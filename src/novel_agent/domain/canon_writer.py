"""CanonWriter:正史唯一写入器(D10/Spec §6 N9)。

流程(与 Spec §6/D15 对齐):
- stage_provisional():批次连跑时先行注入提案态(provisional=True),供后章上下文;
- finalize():人工批准后转正+落 delta 提交记录+Git 检查点;
- 退回时的作废走 CanonRepo.discard_provisional(由 STALE 级联调用)。

冲突校验(阶段0 最小集,覆盖回归样本 R1 类):
1. 死亡守卫:实体当前 status 含"死"仍被变更 → 冲突;
2. old_value 断言:提案声称的旧值与当前值不符 → 冲突;
3. 关系前态断言:from_state 与当前关系不符 → 冲突。
"""

import logging
import subprocess
from pathlib import Path

from sqlmodel import Session

from novel_agent.domain.models import CanonDeltaRecord
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.ops import OpsRepo
from novel_agent.domain.schemas import CanonDelta, EntityStateChange
from novel_agent.memory.factory import memory_retrieval_for_session
from novel_agent.memory.protocol import MemoryRetrieval

logger = logging.getLogger(__name__)


class CanonConflict(Exception):
    def __init__(self, conflicts: list[str]) -> None:
        self.conflicts = conflicts
        super().__init__("正史冲突: " + ";".join(conflicts))


class CanonWriter:
    def __init__(
        self,
        session: Session,
        project_id: int,
        git_root: Path | None = None,
        retrieval: MemoryRetrieval | None = None,
    ) -> None:
        self.s = session
        self.project_id = project_id
        self.git_root = git_root
        self.retrieval = retrieval
        self.canon = CanonRepo(session)
        self.ops = OpsRepo(session)

    # ---- 校验 ----

    def validate(self, delta: CanonDelta, include_provisional: bool = True) -> list[str]:
        """返回冲突清单;空 = 通过。批次内校验须叠加 provisional(D15)。"""
        current = self.canon.latest_entity_states(
            self.project_id, include_provisional=include_provisional
        )
        conflicts: list[str] = []

        changes: list[EntityStateChange] = [
            *delta.new_facts,
            *delta.character_state_changes,
            *delta.knowledge_changes,
            *delta.resource_changes,
        ]
        for ch in changes:
            cur_status = current.get((ch.entity_id, "status"))
            if cur_status and "死" in cur_status.value:
                conflicts.append(
                    f"死亡守卫: {ch.entity_id} 当前状态为「{cur_status.value}」仍被变更"
                )
                continue
            cur = current.get((ch.entity_id, ch.state_type.value))
            if ch.old_value and cur and cur.value != ch.old_value:
                conflicts.append(
                    f"旧值断言失败: {ch.entity_id}.{ch.state_type.value} "
                    f"当前「{cur.value}」≠ 提案声称「{ch.old_value}」"
                )

        for rel in delta.relationship_changes:
            existing = self.canon.get_relationship(self.project_id, *rel.parties)
            if existing and existing.state != rel.from_state:
                conflicts.append(
                    f"关系前态断言失败: {rel.parties} 当前「{existing.state}」"
                    f"≠ 提案声称「{rel.from_state}」"
                )
        return conflicts

    # ---- 写入(字段→表映射见 Spec §5) ----

    def _apply(self, delta: CanonDelta, provisional: bool) -> None:
        for ch in [
            *delta.new_facts,
            *delta.character_state_changes,
            *delta.knowledge_changes,
            *delta.resource_changes,
        ]:
            self.canon.append_entity_state(
                self.project_id,
                ch.entity_id,
                ch.state_type.value,
                ch.new_value,
                ch.reason,
                delta.chapter_key,
                provisional=provisional,
            )
        for rel in delta.relationship_changes:
            self.canon.upsert_relationship(
                self.project_id,
                rel.parties[0],
                rel.parties[1],
                rel.to_state,
                rel.evidence,
                delta.chapter_key,
                provisional=provisional,
            )
        for t in delta.foreshadowing_created:
            self.canon.upsert_thread(
                self.project_id, t.thread_id, status="setup", setup=t.note, note=t.note
            )
        for t in delta.foreshadowing_progressed:
            self.canon.upsert_thread(
                self.project_id, t.thread_id, status="progressing", note=t.note
            )
        for t in delta.foreshadowing_resolved:
            self.canon.upsert_thread(self.project_id, t.thread_id, status="resolved", note=t.note)
        # world_rule_proposals → project.world_rules 带变更记录
        if delta.world_rule_proposals:
            from novel_agent.domain.models import ProjectRecord

            proj = self.s.get_one(ProjectRecord, self.project_id)
            log = proj.world_rules.get("__changelog__", [])
            proj.world_rules = {
                **proj.world_rules,
                "__changelog__": [
                    *log,
                    *[
                        {"chapter": delta.chapter_key, "rule": r}
                        for r in delta.world_rule_proposals
                    ],
                ],
            }
            self.s.add(proj)

    # ---- 对外入口 ----

    def stage_provisional(self, delta: CanonDelta, idempotency_key: str) -> CanonDeltaRecord:
        """批次连跑:提案态注入(D15)。幂等:同 key 已存在直接返回。"""
        existing = self.canon.get_by_idempotency_key(idempotency_key)
        if existing:
            return existing
        conflicts = self.validate(delta, include_provisional=True)
        if conflicts:
            raise CanonConflict(conflicts)
        rec = self.canon.save_delta(self.project_id, delta, idempotency_key, provisional=True)
        self._apply(delta, provisional=True)
        return rec

    def finalize(
        self, delta: CanonDelta, idempotency_key: str, chapter_key: str
    ) -> CanonDeltaRecord:
        """人工批准后的正式提交(N9)。要求 Approval 存在;幂等防重复提交。"""
        if not self.ops.has_approval(self.project_id, "chapter", chapter_key):
            raise PermissionError(f"章 {chapter_key} 无人工批准记录,拒绝提交正史(PRD §12.3)")

        existing = self.canon.get_by_idempotency_key(idempotency_key)
        if existing and existing.status == "committed":
            return existing  # 幂等:不重复提交

        if existing and existing.provisional:
            # 批次模式:提案态转正
            assert existing.id is not None
            self.canon.promote_provisional(self.project_id, chapter_key)
            self.canon.mark_committed(existing.id)
            rec = existing
        else:
            # 单章模式:校验(只对已提交态)后直接落正式
            conflicts = self.validate(delta, include_provisional=False)
            if conflicts:
                raise CanonConflict(conflicts)
            rec = self.canon.save_delta(self.project_id, delta, idempotency_key, provisional=False)
            self._apply(delta, provisional=False)
            assert rec.id is not None
            self.canon.mark_committed(rec.id)

        self._git_checkpoint(chapter_key)
        self._reindex()
        return rec

    def _reindex(self) -> None:
        retrieval = self.retrieval or memory_retrieval_for_session(self.s)
        retrieval.reindex(self.project_id)

    def _git_checkpoint(self, chapter_key: str) -> None:
        """D12:git 失败只告警,不回滚 canon 事务。"""
        if self.git_root is None:
            return
        try:
            subprocess.run(
                ["git", "add", "-A"], cwd=self.git_root, check=True, capture_output=True, timeout=30
            )
            subprocess.run(
                ["git", "commit", "-m", f"canon: {chapter_key} 正史提交", "--allow-empty"],
                cwd=self.git_root,
                check=True,
                capture_output=True,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("git 检查点失败(不影响 canon 事务): %s", exc)
