"""卷工厂:滚动窗口续规划、卷翻转、write-batch 续写、D15 STALE。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from typer.testing import CliRunner

from novel_agent.api.app import create_app
from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.models import NodeRunRecord, PlotUnitRecord
from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
from novel_agent.domain.schemas import ChapterStatus
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.graph.projector import project_graph
from novel_agent.lint.bible import lint_bible
from novel_agent.planning.chain import PlanningGates
from novel_agent.planning.conversation import run_bible_conversation
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.planning.outline_tree import assemble_outline_tree
from novel_agent.planning.volume import (
    PlanMoreError,
    plan_more,
    select_write_batch_keys,
    volume_arc_paid_off,
    window_deficit,
)
from novel_agent.production.batch import run_write_batch
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults
from novel_agent.production.review import reject_chapter
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "volume.db")
    create_all(engine)
    return engine


def _lock_chapters(planning: PlanningRepo, project_id: int, keys: list[str] | None = None) -> None:
    targets = keys or [chapter.chapter_key for chapter in planning.list_chapters(project_id)]
    for key in targets:
        planning.set_status(project_id, key, ChapterStatus.CANON_LOCKED)


async def _bibled(tmp_path, *, with_production: bool = False):
    engine = _engine(tmp_path)
    session = Session(engine)
    planning = PlanningRepo(session)
    bible = BibleRepo(session)
    canon = CanonRepo(session)
    project = planning.create_project("说书人传奇", genre="奇幻", boundaries=["禁无代价全能"])
    session.commit()
    mock = MockProvider()
    register_planning_defaults(mock)
    if with_production:
        register_chapter_loop_defaults(mock)
    deps = AgentDeps(
        gateway=ModelGateway(Settings(_env_file=None), session, {"mock": mock}),
        project_id=project.id,
    )
    await run_bible_conversation(
        planning,
        bible,
        canon,
        deps,
        spark="说书人发现故事会成真",
        gates=PlanningGates.auto(),
        volume_id="v1",
        chapters_needed=5,
        skip_concept_judge=True,
    )
    session.commit()
    return session, deps, planning, bible, canon, project.id


async def test_plan_more_after_five_locked_adds_next_v1_slice(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path)
    try:
        _lock_chapters(planning, pid)
        session.commit()
        assert window_deficit(planning.list_chapters(pid), window=5) == 5

        result = await plan_more(
            planning, bible, canon, deps, pid, PlanningGates.auto(), window=5
        )
        session.commit()

        assert result.chapter_keys == [f"v1c{i:03d}" for i in range(6, 11)]
        assert result.volume_id == "v1"
        assert result.opened_new_volume is False
        for key in result.chapter_keys:
            chapter = planning.get_chapter(pid, key)
            assert chapter.status is ChapterStatus.PLANNED
            scenes = planning.list_scene_cards(pid, key)
            assert scenes
            outline = planning.get_outline(pid, key)
            assert outline.cited_conflict_ids or outline.cited_beat_ids

        keys = [chapter.chapter_key for chapter in planning.list_chapters(pid)]
        report = lint_bible(
            structure=bible.get_structure_map(pid),
            conflicts=bible.list_conflicts(pid),
            payoff_beats=bible.list_payoff_beats(pid),
            rolling_keys=keys,
            outline_citations=[
                (ch.chapter_key, outline.cited_conflict_ids, outline.cited_beat_ids)
                for ch in planning.list_chapters(pid)
                if (outline := planning.get_outline(pid, ch.chapter_key))
            ],
        )
        assert report.passed
        tree = assemble_outline_tree(planning, pid)
        assert [vol["volume_id"] for vol in tree["volumes"]] == ["v1"]
        chapter_keys = [
            node["chapter_key"]
            for unit in tree["volumes"][0]["units"]
            for node in unit["chapters"]
        ]
        assert "v1c006" in chapter_keys
    finally:
        session.close()


async def test_plan_more_is_noop_when_window_is_full(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path)
    try:
        result = await plan_more(
            planning, bible, canon, deps, pid, PlanningGates.auto(), window=5
        )
        assert result.chapter_keys == []
        assert "window_full" in result.skipped
        assert [ch.chapter_key for ch in planning.list_chapters(pid)] == [
            f"v1c{i:03d}" for i in range(1, 6)
        ]
    finally:
        session.close()


async def test_volume_rollover_when_instructed_creates_v2(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path)
    try:
        _lock_chapters(planning, pid)
        session.commit()
        result = await plan_more(
            planning,
            bible,
            canon,
            deps,
            pid,
            PlanningGates.auto(),
            window=5,
            open_volume=True,
        )
        session.commit()
        assert result.opened_new_volume is True
        assert result.volume_id == "v2"
        assert result.chapter_keys == [f"v2c{i:03d}" for i in range(1, 6)]
        volumes = [vol.volume_id for vol in planning.list_volumes(pid)]
        assert volumes == ["v1", "v2"]
        units = planning.list_unit_records(pid)
        assert any(rec.volume_id == "v2" for rec in units)
        kernel = planning.get_approved_kernel(pid)
        assert kernel is not None
        assert bible.get_structure_map(pid) is not None
        tree = assemble_outline_tree(planning, pid)
        assert [vol["volume_id"] for vol in tree["volumes"]] == ["v1", "v2"]
    finally:
        session.close()


async def test_volume_rollover_when_unit_payoff_is_marked_done(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path)
    try:
        _lock_chapters(planning, pid)
        unit = session.exec(
            select(PlotUnitRecord).where(PlotUnitRecord.project_id == pid)
        ).one()
        unit.status = "locked"
        session.add(unit)
        session.commit()
        assert volume_arc_paid_off(planning, bible, pid) is True
        result = await plan_more(
            planning, bible, canon, deps, pid, PlanningGates.auto(), window=5
        )
        session.commit()
        assert result.opened_new_volume is True
        assert result.volume_id == "v2"
        assert result.chapter_keys[0] == "v2c001"
    finally:
        session.close()


async def test_later_outlines_inherit_reveal_forbidden(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path)
    try:
        first = planning.get_outline(pid, "v1c001")
        assert "书局主人真名" in first.reveal_forbidden
        dirty = first.model_copy(
            update={
                "reveal_forbidden": list(
                    dict.fromkeys([*first.reveal_forbidden, "反噬设定", "主角主人真名"])
                )
            }
        )
        planning.update_outline(pid, "v1c001", dirty)
        _lock_chapters(planning, pid)
        session.commit()
        result = await plan_more(
            planning, bible, canon, deps, pid, PlanningGates.auto(), window=5
        )
        later = planning.get_outline(pid, result.chapter_keys[0])
        assert "书局主人真名" in later.reveal_forbidden
        assert "主角主人真名" in later.reveal_forbidden
        assert "反噬设定" not in later.reveal_forbidden
        assert "书局主人真名" not in later.reveal_allowed
        blob = f"{later.core_event}{later.title}{later.exit_hook}"
        assert "书局主人真名" not in blob
    finally:
        session.close()


def test_select_write_batch_keys_skips_locked_then_takes_count() -> None:
    class _Chapter:
        def __init__(self, key: str, status: ChapterStatus) -> None:
            self.chapter_key = key
            self.status = status

    class _Repo:
        def list_chapters(self, _project_id: int) -> list[_Chapter]:
            return [
                _Chapter("v1c001", ChapterStatus.CANON_LOCKED),
                _Chapter("v1c002", ChapterStatus.CANON_LOCKED),
                _Chapter("v1c003", ChapterStatus.CANON_LOCKED),
                _Chapter("v1c004", ChapterStatus.CANON_LOCKED),
                _Chapter("v1c005", ChapterStatus.CANON_LOCKED),
                _Chapter("v1c006", ChapterStatus.PLANNED),
                _Chapter("v1c007", ChapterStatus.PLANNED),
                _Chapter("v1c008", ChapterStatus.PLANNED),
            ]

    keys = select_write_batch_keys(_Repo(), 1, 3)  # type: ignore[arg-type]
    assert keys == ["v1c006", "v1c007", "v1c008"]
    from_ch = select_write_batch_keys(_Repo(), 1, 2, from_chapter="v1c007")  # type: ignore[arg-type]
    assert from_ch == ["v1c007", "v1c008"]


async def test_write_batch_from_chapter_continues_and_reject_stales_later(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path, with_production=True)
    try:
        _lock_chapters(planning, pid)
        session.commit()
        planned = await plan_more(
            planning, bible, canon, deps, pid, PlanningGates.auto(), window=5
        )
        session.commit()
        assert planned.chapter_keys[0] == "v1c006"

        batch = await run_write_batch(
            session,
            deps,
            pid,
            chapter_count=3,
            yes=False,
            from_chapter="v1c006",
        )
        session.commit()
        assert [item.chapter_key for item in batch.results] == ["v1c006", "v1c007", "v1c008"]
        assert all(item.status is ChapterStatus.HUMAN_REVIEW for item in batch.results)

        stale = reject_chapter(session, pid, "v1c006")
        session.commit()
        assert planning.get_chapter(pid, "v1c006").status is ChapterStatus.NEEDS_REPLAN
        assert "v1c007" in stale and "v1c008" in stale
        assert planning.get_chapter(pid, "v1c007").status is ChapterStatus.STALE
        assert planning.get_chapter(pid, "v1c008").status is ChapterStatus.STALE
        assert planning.get_chapter(pid, "v1c009").status is ChapterStatus.PLANNED
    finally:
        session.close()


async def test_write_batch_without_from_chapter_skips_locked_prefix(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path, with_production=True)
    try:
        _lock_chapters(planning, pid)
        session.commit()
        await plan_more(planning, bible, canon, deps, pid, PlanningGates.auto(), window=5)
        session.commit()
        batch = await run_write_batch(session, deps, pid, chapter_count=3, yes=True)
        session.commit()
        assert [item.chapter_key for item in batch.results] == ["v1c006", "v1c007", "v1c008"]
        assert all(item.status is ChapterStatus.CANON_LOCKED for item in batch.results)
    finally:
        session.close()


def _count_n3(session: Session, chapter_key: str) -> int:
    recs = session.exec(select(NodeRunRecord)).all()
    return sum(
        1
        for rec in recs
        if rec.node_name == "n3_draft"
        and rec.status == "succeeded"
        and (rec.input_snapshot or {}).get("chapter_key") == chapter_key
    )


async def test_resume_does_not_rerun_success_after_plan_more(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path, with_production=True)
    try:
        first = await run_write_batch(session, deps, pid, chapter_count=3, yes=True)
        session.commit()
        assert first.results[0].chapter_key == "v1c001"
        n3 = _count_n3(session, "v1c001")
        assert n3 == 1
        resumed = await run_write_batch(session, deps, pid, chapter_count=3, yes=True)
        session.commit()
        assert resumed.results[0].chapter_key == "v1c004"
        assert _count_n3(session, "v1c001") == n3
    finally:
        session.close()


async def test_graph_projector_still_works_after_plan_more(tmp_path) -> None:
    session, deps, planning, bible, canon, pid = await _bibled(tmp_path)
    try:
        _lock_chapters(planning, pid)
        session.commit()
        await plan_more(planning, bible, canon, deps, pid, PlanningGates.auto(), window=5)
        session.commit()
        graph = project_graph(pid, planning, bible, canon)
        assert graph.project_id == pid
        assert graph.nodes
        assert any(node.id == "ch_su" for node in graph.nodes)
    finally:
        session.close()


async def test_plan_more_requires_bible(tmp_path) -> None:
    engine = _engine(tmp_path)
    session = Session(engine)
    try:
        planning = PlanningRepo(session)
        project = planning.create_project("空项目")
        session.commit()
        deps = AgentDeps(
            gateway=ModelGateway(Settings(_env_file=None), session, {"mock": MockProvider()}),
            project_id=project.id,
        )
        try:
            await plan_more(
                planning,
                BibleRepo(session),
                CanonRepo(session),
                deps,
                project.id or 0,
                PlanningGates.auto(),
            )
            raise AssertionError("expected PlanMoreError")
        except PlanMoreError:
            pass
    finally:
        session.close()


def test_cli_plan_more_and_write_batch_from_chapter(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    runner = CliRunner()
    try:
        init = runner.invoke(
            app,
            [
                "init",
                "说书人传奇",
                "--brief",
                "说书人发现故事会成真",
                "--yes",
                "--skip-concept-judge",
            ],
        )
        assert init.exit_code == 0, init.output
        engine = build_engine(db_path)
        with Session(engine) as session:
            planning = PlanningRepo(session)
            _lock_chapters(planning, 1)
            session.commit()
        more = runner.invoke(app, ["plan-more", "--project-id", "1", "--yes"])
        assert more.exit_code == 0, more.output
        assert "v1c006" in more.output
        batch = runner.invoke(
            app,
            [
                "write-batch",
                "--project-id",
                "1",
                "--chapters",
                "3",
                "--from-chapter",
                "v1c006",
                "--yes",
            ],
        )
        assert batch.exit_code == 0, batch.output
        assert "v1c006" in batch.output
    finally:
        reset_settings_cache()


def test_api_plan_more_and_outline_tree(tmp_path) -> None:
    engine = build_engine(tmp_path / "desk.db")
    create_all(engine)
    settings = Settings(_env_file=None, db_path=tmp_path / "desk.db")
    with TestClient(create_app(settings=settings, engine=engine)) as client:
        created = client.post(
            "/projects",
            json={
                "title": "卷工厂",
                "spark": "说书人发现故事会成真",
                "auto_bible": True,
                "skip_concept_judge": True,
            },
        )
        assert created.status_code == 200, created.text
        pid = created.json()["id"]
        with Session(engine) as session:
            planning = PlanningRepo(session)
            _lock_chapters(planning, pid)
            session.commit()
        more = client.post(f"/projects/{pid}/plan-more", json={"window": 5})
        assert more.status_code == 200, more.text
        body = more.json()
        assert body["chapter_keys"][0] == "v1c006"
        tree = client.get(f"/projects/{pid}/outline-tree")
        assert tree.status_code == 200
        keys = [
            chapter["chapter_key"]
            for volume in tree.json()["volumes"]
            for unit in volume["units"]
            for chapter in unit["chapters"]
        ]
        assert "v1c006" in keys
        batch = client.post(
            f"/projects/{pid}/write-batch",
            json={"chapters": 3, "yes": True, "from_chapter": "v1c006"},
        )
        assert batch.status_code == 200, batch.text
        assert batch.json()["results"][0]["chapter_key"] == "v1c006"
