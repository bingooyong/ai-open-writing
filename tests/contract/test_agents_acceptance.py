"""G001 acceptance contracts missing from the initial M2.4/M2.6 tests."""

import asyncio
import json
from pathlib import Path

import pytest
from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

from novel_agent.domain.schemas import (
    ChapterContextPackage,
    DraftCandidate,
    ReviewerRole,
    ReviewReport,
)
from novel_agent.gateway.base import ModelRequest, ModelResponse
from novel_agent.gateway.structured import (
    StructuredOutputError,
    TwoPartParseError,
    parse_two_part,
)
from novel_agent.runtime import agents
from novel_agent.runtime.agents import (
    AgentDeps,
    run_canon_curator,
    run_character_planner,
    run_judge,
    run_outline_planner,
    run_review_round,
)
from novel_agent.runtime.blinding import BlindingLeak
from novel_agent.runtime.prompts import load_prompt


def _ctx() -> ChapterContextPackage:
    return ChapterContextPackage.model_validate(
        {
            "chapter_key": "v1c001",
            "canon_version": "canon_v0",
            "task_brief": "写第一章",
            "outline": OUTLINE,
            "scene_cards": [SCENE],
            "kernel_summary": "说书人故事成真",
            "volume_summary": "第一卷",
            "unit_card": UNIT,
            "characters": [CHARACTER],
        }
    )


def _draft(content: str = "茶楼里灯火通明。") -> DraftCandidate:
    return DraftCandidate.model_validate(
        {
            "candidate_id": "candidate_1",
            "chapter_key": "v1c001",
            "scenes": [{"scene_id": "v1c001_s1", "content": content}],
            "chapter_summary": "开场",
        }
    )


class StubGateway:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, ModelRequest]] = []

    async def call(
        self,
        slot_name: str,
        req: ModelRequest,
        *,
        agent_role: str,
        prompt_version: str,
        **_: object,
    ) -> ModelResponse:
        self.calls.append((slot_name, agent_role, req))
        return ModelResponse(text=self.responses[agent_role], provider="stub", model="stub")


def _write_prompt(directory: Path, role: str, slot: str, body: str = "prompt") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{role}.md").write_text(
        (
            f"---\nversion: 1\nrole: {role}\nslot: {slot}\n"
            "input_schema: TestInput\noutput_schema: TestOutput\n"
            f"---\n{body}\n"
        ),
        encoding="utf-8",
    )


def test_prompt_loader_rejects_unknown_model_slot(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "writer", "shell")

    with pytest.raises(ValueError, match="slot"):
        load_prompt("writer", tmp_path)


def test_prompt_render_rejects_missing_contract_variable(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "writer", "creative", "Schema: ${format_instructions}")
    spec = load_prompt("writer", tmp_path)

    with pytest.raises((KeyError, ValueError), match="format_instructions"):
        spec.render()


def test_two_part_parser_keeps_last_nonempty_duplicate_scene_block() -> None:
    output = """<<<SCENE:s1>>>
第一版。
<<<END>>>
<<<SCENE:s1>>>
第二版。
<<<END>>>
<<<META>>>
{"chapter_summary": "摘要", "deviation_notes": ""}"""

    scenes, _ = parse_two_part(output, ["s1"])
    assert scenes["s1"] == "第二版。"


def test_two_part_parser_rejects_non_object_metadata() -> None:
    output = """<<<SCENE:s1>>>
正文。
<<<END>>>
<<<META>>>
[]"""

    with pytest.raises(TwoPartParseError, match="META.*对象"):
        parse_two_part(output, ["s1"])


async def test_review_round_starts_all_five_reviewers_concurrently(monkeypatch) -> None:
    started: set[ReviewerRole] = set()
    all_started = asyncio.Event()

    async def reviewer(_deps, role, draft, ctx):
        started.add(role)
        if len(started) == 5:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=0.5)
        return ReviewReport(
            reviewer_role=role,
            candidate_id=draft.candidate_id,
            issues=[],
        )

    monkeypatch.setattr(agents, "run_reviewer", reviewer)
    result = await run_review_round(object(), _draft(), _ctx())  # type: ignore[arg-type]

    assert len(result.reports) == 5


