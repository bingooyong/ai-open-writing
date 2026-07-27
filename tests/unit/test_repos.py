"""M1.3 DoD:各仓储 CRUD round-trip;幂等查找;provisional 生命周期(D15)。"""

import pytest
from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT, _issue

from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import CanonRepo, OpsRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import (
    CanonDelta,
    ChapterOutline,
    ChapterStatus,
    CharacterCard,
    JudgeVerdict,
    PlotUnitCard,
    ReviewIssue,
    SceneCard,
    StoryKernel,
)


@pytest.fixture()
def engine(tmp_path):
    e = build_engine(tmp_path / "t.db")
    create_all(e)
    return e


def test_planning_repo_roundtrip(engine) -> None:
    with session_scope(engine) as s:
        repo = PlanningRepo(s)
        p = repo.create_project("测试作品", boundaries=["禁写项A"])
        pid = p.id

        # 内核:两版,批准 v2,取回的是 v2
        repo.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        repo.save_kernel(pid, StoryKernel.model_validate({**KERNEL, "logline": "改后的一句话"}))
        repo.approve_kernel(pid, 2)
        k = repo.get_approved_kernel(pid)
        assert k and k.logline == "改后的一句话"

        # 角色 upsert:两次写同 id 版本+1
        card = CharacterCard.model_validate(CHARACTER)
        repo.upsert_character(pid, card)
        rec = repo.upsert_character(pid, card)
        assert rec.version == 2
        assert repo.get_characters(pid, ["ch_su"])[0].name == "苏晚生"

        # 卷/单元/章/场景
        repo.save_volume(pid, "v1", {"goal": "入局"})
        repo.save_unit(pid, "v1", PlotUnitCard.model_validate(UNIT))
        assert repo.get_unit(pid, "u1").unit_id == "u1"

        outline = ChapterOutline.model_validate(OUTLINE)
        repo.create_chapter(pid, outline, order_index=1)
        assert repo.get_outline(pid, "v1c001").core_event == outline.core_event

        repo.save_scene_cards(pid, "v1c001", [SceneCard.model_validate(SCENE)])
        assert repo.list_scene_cards(pid, "v1c001")[0].scene_id == "v1c001_s1"

        # M3.3b:update_outline bump 版本、重置轮次与状态
        repo.increment_revision_round(pid, "v1c001")
        repo.set_status(pid, "v1c001", ChapterStatus.NEEDS_REPLAN)
        v2 = repo.update_outline(
            pid, "v1c001", ChapterOutline.model_validate({**OUTLINE, "core_event": "改"})
        )
        ch = repo.get_chapter(pid, "v1c001")
        assert v2 == 2 and ch.revision_round == 0 and ch.status == ChapterStatus.PLANNED


def test_production_repo_and_rounds(engine) -> None:
    with session_scope(engine) as s:
        pid = PlanningRepo(s).create_project("p").id
        repo = ProductionRepo(s)
        d1 = repo.create_draft(pid, "v1c001", "candidate_1", "lin1", "正文", {}, "w1", 1)
        d2 = repo.create_draft(
            pid, "v1c001", "candidate_1", "lin1", "正文v2", {}, "w1", 1, revision_of=d1.id
        )

        repo.save_issues(d1.id, [ReviewIssue.model_validate(_issue())])
        issues = repo.list_issues(d1.id)
        assert issues[0].hard_gate is not None and not issues[0].downweighted

        v = JudgeVerdict.model_validate(
            dict(
                verdict="REVISE_LOCAL",
                selected_candidate="candidate_1",
                revision_scope=["v1c001_s1"],
                reasoning_summary="局部修订",
            )
        )
        repo.save_verdict(d1.id, "v1c001", v, round_number=1)
        assert repo.revise_local_rounds("v1c001", [d1.id, d2.id]) == 1
        assert repo.latest_verdict("v1c001").verdict.value == "REVISE_LOCAL"


def test_canon_repo_provisional_lifecycle(engine) -> None:
    """D15:provisional 注入→批准转正 / 退回作废。"""
    with session_scope(engine) as s:
        pid = PlanningRepo(s).create_project("p").id
        repo = CanonRepo(s)

        delta = CanonDelta.model_validate(
            {"chapter_key": "v1c001", "base_canon_version": "canon_v0"}
        )
        rec = repo.save_delta(pid, delta, idempotency_key="idem-1", provisional=True)
        assert repo.get_by_idempotency_key("idem-1").id == rec.id

        repo.append_entity_state(
            pid, "ch_su", "status", "关联人", "问话", "v1c001", provisional=True
        )
        repo.upsert_relationship(
            pid, "ch_su", "ch_shuju", "试探", "名帖", "v1c001", provisional=True
        )

        # 未含 provisional 时查不到;含则可见
        assert ("ch_su", "status") not in repo.latest_entity_states(pid)
        assert ("ch_su", "status") in repo.latest_entity_states(pid, include_provisional=True)

        # 批准 → 转正
        repo.promote_provisional(pid, "v1c001")
        repo.mark_committed(rec.id)
        assert ("ch_su", "status") in repo.latest_entity_states(pid)
        assert repo.current_canon_version(pid) == "canon_v1"

        # 另一章 provisional → 退回作废
        repo.append_entity_state(
            pid, "ch_su", "position", "西市", "追查", "v1c002", provisional=True
        )
        n = repo.discard_provisional(pid, "v1c002")
        assert n == 1
        assert ("ch_su", "position") not in repo.latest_entity_states(pid, include_provisional=True)


def test_ops_repo_idempotency_and_budget(engine) -> None:
    with session_scope(engine) as s:
        pid = PlanningRepo(s).create_project("p").id
        repo = OpsRepo(s)

        run = repo.create_workflow_run(pid, "chapter_loop", chapter_key="v1c001")
        node = repo.start_node(run.id, "N3_draft", "v1c001|o1|draft|a1", {"in": 1})
        repo.finish_node(node.id, "succeeded", {"out": 2})

        # 幂等命中:同 key 直接复用
        hit = repo.find_success_node("v1c001|o1|draft|a1")
        assert hit and hit.output_snapshot == {"out": 2}
        assert repo.find_success_node("不存在") is None

        # 二次 start 同 key → attempt 递增(唯一约束 key+attempt)
        n2 = repo.start_node(run.id, "N3_draft", "v1c001|o1|draft|a1", {})
        assert n2.attempt == 2

        # 审批与调用计数
        repo.save_approval(pid, "chapter", "v1c001", "approved")
        assert repo.has_approval(pid, "chapter", "v1c001")
        repo.record_model_run(
            project_id=pid, chapter_key="v1c001", agent_role="writer",
            provider="mock", model="m", prompt_version="w1",
            input_tokens=10, output_tokens=20, latency_ms=5, cost_estimate=0.0,
        )
        assert repo.calls_for_chapter("v1c001") == 1
