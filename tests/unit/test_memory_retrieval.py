"""Stage 2: 提交正史后检索能命中植入事实;重建索引幂等;无网络。"""

from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

from novel_agent.context import ContextBuilder
from novel_agent.domain.canon_writer import CanonWriter
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import CanonRepo, OpsRepo, PlanningRepo
from novel_agent.domain.schemas import (
    CanonDelta,
    ChapterOutline,
    CharacterCard,
    PlotUnitCard,
    SceneCard,
    StoryKernel,
)
from novel_agent.memory import memory_retrieval_for_session


def _seed_project(session, *, plant: bool = True) -> int:
    planning = PlanningRepo(session)
    project = planning.create_project("检索测试", boundaries=["项目边界"])
    assert project.id is not None
    planning.save_kernel(project.id, StoryKernel.model_validate(KERNEL))
    planning.approve_kernel(project.id, 1)
    planning.upsert_character(project.id, CharacterCard.model_validate(CHARACTER))
    planning.save_volume(project.id, "v1", {"summary": "第一卷摘要"})
    planning.save_unit(project.id, "v1", PlotUnitCard.model_validate(UNIT))
    planning.create_chapter(project.id, ChapterOutline.model_validate(OUTLINE), order_index=1)
    planning.save_scene_cards(project.id, "v1c001", [SceneCard.model_validate(SCENE)])
    if plant:
        canon = CanonRepo(session)
        canon.append_entity_state(
            project.id,
            "ch_su",
            "fact",
            "西市火灾由说书人昨夜随口编造的桥段成真",
            "开局植入",
            "v1c001",
        )
        canon.append_entity_state(
            project.id,
            "ch_unrelated",
            "fact",
            "北境商队走失三头骆驼与本书无关",
            "闲笔",
            "v9c099",
        )
    return project.id


def test_retrieve_finds_planted_committed_fact_not_unrelated(tmp_path) -> None:
    engine = build_engine(tmp_path / "mem.db")
    create_all(engine)
    with session_scope(engine) as session:
        project_id = _seed_project(session)
        OpsRepo(session).save_approval(project_id, "chapter", "v1c001", "approved")
        CanonWriter(session, project_id).finalize(
            CanonDelta.model_validate(
                {
                    "chapter_key": "v1c001",
                    "base_canon_version": "canon_v0",
                    "new_facts": [
                        {
                            "entity_id": "ch_su",
                            "state_type": "fact",
                            "old_value": "",
                            "new_value": "临安西市火场已封锁",
                            "reason": "火灾现场",
                        }
                    ],
                }
            ),
            "idem-retrieve",
            "v1c001",
        )
        hits = memory_retrieval_for_session(session).retrieve(
            project_id, "西市火灾 说书人编造的桥段"
        )
    texts = [fact.text for fact in hits]
    assert any("西市火灾" in text for text in texts)
    assert all("北境商队" not in text for text in texts[:3])
    assert hits[0].fact_id.startswith("entity:") or "西市" in hits[0].text


def test_reindex_is_idempotent(tmp_path) -> None:
    engine = build_engine(tmp_path / "mem.db")
    create_all(engine)
    with session_scope(engine) as session:
        project_id = _seed_project(session)
        retrieval = memory_retrieval_for_session(session)
        first = retrieval.reindex(project_id)
        second = retrieval.reindex(project_id)
        third = retrieval.reindex(project_id)
        assert first == second == third
        assert first >= 2
        again = retrieval.retrieve(project_id, "西市火灾")
        once_more = retrieval.retrieve(project_id, "西市火灾")
        assert [fact.fact_id for fact in again] == [fact.fact_id for fact in once_more]


def test_context_builder_fills_retrieval_facts_and_trims(tmp_path) -> None:
    engine = build_engine(tmp_path / "mem.db")
    create_all(engine)
    with session_scope(engine) as session:
        project_id = _seed_project(session)
        retrieval = memory_retrieval_for_session(session)
        retrieval.reindex(project_id)
        builder = ContextBuilder(PlanningRepo(session), CanonRepo(session), retrieval=retrieval)
        full = builder.build(
            project_id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            previous_ending="x" * 40,
            earlier_summaries=["y" * 40],
        )
        assert full.retrieval_facts
        assert any("西市火灾" in item for item in full.retrieval_facts)
        required = builder.required_size(full)
        trimmed = builder.build(
            project_id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            previous_ending="x" * 40,
            earlier_summaries=["y" * 40],
            max_chars=required + 1,
        )
        assert trimmed.hard_constraints == full.hard_constraints
        assert builder.context_size(trimmed) <= required + 1
        assert trimmed.outline.chapter_key == "v1c001"
