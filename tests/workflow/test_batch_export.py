"""M3.5: write-batch / resume / export,含 D15 STALE 级联。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.models import NodeRunRecord
from novel_agent.domain.repos import CanonRepo, PlanningRepo
from novel_agent.domain.schemas import ChapterStatus
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningGates, run_planning_chain
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.production.batch import run_write_batch
from novel_agent.production.export import export_project
from novel_agent.production.loop import ChapterLoopGates, run_chapter_loop
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults
from novel_agent.production.review import reject_chapter
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "batch.db")
    create_all(engine)
    return engine


async def _planned(tmp_path, mock: MockProvider | None = None):
    engine = _engine(tmp_path)
    session = Session(engine)
    repo = PlanningRepo(session)
    project = repo.create_project("说书人传奇", genre="奇幻", boundaries=["禁无代价全能"])
    session.commit()
    mock = mock or MockProvider()
    register_planning_defaults(mock)
    register_chapter_loop_defaults(mock)
    settings = Settings(_env_file=None)
    deps = AgentDeps(
        gateway=ModelGateway(settings, session, {"mock": mock}),
        project_id=project.id,
    )
    await run_planning_chain(
        repo,
        deps,
        brief="说书人发现故事会成真",
        gates=PlanningGates.auto(),
        volume_id="v1",
        chapters_needed=5,
    )
    session.commit()
    return session, deps, mock, project.id


def _count_n3(session: Session, chapter_key: str) -> int:
    recs = session.exec(select(NodeRunRecord)).all()
    return sum(
        1
        for rec in recs
        if rec.node_name == "n3_draft"
        and rec.status == "succeeded"
        and (rec.input_snapshot or {}).get("chapter_key") == chapter_key
    )


async def test_three_chapter_batch_under_mock(tmp_path) -> None:
    session, deps, _mock, project_id = await _planned(tmp_path)
    try:
        batch = await run_write_batch(
            session, deps, project_id, chapter_count=3, yes=True
        )
        session.commit()
        assert len(batch.results) == 3
        assert [item.chapter_key for item in batch.results] == ["v1c001", "v1c002", "v1c003"]
        assert all(item.status is ChapterStatus.CANON_LOCKED for item in batch.results)
        planning = PlanningRepo(session)
        for key in ("v1c001", "v1c002", "v1c003"):
            assert planning.get_chapter(project_id, key).status is ChapterStatus.CANON_LOCKED
        assert CanonRepo(session).committed_count(project_id) >= 3
    finally:
        session.close()


async def test_interrupt_resume_does_not_rerun_successful_nodes(tmp_path) -> None:
    session, deps, _mock, project_id = await _planned(tmp_path)
    try:
        first = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert first.status is ChapterStatus.CANON_LOCKED
        n3_before = _count_n3(session, "v1c001")
        assert n3_before == 1

        resumed = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert resumed.status is ChapterStatus.CANON_LOCKED
        assert _count_n3(session, "v1c001") == n3_before

        batch = await run_write_batch(
            session, deps, project_id, chapter_count=3, yes=True
        )
        session.commit()
        assert [item.chapter_key for item in batch.results] == ["v1c002", "v1c003", "v1c004"]
        assert _count_n3(session, "v1c001") == n3_before
        assert _count_n3(session, "v1c002") == 1
        assert _count_n3(session, "v1c003") == 1
        assert _count_n3(session, "v1c004") == 1
    finally:
        session.close()


async def test_reject_chapter1_cascades_stale_on_later_chapters(tmp_path) -> None:
    session, deps, _mock, project_id = await _planned(tmp_path)
    try:
        batch = await run_write_batch(
            session, deps, project_id, chapter_count=3, yes=False
        )
        session.commit()
        assert [item.status for item in batch.results] == [
            ChapterStatus.HUMAN_REVIEW,
            ChapterStatus.HUMAN_REVIEW,
            ChapterStatus.HUMAN_REVIEW,
        ]
        ch2 = PlanningRepo(session).get_chapter(project_id, "v1c002")
        ch3 = PlanningRepo(session).get_chapter(project_id, "v1c003")
        assert ch2.built_on_provisional is True
        assert ch3.built_on_provisional is True
        assert CanonRepo(session).committed_count(project_id) == 0
        overlay = CanonRepo(session).latest_entity_states(project_id, include_provisional=True)
        assert overlay

        reject_chapter(session, project_id, "v1c001")
        session.commit()
        planning = PlanningRepo(session)
        assert planning.get_chapter(project_id, "v1c001").status is ChapterStatus.NEEDS_REPLAN
        assert planning.get_chapter(project_id, "v1c002").status is ChapterStatus.STALE
        assert planning.get_chapter(project_id, "v1c003").status is ChapterStatus.STALE
        leftover = CanonRepo(session).latest_entity_states(project_id, include_provisional=True)
        assert leftover == CanonRepo(session).latest_entity_states(project_id)
    finally:
        session.close()


async def test_export_files_contain_chapter_text(tmp_path) -> None:
    session, deps, _mock, project_id = await _planned(tmp_path)
    try:
        await run_write_batch(session, deps, project_id, chapter_count=3, yes=True)
        session.commit()
        out_md = tmp_path / "book.md"
        out_txt = tmp_path / "book.txt"
        export_project(session, project_id, "md", out_md)
        export_project(session, project_id, "txt", out_txt)
        assert out_md.is_file()
        assert out_txt.is_file()
        md = out_md.read_text(encoding="utf-8")
        txt = out_txt.read_text(encoding="utf-8")
        assert "苏晚生" in md and "醒木" in md
        assert "苏晚生" in txt and "醒木" in txt
        assert "v1c001" in md and "v1c003" in md
    finally:
        session.close()


@pytest.fixture()
def cli_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    yield db_path
    reset_settings_cache()


def test_cli_write_batch_resume_and_export(cli_db, tmp_path: Path) -> None:
    runner = CliRunner()
    init = runner.invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output

    batch = runner.invoke(
        app, ["write-batch", "--project-id", "1", "--chapters", "3", "--yes"]
    )
    assert batch.exit_code == 0, batch.output
    assert "v1c001" in batch.output and "v1c003" in batch.output

    resume = runner.invoke(app, ["resume", "--project-id", "1", "--yes"])
    assert resume.exit_code == 0, resume.output

    out = tmp_path / "export.md"
    exported = runner.invoke(
        app,
        ["export", "--project-id", "1", "--format", "md", "--out", str(out)],
    )
    assert exported.exit_code == 0, exported.output
    assert out.is_file()
    assert "醒木" in out.read_text(encoding="utf-8")

    engine = build_engine(cli_db)
    with session_scope(engine) as session:
        for key in ("v1c001", "v1c002", "v1c003"):
            assert PlanningRepo(session).get_chapter(1, key).status is ChapterStatus.CANON_LOCKED
        assert _count_n3(session, "v1c001") == 1
