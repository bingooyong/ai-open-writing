"""长跑运维:run-volume 隔夜批次(plan-more + 写章 + 预算/人工门禁)。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from typer.testing import CliRunner

from novel_agent.api.app import create_app
from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.repos import BibleRepo, CanonRepo, OpsRepo, PlanningRepo
from novel_agent.domain.schemas import ChapterStatus
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningGates
from novel_agent.planning.conversation import run_bible_conversation
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.planning.volume import plan_more
from novel_agent.production.loop import ChapterLoopResult
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults
from novel_agent.production.volume_run import (
    KIND,
    VolumeStopReason,
    _occupy,
    request_volume_stop,
    run_volume,
)
from novel_agent.runtime.agents import AgentDeps
from novel_agent.workflow import WorkflowPaused


def _engine(tmp_path):
    engine = build_engine(tmp_path / "volume-run.db")
    create_all(engine)
    return engine


async def _bibled(tmp_path):
    engine = _engine(tmp_path)
    session = Session(engine)
    planning = PlanningRepo(session)
    bible = BibleRepo(session)
    canon = CanonRepo(session)
    project = planning.create_project("说书人传奇", genre="奇幻", boundaries=["禁无代价全能"])
    session.commit()
    mock = MockProvider()
    register_planning_defaults(mock)
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
    return session, deps, planning, project.id


def _loop_result(
    project_id: int, chapter_key: str, status: ChapterStatus
) -> ChapterLoopResult:
    stopped = "n9_canon_commit" if status is ChapterStatus.CANON_LOCKED else "n6_judge"
    return ChapterLoopResult(
        project_id=project_id,
        chapter_key=chapter_key,
        status=status,
        verdict=None,
        revision_round=0,
        workflow_run_id=0,
        draft_id=None,
        lineage_id="stub",
        stopped_at=stopped,
        reason="stub",
    )


def _patch_loop(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[str]:
    written: list[str] = []

    async def stub(session: Session, deps: Any, project_id: int, chapter_key: str, **kwargs: Any):
        written.append(chapter_key)
        return await handler(session, project_id, chapter_key)

    monkeypatch.setattr("novel_agent.production.volume_run.run_chapter_loop", stub)
    return written


async def test_run_volume_calls_plan_more_and_exceeds_five_chapters(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)
    plan_calls = {"n": 0}

    async def counting_plan(*args: Any, **kwargs: Any):
        plan_calls["n"] += 1
        return await plan_more(*args, **kwargs)

    monkeypatch.setattr("novel_agent.production.volume_run.plan_more", counting_plan)

    async def cheap(session: Session, project_id: int, chapter_key: str):
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    _patch_loop(monkeypatch, cheap)
    try:
        result = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=8
        )
        session.commit()
        assert result.stop_reason == VolumeStopReason.MAX_CHAPTERS.value
        assert result.chapters_done == 8
        keys = [chapter.chapter_key for chapter in planning.list_chapters(pid)]
        assert len(keys) > 5
        assert "v1c006" in keys
        assert plan_calls["n"] >= 1
        locked = [
            chapter.chapter_key
            for chapter in planning.list_chapters(pid)
            if chapter.status is ChapterStatus.CANON_LOCKED
        ]
        assert locked[:8] == [f"v1c{i:03d}" for i in range(1, 9)]
    finally:
        session.close()


async def test_second_run_volume_skips_canon_locked(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)

    async def cheap(session: Session, project_id: int, chapter_key: str):
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    written = _patch_loop(monkeypatch, cheap)
    try:
        first = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=2
        )
        session.commit()
        assert first.chapter_keys == ["v1c001", "v1c002"]
        assert written == ["v1c001", "v1c002"]

        second = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=2
        )
        session.commit()
        assert second.chapter_keys == ["v1c003", "v1c004"]
        assert written == ["v1c001", "v1c002", "v1c003", "v1c004"]
        assert planning.get_chapter(pid, "v1c001").status is ChapterStatus.CANON_LOCKED
        assert planning.get_chapter(pid, "v1c002").status is ChapterStatus.CANON_LOCKED
    finally:
        session.close()


async def test_needs_replan_does_not_stop_volume_by_default(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)

    async def replan_first(session: Session, project_id: int, chapter_key: str):
        if chapter_key == "v1c001":
            PlanningRepo(session).set_status(
                project_id, chapter_key, ChapterStatus.NEEDS_REPLAN
            )
            session.commit()
            return _loop_result(project_id, chapter_key, ChapterStatus.NEEDS_REPLAN)
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    written = _patch_loop(monkeypatch, replan_first)
    try:
        result = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=2
        )
        session.commit()
        assert result.stop_reason == VolumeStopReason.MAX_CHAPTERS.value
        assert written == ["v1c001", "v1c002", "v1c003"]
        assert result.chapter_keys == ["v1c002", "v1c003"]
        assert planning.get_chapter(pid, "v1c001").status is ChapterStatus.NEEDS_REPLAN
        assert planning.get_chapter(pid, "v1c002").status is ChapterStatus.CANON_LOCKED
        assert planning.get_chapter(pid, "v1c003").status is ChapterStatus.CANON_LOCKED
        assert planning.get_chapter(pid, "v1c004").status is ChapterStatus.PLANNED
    finally:
        session.close()


async def test_volume_stop_on_replan_when_keep_going_off(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)

    async def replan_first(session: Session, project_id: int, chapter_key: str):
        PlanningRepo(session).set_status(
            project_id, chapter_key, ChapterStatus.NEEDS_REPLAN
        )
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.NEEDS_REPLAN)

    written = _patch_loop(monkeypatch, replan_first)
    try:
        result = await run_volume(
            session,
            deps,
            pid,
            budget_usd=1.0,
            yes=True,
            max_chapters=5,
            keep_going=False,
        )
        session.commit()
        assert result.stop_reason == VolumeStopReason.NEEDS_REPLAN.value
        assert written == ["v1c001"]
        assert planning.get_chapter(pid, "v1c001").status is ChapterStatus.NEEDS_REPLAN
        assert planning.get_chapter(pid, "v1c002").status is ChapterStatus.PLANNED
    finally:
        session.close()


async def test_volume_skips_already_parked_replan_chapter(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)
    planning.set_status(pid, "v1c001", ChapterStatus.NEEDS_REPLAN)
    session.commit()

    async def cheap(session: Session, project_id: int, chapter_key: str):
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    written = _patch_loop(monkeypatch, cheap)
    try:
        result = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=2
        )
        session.commit()
        assert written == ["v1c002", "v1c003"]
        assert result.chapter_keys == ["v1c002", "v1c003"]
        assert planning.get_chapter(pid, "v1c001").status is ChapterStatus.NEEDS_REPLAN
    finally:
        session.close()


async def test_human_review_stops_without_writing_later_chapters(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)

    async def maybe_review(session: Session, project_id: int, chapter_key: str):
        if chapter_key == "v1c002":
            PlanningRepo(session).set_status(
                project_id, chapter_key, ChapterStatus.HUMAN_REVIEW
            )
            session.commit()
            return _loop_result(project_id, chapter_key, ChapterStatus.HUMAN_REVIEW)
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    written = _patch_loop(monkeypatch, maybe_review)
    try:
        result = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=5
        )
        session.commit()
        assert result.stop_reason == VolumeStopReason.HUMAN_REVIEW.value
        assert written == ["v1c001", "v1c002"]
        assert planning.get_chapter(pid, "v1c001").status is ChapterStatus.CANON_LOCKED
        assert planning.get_chapter(pid, "v1c002").status is ChapterStatus.HUMAN_REVIEW
        assert planning.get_chapter(pid, "v1c003").status is ChapterStatus.PLANNED
        assert planning.get_chapter(pid, "v1c004").status is ChapterStatus.PLANNED
        assert planning.get_chapter(pid, "v1c005").status is ChapterStatus.PLANNED
    finally:
        session.close()


async def test_budget_stop_does_not_write_later_chapters(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)

    async def blow_budget(session: Session, project_id: int, chapter_key: str):
        raise WorkflowPaused("章 v1c001 模型调用 40 次,已达上限 1,工作流暂停")

    written = _patch_loop(monkeypatch, blow_budget)
    try:
        result = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=5
        )
        session.commit()
        assert result.stop_reason == VolumeStopReason.BUDGET.value
        assert written == ["v1c001"]
        assert planning.get_chapter(pid, "v1c001").status is ChapterStatus.PLANNED
        assert planning.get_chapter(pid, "v1c002").status is ChapterStatus.PLANNED
    finally:
        session.close()


async def test_usd_budget_stop_before_later_chapters(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)
    ops = deps.gateway.ops

    async def lock_and_spend(session: Session, project_id: int, chapter_key: str):
        ops.record_model_run(
            project_id=project_id,
            chapter_key=chapter_key,
            agent_role="writer_a",
            provider="mock",
            model="mock-model",
            prompt_version="t",
            cost_estimate=1.5,
        )
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    written = _patch_loop(monkeypatch, lock_and_spend)
    try:
        result = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=5
        )
        session.commit()
        assert result.stop_reason == VolumeStopReason.BUDGET.value
        assert written == ["v1c001"]
        assert planning.get_chapter(pid, "v1c002").status is ChapterStatus.PLANNED
        assert result.spent_usd >= 1.0
    finally:
        session.close()


def test_cli_run_volume_requires_positive_budget(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    runner = CliRunner()
    try:
        missing = runner.invoke(app, ["run-volume", "--project-id", "1", "--yes"])
        assert missing.exit_code == 2
        assert "budget-usd" in missing.output
        zero = runner.invoke(
            app, ["run-volume", "--project-id", "1", "--yes", "--budget-usd", "0"]
        )
        assert zero.exit_code == 2
    finally:
        reset_settings_cache()


def test_cli_and_api_run_volume(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def cheap(session: Session, project_id: int, chapter_key: str):
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    _patch_loop(monkeypatch, cheap)
    db_path = tmp_path / "desk.db"
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
        ran = runner.invoke(
            app,
            [
                "run-volume",
                "--project-id",
                "1",
                "--yes",
                "--budget-usd",
                "1",
                "--max-chapters",
                "2",
            ],
        )
        assert ran.exit_code == 0, ran.output
        assert "stop_reason=MAX_CHAPTERS" in ran.output
        assert "chapters_done=2" in ran.output
    finally:
        reset_settings_cache()

    engine = build_engine(tmp_path / "api.db")
    create_all(engine)
    settings = Settings(_env_file=None, db_path=tmp_path / "api.db")
    with TestClient(create_app(settings=settings, engine=engine)) as client:
        created = client.post(
            "/projects",
            json={
                "title": "长跑",
                "spark": "说书人发现故事会成真",
                "auto_bible": True,
                "skip_concept_judge": True,
            },
        )
        assert created.status_code == 200, created.text
        pid = created.json()["id"]
        idle = client.get(f"/projects/{pid}/run-volume")
        assert idle.status_code == 200
        assert idle.json()["status"] == "idle"
        assert idle.json()["current_chapter"] == ""
        assert idle.json()["cancel_requested"] is False
        assert idle.json()["max_chapters"] is None
        bad = client.post(f"/projects/{pid}/run-volume", json={"budget_usd": 0, "yes": True})
        assert bad.status_code == 400
        started = client.post(
            f"/projects/{pid}/run-volume",
            json={"budget_usd": 1, "max_chapters": 2, "yes": True},
        )
        assert started.status_code == 200, started.text
        status = client.get(f"/projects/{pid}/run-volume")
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["stop_reason"] == "MAX_CHAPTERS"
        assert body["chapters_done"] == 2
        assert body["chapter_keys"] == ["v1c001", "v1c002"]
        assert body["budget_usd"] == 1.0
        assert body["max_chapters"] == 2
        assert body["cancel_requested"] is False
        assert "current_chapter" in body
        assert "spent_usd" in body


async def test_cooperative_stop_skips_later_chapters(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, deps, planning, pid = await _bibled(tmp_path)

    async def lock_then_stop(session: Session, project_id: int, chapter_key: str):
        request_volume_stop(project_id)
        PlanningRepo(session).set_status(project_id, chapter_key, ChapterStatus.CANON_LOCKED)
        session.commit()
        return _loop_result(project_id, chapter_key, ChapterStatus.CANON_LOCKED)

    written = _patch_loop(monkeypatch, lock_then_stop)
    try:
        result = await run_volume(
            session, deps, pid, budget_usd=1.0, yes=True, max_chapters=5
        )
        session.commit()
        assert result.stop_reason == VolumeStopReason.CANCELLED.value
        assert result.status == "cancelled"
        assert written == ["v1c001"]
        assert planning.get_chapter(pid, "v1c002").status is ChapterStatus.PLANNED
    finally:
        session.close()


def test_get_run_volume_exposes_console_fields(tmp_path) -> None:
    engine = build_engine(tmp_path / "console.db")
    create_all(engine)
    settings = Settings(_env_file=None, db_path=tmp_path / "console.db")
    with Session(engine) as session:
        project = PlanningRepo(session).create_project("控制台", genre="奇幻")
        session.commit()
        pid = project.id
        assert pid is not None
        ops = OpsRepo(session)
        run = ops.create_workflow_run(pid, KIND)
        assert run.id is not None
        ops.update_workflow(
            run.id,
            status="running",
            current_node="v1c003",
            budget_spent={
                "budget_usd": 1.0,
                "spent_usd": 0.25,
                "chapters_done": 2,
                "chapter_keys": ["v1c001", "v1c002"],
                "stop_reason": "",
                "current_chapter": "v1c003",
                "max_chapters": 8,
                "cancel_requested": False,
            },
        )
        session.commit()

    with TestClient(create_app(settings=settings, engine=engine)) as client:
        body = client.get(f"/projects/{pid}/run-volume").json()
        assert body["status"] == "running"
        assert body["current_chapter"] == "v1c003"
        assert body["chapters_done"] == 2
        assert body["chapter_keys"] == ["v1c001", "v1c002"]
        assert body["spent_usd"] == 0.25
        assert body["budget_usd"] == 1.0
        assert body["max_chapters"] == 8
        assert body["stop_reason"] == ""
        assert body["cancel_requested"] is False


def test_api_stop_run_volume(tmp_path) -> None:
    engine = build_engine(tmp_path / "stop.db")
    create_all(engine)
    settings = Settings(_env_file=None, db_path=tmp_path / "stop.db")
    with Session(engine) as session:
        project = PlanningRepo(session).create_project("停跑", genre="奇幻")
        session.commit()
        pid = project.id
        assert pid is not None
        ops = OpsRepo(session)
        run = ops.create_workflow_run(pid, KIND)
        assert run.id is not None
        ops.update_workflow(
            run.id,
            status="running",
            current_node="v1c001",
            budget_spent={
                "budget_usd": 1.0,
                "spent_usd": 0.0,
                "chapters_done": 0,
                "chapter_keys": [],
                "stop_reason": "",
                "current_chapter": "v1c001",
                "max_chapters": 8,
                "cancel_requested": False,
            },
        )
        session.commit()

    with TestClient(create_app(settings=settings, engine=engine)) as client:
        missing = client.post("/projects/99/run-volume/stop")
        assert missing.status_code == 404
        idle_stop = client.post(f"/projects/{pid}/run-volume/stop")
        assert idle_stop.status_code == 409
        release = _occupy(pid)
        try:
            stopped = client.post(f"/projects/{pid}/run-volume/stop")
            assert stopped.status_code == 200, stopped.text
            body = stopped.json()
            assert body["cancel_requested"] is True
            assert body["current_chapter"] == "v1c001"
            polled = client.get(f"/projects/{pid}/run-volume")
            assert polled.json()["cancel_requested"] is True
        finally:
            release()


def test_human_review_status_exposes_gate_chapter(tmp_path) -> None:
    engine = build_engine(tmp_path / "gate.db")
    create_all(engine)
    settings = Settings(_env_file=None, db_path=tmp_path / "gate.db")
    with Session(engine) as session:
        project = PlanningRepo(session).create_project("人门", genre="奇幻")
        session.commit()
        pid = project.id
        assert pid is not None
        ops = OpsRepo(session)
        run = ops.create_workflow_run(pid, KIND)
        assert run.id is not None
        ops.update_workflow(
            run.id,
            status="paused",
            current_node="v1c002",
            budget_spent={
                "budget_usd": 1.0,
                "spent_usd": 0.0,
                "chapters_done": 1,
                "chapter_keys": ["v1c001"],
                "stop_reason": "HUMAN_REVIEW",
                "current_chapter": "v1c002",
                "max_chapters": 8,
                "cancel_requested": False,
            },
        )
        session.commit()

    with TestClient(create_app(settings=settings, engine=engine)) as client:
        body = client.get(f"/projects/{pid}/run-volume").json()
        assert body["status"] == "paused"
        assert body["stop_reason"] == "HUMAN_REVIEW"
        assert body["current_chapter"] == "v1c002"
        assert body["chapters_done"] == 1
