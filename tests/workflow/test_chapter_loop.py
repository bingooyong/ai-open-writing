"""M3.3 单章循环集成: mock 下 N1→N9 四条路径(Spec §6 / Plan DoD)。"""

from __future__ import annotations

import json

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
from novel_agent.production.mock_fixtures import (
    LOCATABLE_QUOTE,
    SCENE_1,
    SCENE_1_REVISED,
    SCENE_2,
    register_chapter_loop_defaults,
    two_part_text,
    verdict_json,
)
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "chapter.db")
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


def _reviewer_roles(mock: MockProvider) -> set[str]:
    return {role for role, _req in mock.calls if role in {
        "red_team", "plot", "character", "continuity", "prose", "reader_advocate",
    }}


def _node_names(session: Session, workflow_run_id: int) -> list[str]:
    return [rec.node_name for rec in OpsRepo(session).node_history(workflow_run_id)]


async def test_pass_path_drives_n1_to_n9_and_locks_canon(tmp_path) -> None:
    session, deps, mock, project_id = await _planned(tmp_path)
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()

        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        assert result.revision_round == 0
        names = _node_names(session, result.workflow_run_id)
        for required in (
            "n1_validate_outline",
            "n2_build_context",
            "n3_draft",
            "n4_lint",
            "n5_parallel_review",
            "n6_judge",
            "n8_human_gate",
            "n9_canon_commit",
        ):
            assert required in names, names
        assert _reviewer_roles(mock) == {
            "red_team", "plot", "character", "continuity", "prose", "reader_advocate",
        }
        assert any(role == "judge" for role, _req in mock.calls)

        prod = ProductionRepo(session)
        issues = prod.list_issues(result.draft_id)
        assert any(issue.downweighted for issue in issues)
        downweighted_ids = {issue.issue_id for issue in issues if issue.downweighted}
        verdict = prod.latest_verdict("v1c001")
        assert verdict is not None
        assert verdict.verdict is VerdictType.PASS
        assert not verdict.hard_gate_failures
        assert all(
            not ruling.accepted or ruling.issue_id not in downweighted_ids
            for ruling in verdict.rulings
        )
        judge_users = [req.user for role, req in mock.calls if role == "judge"]
        assert judge_users
        assert "downweighted" in judge_users[-1]

        chapter = PlanningRepo(session).get_chapter(project_id, "v1c001")
        assert chapter.status is ChapterStatus.CANON_LOCKED
        assert OpsRepo(session).has_approval(project_id, "chapter", "v1c001")
        assert CanonRepo(session).committed_count(project_id) >= 1
    finally:
        session.close()


async def test_revise_local_two_round_path_then_pass(tmp_path) -> None:
    mock = MockProvider()
    judge_calls = {"n": 0}

    def judge_handler(_req):
        judge_calls["n"] += 1
        if judge_calls["n"] <= 2:
            return verdict_json(
                "REVISE_LOCAL",
                accepted_issue="continuity_1",
                revision_scope=["v1c001_s1"],
                hard_gates=["canon_conflict"],
            )
        return verdict_json("PASS")

    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register("judge", judge_handler)
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()

        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        # n7 之后只剩一稿; §5.4 sole n=1 在第二次 REVISE_LOCAL 时锁定,不再走第二轮修订。
        assert result.revision_round == 1
        assert judge_calls["n"] == 2
        assert sum(1 for role, _req in mock.calls if role == "reviser") == 1
        names = _node_names(session, result.workflow_run_id)
        assert names.count("n7_revise") == 1
        assert names.count("n6_judge") == 2
        assert PlanningRepo(session).get_chapter(project_id, "v1c001").revision_round == 1
    finally:
        session.close()


