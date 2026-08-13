"""M3.4: novel review-batch / approve 人工门禁。"""

from __future__ import annotations

import subprocess

import pytest
from sqlmodel import Session
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import CanonRepo, OpsRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus, VerdictType
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningGates, run_planning_chain
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.production.loop import ChapterLoopGates, run_chapter_loop
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults
from novel_agent.production.review import (
    approve_chapter,
    list_review_queue,
    mark_locked_ranges,
    reject_chapter,
)
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "gate.db")
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


async def test_approve_locks_canon_and_writes_checkpoint(tmp_path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "t"], check=True)

    session, deps, _mock, project_id = await _planned(tmp_path)
    try:
        held = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.hold()
        )
        session.commit()
        assert held.status is ChapterStatus.HUMAN_REVIEW
        assert held.verdict is VerdictType.PASS
        queue = list_review_queue(session, project_id)
        assert [item.chapter_key for item in queue] == ["v1c001"]
        assert "茶楼" in queue[0].draft_text
        assert queue[0].verdict is VerdictType.PASS
        assert queue[0].issues

        result = await approve_chapter(
            session, deps, project_id, "v1c001", git_root=repo_dir
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        chapter = PlanningRepo(session).get_chapter(project_id, "v1c001")
        assert chapter.status is ChapterStatus.CANON_LOCKED
        assert OpsRepo(session).has_approval(project_id, "chapter", "v1c001")
        assert CanonRepo(session).committed_count(project_id) >= 1
        log = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "--oneline"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "canon: v1c001" in log
    finally:
        session.close()


async def test_reject_sends_chapter_to_needs_replan(tmp_path) -> None:
    session, deps, _mock, project_id = await _planned(tmp_path)
    try:
        held = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.hold()
        )
        session.commit()
        assert held.status is ChapterStatus.HUMAN_REVIEW
        reject_chapter(session, project_id, "v1c001")
        session.commit()
        chapter = PlanningRepo(session).get_chapter(project_id, "v1c001")
        assert chapter.status is ChapterStatus.NEEDS_REPLAN
        assert not OpsRepo(session).has_approval(project_id, "chapter", "v1c001")
        assert CanonRepo(session).committed_count(project_id) == 0
    finally:
        session.close()


async def test_mark_locked_ranges_persists_on_draft(tmp_path) -> None:
    session, deps, _mock, project_id = await _planned(tmp_path)
    try:
        await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.hold()
        )
        session.commit()
        mark_locked_ranges(session, project_id, "v1c001", ["醒木一响满堂静"])
        session.commit()
        draft = ProductionRepo(session).latest_chapter_draft(project_id, "v1c001")
        assert draft is not None
        assert draft.locked_ranges == ["醒木一响满堂静"]
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


def test_cli_approve_yes_locks_canon(cli_db) -> None:
    runner = CliRunner()
    init = runner.invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output
    held = runner.invoke(
        app, ["write-chapter", "--project-id", "1", "--chapter-key", "v1c001"]
    )
    assert held.exit_code == 0, held.output
    assert "HUMAN_REVIEW" in held.output

    listed = runner.invoke(app, ["review-batch", "--project-id", "1", "--yes"])
    assert listed.exit_code == 0, listed.output
    assert "v1c001" in listed.output

    engine = build_engine(cli_db)
    with session_scope(engine) as session:
        chapter = PlanningRepo(session).get_chapter(1, "v1c001")
        assert chapter.status is ChapterStatus.CANON_LOCKED
        assert CanonRepo(session).committed_count(1) >= 1


def test_cli_approve_command_yes(cli_db) -> None:
    runner = CliRunner()
    init = runner.invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output
    held = runner.invoke(
        app, ["write-chapter", "--project-id", "1", "--chapter-key", "v1c001"]
    )
    assert held.exit_code == 0, held.output
    approved = runner.invoke(
        app, ["approve", "--project-id", "1", "--chapter-key", "v1c001", "--yes"]
    )
    assert approved.exit_code == 0, approved.output
    assert "CANON_LOCKED" in approved.output


def test_cli_reject_enters_edit_outline_path(cli_db, tmp_path) -> None:
    runner = CliRunner()
    init = runner.invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output
    held = runner.invoke(
        app, ["write-chapter", "--project-id", "1", "--chapter-key", "v1c001"]
    )
    assert held.exit_code == 0, held.output
    rejected = runner.invoke(
        app,
        [
            "review-batch",
            "--project-id",
            "1",
            "--chapter-key",
            "v1c001",
            "--reject",
            "--yes",
        ],
    )
    assert rejected.exit_code == 0, rejected.output
    engine = build_engine(cli_db)
    with session_scope(engine) as session:
        chapter = PlanningRepo(session).get_chapter(1, "v1c001")
        assert chapter.status is ChapterStatus.NEEDS_REPLAN

    yaml_path = tmp_path / "outline.yaml"
    exported = runner.invoke(
        app,
        ["edit-outline", "v1c001", "--project-id", "1", "--out", str(yaml_path)],
    )
    assert exported.exit_code == 0, exported.output
    imported = runner.invoke(
        app,
        [
            "edit-outline",
            "v1c001",
            "--project-id",
            "1",
            "--from-file",
            str(yaml_path),
            "--yes",
        ],
    )
    assert imported.exit_code == 0, imported.output
    with session_scope(build_engine(cli_db)) as session:
        chapter = PlanningRepo(session).get_chapter(1, "v1c001")
        assert chapter.status is ChapterStatus.PLANNED
        assert chapter.outline_version >= 2


def test_cli_review_batch_non_tty_without_yes_exits_2(cli_db) -> None:
    runner = CliRunner()
    init = runner.invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output
    result = runner.invoke(app, ["review-batch", "--project-id", "1"])
    assert result.exit_code == 2, result.output


def test_cli_approve_non_tty_without_yes_exits_2(cli_db) -> None:
    runner = CliRunner()
    init = runner.invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output
    result = runner.invoke(
        app, ["approve", "--project-id", "1", "--chapter-key", "v1c001"]
    )
    assert result.exit_code == 2, result.output
