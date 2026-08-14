"""Stage 1 slice 3: Concept Judge PASS / REVISE / REJECT(mock,无网络)。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlmodel import Session
from tests.unit.test_window_scope import yu_jin_structure
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
from novel_agent.domain.schemas import ConceptJudgeVerdict, Conflict, PayoffBeat, StoryKernel
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningError, PlanningGates
from novel_agent.planning.conversation import run_bible_conversation
from novel_agent.planning.mock_fixtures import PLANNING_KERNELS, register_planning_defaults
from novel_agent.runtime.agents import AgentDeps, run_concept_judge
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
    body = spec.render(verdict_schema="{}")
    assert "滚动窗口" in body
    assert "草图" in body
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


def _yu_jin_revise_if_unscoped(req) -> str:
    """模拟现场 MiniMax:看到绑定的 ch48/ch108 就按全书要冲突。"""
    user = req.user
    binding = ('"chapter_key": "ch48"' in user) or ('"chapter_key": "ch108"' in user)
    if binding and "# 冲突" in user:
        return _verdict(
            "REVISE",
            after="R4",
            repair_notes=(
                "冲突系统只覆盖了第1卷前3章(v1c001-v1c003),"
                "对一套跨度ch04→ch115、跨越三幕六个关键节点的全本规划而言不够。"
                "中点(ch48)、绝境(ch79)、高潮(ch108)、终局(ch115)这四把火全部没有对应冲突条目。"
            ),
        )
    after = "R4" if "# 冲突" in user else "R2"
    return _verdict("PASS", after=after)


async def test_r4_judge_payload_does_not_bind_far_chapter_keys(tmp_path) -> None:
    engine = _engine(tmp_path)
    captured: dict[str, str] = {}
    with Session(engine) as session:
        deps, mock = _deps(session)

        def handler(req):
            captured["user"] = req.user
            return _verdict("PASS", after="R4")

        mock.register("concept_judge", handler)
        kernel = StoryKernel.model_validate(PLANNING_KERNELS[0])
        conflicts = [
            Conflict.model_validate(
                dict(
                    conflict_id="cf_echo",
                    kind="identity",
                    parties=["ch_lead"],
                    stake="要不要回应广播",
                    temperature="rising",
                    must_affect="both",
                    payoff_chapter_key="v1c003",
                )
            )
        ]
        payoffs = [
            PayoffBeat.model_validate(
                dict(
                    beat_id="pb_1",
                    scale="small",
                    kind="reveal",
                    pressure_before="广播点名他",
                    hit="他听出那是自己的声音",
                    chapter_key="v1c002",
                    order_index=1,
                )
            )
        ]
        verdict = await run_concept_judge(
            deps,
            kernel=kernel,
            structure=yu_jin_structure(),
            after_round="R4",
            conflicts=conflicts,
            payoffs=payoffs,
            rolling_keys=["v1c001", "v1c002", "v1c003"],
        )
    assert verdict.verdict.value == "PASS"
    user = captured["user"]
    assert "v1c001,v1c002,v1c003" in user or "v1c001" in user
    assert '"chapter_key": "ch48"' not in user
    assert '"chapter_key": "ch108"' not in user
    assert '"chapter_key": "ch115"' not in user
    assert "sketch" in user


async def test_chapters_3_yu_jin_map_does_not_die_at_r4(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("余烬回声")
        session.commit()
        deps, mock = _deps(session)
        mock.register(
            "structure_planner",
            lambda _req: json.dumps(yu_jin_structure().model_dump(), ensure_ascii=False),
        )
        mock.register("concept_judge", _yu_jin_revise_if_unscoped)
        deps.project_id = project.id
        result = await run_bible_conversation(
            planning,
            BibleRepo(session),
            CanonRepo(session),
            deps,
            spark="末世余烬里的回声",
            gates=PlanningGates.auto(),
            chapters_needed=3,
        )
        session.commit()
        bible = BibleRepo(session)
        assert bible.round_complete(project.id) == {"R0", "R1", "R2", "R3", "R4", "R5"}
        assert bible.concept_judge_state(project.id)["after_r4"]["verdict"] == "PASS"
        assert result.chapter_keys == ["v1c001", "v1c002", "v1c003"]


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