@pytest.mark.parametrize("critical_role", [ReviewerRole.CONTINUITY, ReviewerRole.RED_TEAM])
async def test_review_round_fails_when_each_critical_reviewer_is_absent(
    monkeypatch, critical_role: ReviewerRole
) -> None:
    async def reviewer(_deps, role, draft, ctx):
        if role == critical_role:
            raise RuntimeError("offline")
        return ReviewReport(
            reviewer_role=role,
            candidate_id=draft.candidate_id,
            issues=[],
        )

    monkeypatch.setattr(agents, "run_reviewer", reviewer)

    with pytest.raises(RuntimeError, match=critical_role.value):
        await run_review_round(object(), _draft(), _ctx())  # type: ignore[arg-type]


async def test_judge_leak_blocks_before_gateway_call() -> None:
    gateway = StubGateway({"judge": "{}"})
    deps = AgentDeps(gateway=gateway)  # type: ignore[arg-type]

    with pytest.raises(BlindingLeak):
        await run_judge(deps, [_draft("正文泄漏 writer_a 身份")], [], _ctx())

    assert gateway.calls == []


async def test_judge_receives_explicit_absent_reviewer_list() -> None:
    verdict = json.dumps(
        {
            "verdict": "PASS",
            "selected_candidate": "candidate_1",
            "reasoning_summary": "无硬门禁失败",
        },
        ensure_ascii=False,
    )
    gateway = StubGateway({"judge": verdict})
    deps = AgentDeps(gateway=gateway)  # type: ignore[arg-type]

    await run_judge(deps, [_draft()], [], _ctx(), absent=["prose"])

    user = gateway.calls[0][2].user
    assert "# 缺席评审\n1 席" in user
    assert "prose" not in user


async def test_judge_absent_advocate_does_not_leak_identity() -> None:
    verdict = json.dumps(
        {
            "verdict": "PASS",
            "selected_candidate": "candidate_1",
            "reasoning_summary": "无硬门禁失败",
        },
        ensure_ascii=False,
    )
    gateway = StubGateway({"judge": verdict})
    deps = AgentDeps(gateway=gateway)  # type: ignore[arg-type]

    await run_judge(deps, [_draft()], [], _ctx(), absent=["reader_advocate"])

    user = gateway.calls[0][2].user
    assert "# 缺席评审\n1 席" in user
    for token in ("reader_advocate", "red_team", "writer_a", "writer_b"):
        assert token not in user


async def test_canon_curator_routes_through_prompt_declared_slot(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "canon_curator", "creative", "${delta_schema}")
    delta = json.dumps(
        {"chapter_key": "v1c001", "base_canon_version": "canon_v0"},
        ensure_ascii=False,
    )
    gateway = StubGateway({"canon_curator": delta})
    deps = AgentDeps(gateway=gateway, prompts_dir=tmp_path)  # type: ignore[arg-type]

    await run_canon_curator(deps, _draft(), _ctx(), "canon_v0")

    assert gateway.calls[0][0] == "creative"


async def test_character_planner_validates_its_declared_output_schema() -> None:
    response = json.dumps({"characters": [CHARACTER]}, ensure_ascii=False)
    gateway = StubGateway({"character_planner": response})
    deps = AgentDeps(gateway=gateway)  # type: ignore[arg-type]

    characters = await run_character_planner(deps, json.dumps(KERNEL), "创作简报")

    assert characters[0].character_id == CHARACTER["character_id"]


async def test_outline_planner_rejects_scene_for_unrequested_chapter() -> None:
    response = json.dumps(
        {
            "unit": UNIT,
            "outlines": [OUTLINE],
            "scene_cards": [
                {**SCENE, "scene_id": "v1c999_s1", "chapter_key": "v1c999"}
            ],
        },
        ensure_ascii=False,
    )
    gateway = StubGateway({"outline_planner": response})
    deps = AgentDeps(gateway=gateway)  # type: ignore[arg-type]

    with pytest.raises(StructuredOutputError):
        await run_outline_planner(
            deps,
            json.dumps(KERNEL),
            json.dumps([CHARACTER]),
            "v1",
            None,
            chapters_needed=1,
        )