async def test_replan_path_stops_at_needs_replan(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register(
        "judge",
        lambda _req: verdict_json(
            "REPLAN_CHAPTER",
            accepted_issue="continuity_1",
            rollback_target="chapter_outline",
        ),
    )
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()

        assert result.status is ChapterStatus.NEEDS_REPLAN
        assert result.verdict is VerdictType.REPLAN_CHAPTER
        assert result.revision_round == 0
        assert all(role != "reviser" for role, _req in mock.calls)
        names = _node_names(session, result.workflow_run_id)
        assert "n7_revise" not in names
        assert "n9_canon_commit" not in names
        assert PlanningRepo(session).get_chapter(project_id, "v1c001").status is (
            ChapterStatus.NEEDS_REPLAN
        )
        assert CanonRepo(session).committed_count(project_id) == 0
    finally:
        session.close()


async def test_replan_poisoned_by_leaky_sibling_locks_sole_clean_draft(tmp_path) -> None:
    """v1c008: Judge 因 A 跑题+泄漏 REPLAN,B 干净则继续锁定,不停车 NEEDS_REPLAN。"""
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register(
        "writer_a",
        lambda req: two_part_text(
            req,
            SCENE_1 + "产房门口她忽然穿越，耳鸣炸开，实习生把笔记递上来，真名差点出口。",
            SCENE_2,
            "跑题",
        ),
    )
    mock.register(
        "judge",
        lambda _req: verdict_json(
            "REPLAN_CHAPTER",
            accepted_issue="continuity_1",
            rollback_target="chapter_outline",
        ),
    )
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        n3 = OpsRepo(session).find_success_node("v1c001|1|1|n3")
        assert n3 is not None
        assert len(n3.output_snapshot.get("draft_ids") or []) == 2
        locked = ProductionRepo(session).get_draft(result.draft_id)
        assert "穿越" not in locked.content_text
        assert "耳鸣" not in locked.content_text
        names = _node_names(session, result.workflow_run_id)
        assert "n9_canon_commit" in names
        assert PlanningRepo(session).get_chapter(project_id, "v1c001").status is (
            ChapterStatus.CANON_LOCKED
        )
    finally:
        session.close()


async def test_replan_stands_when_both_candidates_are_leaky(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    leak = "天台锁一响，她穿越后耳鸣没停，实习生还在问真名。"
    mock.register(
        "writer_a",
        lambda req: two_part_text(req, SCENE_1 + leak, SCENE_2, "泄漏A"),
    )
    mock.register(
        "writer_b",
        lambda req: two_part_text(req, SCENE_1 + leak, SCENE_2, "泄漏B"),
    )
    mock.register(
        "judge",
        lambda _req: verdict_json(
            "REPLAN_CHAPTER",
            accepted_issue="continuity_1",
            rollback_target="chapter_outline",
        ),
    )
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()
        assert result.status is ChapterStatus.NEEDS_REPLAN
        assert result.verdict is VerdictType.REPLAN_CHAPTER
        assert "n9_canon_commit" not in _node_names(session, result.workflow_run_id)
    finally:
        session.close()


async def test_empty_judge_packet_retries_then_locks_longer_candidate(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register(
        "judge",
        lambda _req: json.dumps(
            {
                "verdict": "HUMAN_REVIEW",
                "selected_candidate": "candidate_1",
                "reasoning_summary": "用户未提供评审材料，强制 HUMAN_REVIEW",
            },
            ensure_ascii=False,
        ),
    )
    try:
        result = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        assert sum(1 for role, _req in mock.calls if role == "judge") == 2
        run = OpsRepo(session).get_workflow_run(result.workflow_run_id)
        assert run.status == "succeeded"
    finally:
        session.close()


async def test_short_writer_b_is_dropped_before_judge(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register(
        "writer_b",
        lambda req: two_part_text(req, "（正文）", "（正文）", "空稿"),
    )
    try:
        result = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        n3 = OpsRepo(session).find_success_node("v1c001|1|1|n3")
        assert n3 is not None
        assert len(n3.output_snapshot.get("draft_ids") or []) == 1
    finally:
        session.close()


async def test_chinese_revision_scope_does_not_block_lint(tmp_path) -> None:
    mock = MockProvider()
    judge_calls = {"n": 0}

    def judge_handler(_req):
        judge_calls["n"] += 1
        if judge_calls["n"] == 1:
            return verdict_json(
                "REVISE_LOCAL",
                accepted_issue="continuity_1",
                revision_scope=["只修开场对白，收紧因果"],
                hard_gates=["canon_conflict"],
            )
        return verdict_json("PASS")

    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register("judge", judge_handler)
    try:
        result = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        assert judge_calls["n"] == 2
        assert sum(1 for role, _req in mock.calls if role == "reviser") == 1
    finally:
        session.close()


async def test_n7_xxx_placeholder_does_not_leave_running(tmp_path) -> None:
    mock = MockProvider()
    judge_calls = {"n": 0}

    def judge_handler(_req):
        judge_calls["n"] += 1
        if judge_calls["n"] == 1:
            return verdict_json(
                "REVISE_LOCAL",
                accepted_issue="continuity_1",
                revision_scope=["v1c001_s1"],
                hard_gates=["canon_conflict"],
            )
        return verdict_json("PASS")

    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register("judge", judge_handler)
    mock.register(
        "reviser",
        lambda req: two_part_text(req, SCENE_1_REVISED, SCENE_2, "评书成真").replace(
            "v1c001_s1", "xxx", 1
        ).replace("v1c001_s2", "xxx", 1),
    )
    try:
        result = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        run = OpsRepo(session).get_workflow_run(result.workflow_run_id)
        assert run.status != "running"
    finally:
        session.close()


async def test_failed_workflow_is_not_resumed(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register(
        "writer_a",
        lambda req: two_part_text(
            req,
            SCENE_1 + '{"issue_id": "prompt_leak"}',
            SCENE_2,
            "泄漏",
        ),
    )
    mock.register(
        "writer_b",
        lambda req: two_part_text(
            req,
            SCENE_1 + '{"issue_id": "prompt_leak"}',
            SCENE_2,
            "泄漏",
        ),
    )
    try:
        first = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert first.status is ChapterStatus.HUMAN_REVIEW
        assert first.stopped_at == "n4_lint"
        run = OpsRepo(session).get_workflow_run(first.workflow_run_id)
        assert run.status == "failed"
        assert OpsRepo(session).find_resumable_run(project_id, "chapter_loop", "v1c001") is None

        mock.register("writer_a", lambda req: two_part_text(req, SCENE_1, SCENE_2, "干净"))
        mock.register("writer_b", lambda req: two_part_text(req, SCENE_1, SCENE_2, "干净"))
        second = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert second.workflow_run_id != first.workflow_run_id
        assert second.status is ChapterStatus.CANON_LOCKED
    finally:
        session.close()


async def test_two_round_hard_gate_failure_upgrades_to_human_review(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register(
        "judge",
        lambda _req: verdict_json(
            "REVISE_LOCAL",
            accepted_issue="continuity_1",
            revision_scope=["v1c001_s1"],
            hard_gates=["canon_conflict"],
        ),
    )
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()

        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        # 首轮 REVISE_LOCAL 后 n7 只留一稿; §5.4 单可锁候选直接锁定,不再二次修订后升 HUMAN_REVIEW。
        assert result.revision_round == 1
        assert sum(1 for role, _req in mock.calls if role == "reviser") == 1
        names = _node_names(session, result.workflow_run_id)
        assert names.count("n7_revise") == 1
        assert "n9_canon_commit" in names
        assert PlanningRepo(session).get_chapter(project_id, "v1c001").status is (
            ChapterStatus.CANON_LOCKED
        )
        assert OpsRepo(session).has_approval(project_id, "chapter", "v1c001")
    finally:
        session.close()


async def test_n5_continuity_parse_fail_does_not_stick_adversarial_review(tmp_path) -> None:
    """Overnight v1c015: Continuity ReviewReport 校验失败不得卡死 ADVERSARIAL_REVIEW。"""
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register("continuity", lambda _req: "{")
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()
        chapter = PlanningRepo(session).get_chapter(project_id, "v1c001")
        assert chapter.status is not ChapterStatus.ADVERSARIAL_REVIEW
        assert result.status is not ChapterStatus.ADVERSARIAL_REVIEW
        assert result.status in {
            ChapterStatus.HUMAN_REVIEW,
            ChapterStatus.JUDGING,
            ChapterStatus.CANON_LOCKED,
        }
        names = _node_names(session, result.workflow_run_id)
        assert "n5_parallel_review" in names
        run = OpsRepo(session).get_workflow_run(result.workflow_run_id)
        assert run.status != "failed"
    finally:
        session.close()


async def test_n5_all_reviewers_parse_fail_upgrades_to_human_review(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    for role in ("red_team", "plot", "character", "continuity", "prose", "reader_advocate"):
        mock.register(role, lambda _req: "{")
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()
        chapter = PlanningRepo(session).get_chapter(project_id, "v1c001")
        assert chapter.status is ChapterStatus.HUMAN_REVIEW
        assert result.status is ChapterStatus.HUMAN_REVIEW
        assert result.stopped_at == "n5_parallel_review"
        assert "ReviewReport" in result.reason
        names = _node_names(session, result.workflow_run_id)
        assert "n5_parallel_review" in names
        run = OpsRepo(session).get_workflow_run(result.workflow_run_id)
        assert run.status == "paused"
        assert run.current_node == "n5_parallel_review"
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


def test_cli_write_chapter_yes_completes_pass_path(cli_db) -> None:
    init = CliRunner().invoke(
        app,
        ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"],
    )
    assert init.exit_code == 0, init.output

    result = CliRunner().invoke(
        app,
        ["write-chapter", "--project-id", "1", "--chapter-key", "v1c001", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert "CANON_LOCKED" in result.output

    engine = build_engine(cli_db)
    with session_scope(engine) as session:
        chapter = PlanningRepo(session).get_chapter(1, "v1c001")
        assert chapter.status is ChapterStatus.CANON_LOCKED


def test_smoke_chapter_refuses_without_explicit_confirm(cli_db) -> None:
    result = CliRunner().invoke(app, ["smoke-chapter"])
    assert result.exit_code == 2, result.output
    assert "--confirm-real-models" in result.output


def test_mock_chapter_fixtures_are_valid_payloads() -> None:
    payload = json.loads(verdict_json("PASS"))
    assert payload["verdict"] == "PASS"
    assert LOCATABLE_QUOTE
