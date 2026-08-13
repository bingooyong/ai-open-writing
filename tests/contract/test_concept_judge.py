"""Stage 1 slice 3: Concept Judge PASS / REVISE / REJECT(mock,无网络)。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlmodel import Session
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
from novel_agent.domain.schemas import ConceptJudgeVerdict
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningError, PlanningGates
from novel_agent.planning.conversation import run_bible_conversation
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.runtime.agents import AgentDeps
from novel_agent.runtime.prompts import load_prompt


def _engine(tmp_path):
    engine = build_engine(tmp_path / "judge.db")
    create_all(engine)
    return engine


def _deps(session: Session, mock: MockProvider | None = None):
    mock = mock or MockProvider()
    register_planning_defaults(mock)
    return AgentDeps(
        gateway=ModelGateway(Settings(_env_file=None), session, {"mock": mock}),
        project_id=None,
    ), mock


def _verdict(decision: str, after: str = "R2", *, repair_notes: str = "") -> str:
    payload = {
        "verdict": decision,
        "after_round": after,
        "reasons": [f"mock {decision} 理由"],
        "repair_notes": repair_notes,
        "repair_attempted": False,
    }
    if decision == "REVISE" and not repair_notes:
        payload["repair_notes"] = "收紧黄金三章的当场问题,不要堆设定"
    return json.dumps(payload, ensure_ascii=False)


def test_concept_judge_prompt_and_schema() -> None:
    spec = load_prompt("concept_judge")
    assert spec.role == "concept_judge"
    assert spec.slot == "judge"
    ConceptJudgeVerdict.model_validate(
        {
            "verdict": "PASS",
            "after_round": "R2",
            "reasons": ["黄金三章有当场问题"],
        }
    )
    with pytest.raises(ValidationError):
        ConceptJudgeVerdict.model_validate(
            {"verdict": "REVISE", "after_round": "R2", "reasons": ["x"]}
        )
    with pytest.raises(ValidationError):
        ConceptJudgeVerdict.model_validate(
            {"verdict": "PASS", "after_round": "R1", "reasons": ["x"]}
        )


async def test_concept_judge_pass_allows_later_rounds(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("过关")
        session.commit()
        deps, mock = _deps(session)
        deps.project_id = project.id
        result = await run_bible_conversation(
            planning,
            BibleRepo(session),
            CanonRepo(session),
            deps,
            spark="说书人发现故事会成真",
            gates=PlanningGates.auto(),
        )
        session.commit()
        bible = BibleRepo(session)
        assert bible.round_complete(project.id) == {"R0", "R1", "R2", "R3", "R4", "R5"}
        snap = bible.concept_judge_state(project.id)
        assert snap["after_r2"]["verdict"] == "PASS"
        assert snap["after_r4"]["verdict"] == "PASS"
        assert result.chapter_keys
        assert sum(1 for role, _ in mock.calls if role == "concept_judge") >= 2


async def test_concept_judge_reject_stops_before_r3(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("拒绝")
        session.commit()
        mock = MockProvider()
        deps, mock = _deps(session, mock)
        mock.register("concept_judge", lambda _req: _verdict("REJECT"))
        deps.project_id = project.id
        with pytest.raises(PlanningError, match="REJECT"):
            await run_bible_conversation(
                planning,
                BibleRepo(session),
                CanonRepo(session),
                deps,
                spark="火花",
                gates=PlanningGates.auto(),
            )
        session.commit()
        bible = BibleRepo(session)
        done = bible.round_complete(project.id)
        assert "R2" in done
        assert "R3" not in done
        assert planning.list_characters(project.id) == []
        assert planning.list_chapters(project.id) == []
        state = bible.concept_judge_state(project.id)
        assert state["after_r2"]["verdict"] == "REJECT"
        assert state["after_r4"] is None


async def test_concept_judge_revise_repairs_once_then_continues(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("修订")
        session.commit()
        mock = MockProvider()
        deps, mock = _deps(session, mock)
        calls = {"n": 0}

        def handler(_req):
            calls["n"] += 1
            if calls["n"] == 1:
                return _verdict("REVISE")
            return _verdict("PASS")

        mock.register("concept_judge", handler)
        deps.project_id = project.id
        await run_bible_conversation(
            planning,
            BibleRepo(session),
            CanonRepo(session),
            deps,
            spark="火花",
            gates=PlanningGates.auto(),
        )
        session.commit()
        bible = BibleRepo(session)
        assert "R5" in bible.round_complete(project.id)
        r2 = bible.concept_judge_state(project.id)["after_r2"]
        assert r2["verdict"] == "PASS"
        assert r2["repair_attempted"] is True
        assert calls["n"] >= 2
        assert sum(1 for role, _ in mock.calls if role == "structure_planner") >= 2


async def test_concept_judge_revise_then_reject_stops(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("修失败")
        session.commit()
        mock = MockProvider()
        deps, mock = _deps(session, mock)
        calls = {"n": 0}

        def handler(_req):
            calls["n"] += 1
            if calls["n"] == 1:
                return _verdict("REVISE")
            return _verdict("REJECT")

        mock.register("concept_judge", handler)
        deps.project_id = project.id
        with pytest.raises(PlanningError, match="REJECT"):
            await run_bible_conversation(
                planning,
                BibleRepo(session),
                CanonRepo(session),
                deps,
                spark="火花",
                gates=PlanningGates.auto(),
            )
        session.commit()
        bible = BibleRepo(session)
        assert "R2" in bible.round_complete(project.id)
        assert "R3" not in bible.round_complete(project.id)
        assert bible.concept_judge_state(project.id)["after_r2"]["repair_attempted"] is True
        assert calls["n"] == 2


async def test_skip_concept_judge_does_not_call_model(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("跳过")
        session.commit()
        deps, mock = _deps(session)
        deps.project_id = project.id
        result = await run_bible_conversation(
            planning,
            BibleRepo(session),
            CanonRepo(session),
            deps,
            spark="火花",
            gates=PlanningGates.auto(),
            skip_concept_judge=True,
        )
        session.commit()
        assert result.chapter_keys
        assert all(role != "concept_judge" for role, _ in mock.calls)
        assert "concept_judge" in result.skipped


def test_cli_skip_concept_judge(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    try:
        result = CliRunner().invoke(
            app,
            [
                "init",
                "跳过裁判",
                "--brief",
                "说书人题材",
                "--yes",
                "--skip-concept-judge",
            ],
        )
        assert result.exit_code == 0, result.output
        engine = build_engine(db_path)
        with session_scope(engine) as session:
            bible = BibleRepo(session)
            assert bible.round_complete(1) == {"R0", "R1", "R2", "R3", "R4", "R5"}
            assert bible.concept_judge_state(1) == {"after_r2": None, "after_r4": None}
    finally:
        reset_settings_cache()
