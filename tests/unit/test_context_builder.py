"""M3.1: ContextBuilder deterministically assembles chapter input."""

from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

from novel_agent.context import ContextBuilder
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import CanonRepo, PlanningRepo
from novel_agent.domain.schemas import (
    ChapterOutline,
    CharacterCard,
    PlotUnitCard,
    SceneCard,
    StoryKernel,
)


def _prepared_repos(tmp_path):
    engine = build_engine(tmp_path / "context.db")
    create_all(engine)
    session = session_scope(engine)
    s = session.__enter__()
    planning = PlanningRepo(s)
    project = planning.create_project("上下文测试", boundaries=["项目边界"])
    planning.save_kernel(project.id, StoryKernel.model_validate(KERNEL))
    planning.approve_kernel(project.id, 1)
    planning.upsert_character(project.id, CharacterCard.model_validate(CHARACTER))
    planning.save_volume(project.id, "v1", {"summary": "第一卷摘要"})
    planning.save_unit(project.id, "v1", PlotUnitCard.model_validate(UNIT))
    planning.create_chapter(project.id, ChapterOutline.model_validate(OUTLINE), order_index=1)
    planning.save_scene_cards(project.id, "v1c001", [SceneCard.model_validate(SCENE)])
    return session, planning, CanonRepo(s), project.id


def test_build_orders_context_and_marks_provisional_facts(tmp_path) -> None:
    """Changing the required §12.2 sequence or omitting provisional provenance must fail."""
    session, planning, canon, project_id = _prepared_repos(tmp_path)
    try:
        canon.append_entity_state(
            project_id, "ch_su", "location", "临安茶楼", "已确认", "v1c000"
        )
        canon.append_entity_state(
            project_id, "ch_su", "status", "被传唤", "批次内草案", "v1c000", provisional=True
        )
        canon.upsert_thread(project_id, "thread_fire", status="setup", setup="西市火灾")

        package = ContextBuilder(planning, canon).build(
            project_id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            previous_ending="最近原文",
            earlier_summaries=["早期摘要"],
            retrieval_facts=["低相关检索片段"],
            style_rules="克制叙述",
            prior_feedback="保留动作",
            include_provisional=True,
        )

        assert package.canon_version == "canon_v0"
        assert package.kernel_summary.endswith("读者契约: " + KERNEL["reader_promise"])
        assert [fact.content for fact in package.hard_constraints] == [
            "故事内核: " + KERNEL["reader_promise"],
            "项目边界",
        ]
        assert [(fact.source_chapter, fact.provisional) for fact in package.entity_states] == [
            ("v1c000", False),
            ("v1c000", True),
        ]
        assert package.has_provisional() is True
        assert [thread.thread_id for thread in package.active_threads] == ["thread_fire"]
        assert package.characters == [CharacterCard.model_validate(CHARACTER)]
        assert package.previous_ending == "最近原文"
        assert package.earlier_summaries == ["早期摘要"]
        assert package.style_rules == "克制叙述"
        assert package.prior_feedback == "保留动作"

        committed_only = ContextBuilder(planning, canon).build(
            project_id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要"
        )
        committed_states = [
            (fact.source_chapter, fact.provisional) for fact in committed_only.entity_states
        ]
        assert committed_states == [("v1c000", False)]
    finally:
        session.__exit__(None, None, None)


def test_build_budget_discards_low_priority_context_before_required_inputs(tmp_path) -> None:
    """A truncation policy that removes required plans/states before text context is a bug."""
    session, planning, canon, project_id = _prepared_repos(tmp_path)
    try:
        canon.append_entity_state(project_id, "ch_su", "location", "临安茶楼", "已确认", "v1c000")
        builder = ContextBuilder(planning, canon)
        full = builder.build(
            project_id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            previous_ending="x" * 20,
            earlier_summaries=["y" * 20, "z" * 20],
            retrieval_facts=["a" * 20, "b" * 20],
            style_rules="风格",
        )
        required_size = builder.required_size(full)
        after_one_retrieval_cut = full.model_copy(update={"retrieval_facts": ["b" * 20]})

        trimmed = builder.build(
            project_id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            previous_ending="x" * 20,
            earlier_summaries=["y" * 20, "z" * 20],
            retrieval_facts=["a" * 20, "b" * 20],
            style_rules="风格",
            max_chars=required_size + 1,
        )
        one_cut = builder.build(
            project_id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            previous_ending="x" * 20,
            earlier_summaries=["y" * 20, "z" * 20],
            retrieval_facts=["a" * 20, "b" * 20],
            style_rules="风格",
            max_chars=builder.context_size(after_one_retrieval_cut),
        )

        assert trimmed.outline.chapter_key == "v1c001"
        assert trimmed.scene_cards[0].scene_id == "v1c001_s1"
        assert trimmed.entity_states[0].content.endswith("临安茶楼")
        assert trimmed.hard_constraints == full.hard_constraints
        assert trimmed.previous_ending == ""
        assert trimmed.earlier_summaries == []
        assert trimmed.retrieval_facts == []
        assert builder.context_size(trimmed) <= required_size + 1
        assert one_cut.retrieval_facts == ["b" * 20]
    finally:
        session.__exit__(None, None, None)
