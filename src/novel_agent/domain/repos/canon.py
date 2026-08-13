"""正史仓储:CanonDelta 落库、实体/关系/伏笔当前态读写、provisional 管理(D15)。

注意:对外的"提交正史"唯一入口是 canon_writer.CanonWriter(M1.7);
本仓储只提供底层读写原语。
"""

from datetime import UTC, datetime

from sqlmodel import Session, select

from novel_agent.domain.models import (
    CanonDeltaRecord,
    EntityStateRecord,
    PlotThreadRecord,
    RelationshipStateRecord,
)
from novel_agent.domain.schemas import CanonDelta


class CanonRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- delta 记录 ----

    def save_delta(
        self,
        project_id: int,
        delta: CanonDelta,
        idempotency_key: str,
        provisional: bool = False,
    ) -> CanonDeltaRecord:
        rec = CanonDeltaRecord(
            project_id=project_id,
            chapter_key=delta.chapter_key,
            base_canon_version=delta.base_canon_version,
            provisional=provisional,
            idempotency_key=idempotency_key,
            payload=delta.model_dump(),
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_by_idempotency_key(self, key: str) -> CanonDeltaRecord | None:
        return self.s.exec(
            select(CanonDeltaRecord).where(CanonDeltaRecord.idempotency_key == key)
        ).first()

    def mark_committed(self, delta_id: int) -> None:
        rec = self.s.get_one(CanonDeltaRecord, delta_id)
        rec.status = "committed"
        rec.provisional = False
        rec.committed_at = datetime.now(UTC)
        self.s.add(rec)

    def committed_count(self, project_id: int) -> int:
        return len(
            self.s.exec(
                select(CanonDeltaRecord).where(
                    CanonDeltaRecord.project_id == project_id,
                    CanonDeltaRecord.status == "committed",
                )
            ).all()
        )

    def current_canon_version(self, project_id: int) -> str:
        """canon 快照版本 = 已提交 delta 数(单写入器保证单调)。"""
        return f"canon_v{self.committed_count(project_id)}"

    # ---- 实体状态 ----

    def append_entity_state(
        self,
        project_id: int,
        entity_id: str,
        state_type: str,
        value: str,
        reason: str,
        source_chapter: str,
        provisional: bool = False,
    ) -> None:
        self.s.add(
            EntityStateRecord(
                project_id=project_id,
                entity_id=entity_id,
                state_type=state_type,
                value=value,
                reason=reason,
                source_chapter=source_chapter,
                provisional=provisional,
            )
        )

    def latest_entity_states(
        self, project_id: int, include_provisional: bool = False
    ) -> dict[tuple[str, str], EntityStateRecord]:
        """每个 (entity_id, state_type) 的最新记录;D15 决定是否叠加 provisional。"""
        stmt = select(EntityStateRecord).where(EntityStateRecord.project_id == project_id)
        if not include_provisional:
            stmt = stmt.where(EntityStateRecord.provisional == False)  # noqa: E712
        result: dict[tuple[str, str], EntityStateRecord] = {}
        for rec in self.s.exec(stmt.order_by(EntityStateRecord.id)).all():  # type: ignore[arg-type]
            result[(rec.entity_id, rec.state_type)] = rec
        return result

    # ---- 关系 ----

    def upsert_relationship(
        self,
        project_id: int,
        party_a: str,
        party_b: str,
        state: str,
        evidence: str,
        source_chapter: str,
        provisional: bool = False,
    ) -> None:
        a, b = sorted([party_a, party_b])
        rec = self.s.exec(
            select(RelationshipStateRecord).where(
                RelationshipStateRecord.project_id == project_id,
                RelationshipStateRecord.party_a == a,
                RelationshipStateRecord.party_b == b,
            )
        ).first()
        if rec:
            rec.state = state
            rec.evidence = evidence
            rec.source_chapter = source_chapter
            rec.provisional = provisional
            rec.updated_at = datetime.now(UTC)
        else:
            rec = RelationshipStateRecord(
                project_id=project_id,
                party_a=a,
                party_b=b,
                state=state,
                evidence=evidence,
                source_chapter=source_chapter,
                provisional=provisional,
            )
        self.s.add(rec)

    def get_relationship(
        self, project_id: int, party_a: str, party_b: str
    ) -> RelationshipStateRecord | None:
        a, b = sorted([party_a, party_b])
        return self.s.exec(
            select(RelationshipStateRecord).where(
                RelationshipStateRecord.project_id == project_id,
                RelationshipStateRecord.party_a == a,
                RelationshipStateRecord.party_b == b,
            )
        ).first()

    def list_relationships(self, project_id: int) -> list[RelationshipStateRecord]:
        return list(
            self.s.exec(
                select(RelationshipStateRecord)
                .where(RelationshipStateRecord.project_id == project_id)
                .order_by(
                    RelationshipStateRecord.party_a,  # type: ignore[arg-type]
                    RelationshipStateRecord.party_b,  # type: ignore[arg-type]
                )
            ).all()
        )

    def list_deltas(self, project_id: int) -> list[CanonDeltaRecord]:
        return list(
            self.s.exec(
                select(CanonDeltaRecord)
                .where(CanonDeltaRecord.project_id == project_id)
                .order_by(CanonDeltaRecord.id)  # type: ignore[arg-type]
            ).all()
        )

    # ---- 伏笔线 ----

    def upsert_thread(
        self,
        project_id: int,
        thread_id: str,
        status: str | None = None,
        setup: str | None = None,
        note: str | None = None,
    ) -> PlotThreadRecord:
        rec = self.s.exec(
            select(PlotThreadRecord).where(
                PlotThreadRecord.project_id == project_id,
                PlotThreadRecord.thread_id == thread_id,
            )
        ).first()
        if not rec:
            rec = PlotThreadRecord(project_id=project_id, thread_id=thread_id)
        if status:
            rec.status = status
        if setup:
            rec.setup = setup
        if note:
            notes = rec.payload.get("notes", []) if rec.payload else []
            rec.payload = {**(rec.payload or {}), "notes": [*notes, note]}
        rec.updated_at = datetime.now(UTC)
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_thread(self, project_id: int, thread_id: str) -> PlotThreadRecord | None:
        return self.s.exec(
            select(PlotThreadRecord).where(
                PlotThreadRecord.project_id == project_id,
                PlotThreadRecord.thread_id == thread_id,
            )
        ).first()

    def list_threads(self, project_id: int) -> list[PlotThreadRecord]:
        """按业务键稳定读取项目伏笔状态。"""
        return list(
            self.s.exec(
                select(PlotThreadRecord)
                .where(PlotThreadRecord.project_id == project_id)
                .order_by(PlotThreadRecord.thread_id)  # type: ignore[arg-type]
            ).all()
        )

    # ---- D15:provisional 生命周期 ----

    def promote_provisional(self, project_id: int, chapter_key: str) -> None:
        """章节批准:该章 provisional 状态转正。"""
        for rec in self.s.exec(
            select(EntityStateRecord).where(
                EntityStateRecord.project_id == project_id,
                EntityStateRecord.source_chapter == chapter_key,
                EntityStateRecord.provisional == True,  # noqa: E712
            )
        ).all():
            rec.provisional = False
            self.s.add(rec)
        for rel in self.s.exec(
            select(RelationshipStateRecord).where(
                RelationshipStateRecord.project_id == project_id,
                RelationshipStateRecord.source_chapter == chapter_key,
                RelationshipStateRecord.provisional == True,  # noqa: E712
            )
        ).all():
            rel.provisional = False
            self.s.add(rel)

    def discard_provisional(self, project_id: int, chapter_key: str) -> int:
        """章节被退回:作废该章 provisional 增量(STALE 级联的一部分)。返回作废条数。"""
        n = 0
        for rec in self.s.exec(
            select(EntityStateRecord).where(
                EntityStateRecord.project_id == project_id,
                EntityStateRecord.source_chapter == chapter_key,
                EntityStateRecord.provisional == True,  # noqa: E712
            )
        ).all():
            self.s.delete(rec)
            n += 1
        for rel in self.s.exec(
            select(RelationshipStateRecord).where(
                RelationshipStateRecord.project_id == project_id,
                RelationshipStateRecord.source_chapter == chapter_key,
                RelationshipStateRecord.provisional == True,  # noqa: E712
            )
        ).all():
            self.s.delete(rel)
            n += 1
        for delta in self.s.exec(
            select(CanonDeltaRecord).where(
                CanonDeltaRecord.project_id == project_id,
                CanonDeltaRecord.chapter_key == chapter_key,
                CanonDeltaRecord.provisional == True,  # noqa: E712
            )
        ).all():
            delta.status = "rolled_back"
            delta.provisional = False
            self.s.add(delta)
            n += 1
        return n
