"""Offline contracts for the explicitly authorized M2.6 real-model smoke runner."""

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select
from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, SlotConfig
from novel_agent.domain.db import build_engine
from novel_agent.domain.models import ModelRunRecord
from novel_agent.gateway.base import ModelRequest, ModelResponse
from novel_agent.verification.m26_smoke import (
    PROMPT_ROLES,
    SmokeExecutionError,
    SmokeGateError,
    run_m26_smoke,
    validate_m26_settings,
)

TWO_PART = """<<<SCENE:v1c001_s1>>>
茶楼灯火照着说书人，他忽然听见门外传来急促马蹄声。
<<<END>>>
<<<META>>>
{"chapter_summary": "马蹄声打断了说书", "deviation_notes": ""}"""


def _review(role: str) -> str:
    return json.dumps(
        {
            "reviewer_role": role,
            "candidate_id": "candidate_1",
            "issues": [
                {
                    "issue_id": "raw_1",
                    "reviewer_role": role,
                    "claim": "节奏可再收紧",
                    "evidence": [{"scene_id": "v1c001_s1", "quote": "茶楼灯火"}],
                    "violated_rule": "章节节奏",
                    "severity": "P2",
                    "failure_consequence": "开场推进偏慢",
                    "recommended_rollback_level": "prose",
                    "confidence": 0.8,
                }
            ],
        },
        ensure_ascii=False,
    )


class OfflineProvider:
    def __init__(
        self, *, excessive_usage: bool = False, malformed_kernel: bool = False
    ) -> None:
        self.roles: list[str] = []
        self.excessive_usage = excessive_usage
        self.malformed_kernel = malformed_kernel

    async def complete(self, slot, req: ModelRequest, agent_role: str) -> ModelResponse:
        self.roles.append(agent_role)
        outputs = {
            "kernel_planner": json.dumps(
                {
                    "candidates": [KERNEL, {**KERNEL, "logline": "另一个中文悬疑方向"}],
                    "differentiation_notes": "两个候选的冲突来源不同",
                },
                ensure_ascii=False,
            ),
            "character_planner": json.dumps({"characters": [CHARACTER]}, ensure_ascii=False),
            "outline_planner": json.dumps(
                {"unit": UNIT, "outlines": [OUTLINE], "scene_cards": [SCENE]},
                ensure_ascii=False,
            ),
            "writer_a": TWO_PART,
            "red_team": _review("red_team"),
            "plot": _review("plot"),
            "character": _review("character"),
            "continuity": _review("continuity"),
            "prose": _review("prose"),
            "judge": json.dumps(
                {
                    "verdict": "PASS",
                    "selected_candidate": "candidate_1",
                    "reasoning_summary": "评审问题不构成阻断",
                },
                ensure_ascii=False,
            ),
            "reviser": TWO_PART,
            "canon_curator": json.dumps(
                {"chapter_key": "v1c001", "base_canon_version": "canon_v0"},
                ensure_ascii=False,
            ),
        }
        if self.malformed_kernel:
            outputs["kernel_planner"] = "not-json"
        return ModelResponse(
            text=outputs[agent_role],
            input_tokens=100_000 if self.excessive_usage else 100,
            output_tokens=50,
            latency_ms=7,
            provider="openai_compat",
            model=slot.model,
        )


def _settings(tmp_path: Path, *, model: str = "gpt-5-smoke") -> Settings:
    def slot(family: str, selected_model: str = "gpt-5-smoke") -> dict[str, object]:
        return {
            "provider": "openai_compat",
            "model": selected_model,
            "family": family,
            "api_key": "SECRET-KEY-MUST-NOT-LEAK",
            "base_url": "https://invalid.example/v1",
        }

    return Settings(
        _env_file=None,
        db_path=tmp_path / "m26.db",
        creative=slot("creative-family"),
        review=slot("review-family"),
        judge=slot("judge-family"),
        extract=slot("extract-family", model),
    )


@pytest.mark.parametrize(
    "args",
    [[], ["smoke-m26"], ["smoke-m26", "--confirm-real-models"],
     ["smoke-m26", "--budget-usd", "10"]],
)
def test_cli_requires_confirmation_and_positive_budget(args: list[str]) -> None:
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0
    assert "passed" not in result.output


def test_mock_and_unknown_pricing_rejected_before_provider(tmp_path: Path) -> None:
    with pytest.raises(SmokeGateError, match="mock"):
        validate_m26_settings(Settings(_env_file=None), 10.0)
    with pytest.raises(SmokeGateError, match="pricing unknown"):
        validate_m26_settings(_settings(tmp_path, model="unpriced-model"), 10.0)
    with pytest.raises(SmokeGateError, match="preflight"):
        validate_m26_settings(_settings(tmp_path), 0.01)


@pytest.mark.parametrize("slot_name", ["creative", "review", "judge", "extract"])
def test_each_mock_slot_is_rejected(tmp_path: Path, slot_name: str) -> None:
    settings = _settings(tmp_path).model_copy(update={slot_name: SlotConfig()})
    with pytest.raises(SmokeGateError, match=slot_name):
        validate_m26_settings(settings, 10.0)


def test_explicit_price_override_authorizes_unknown_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.extract = settings.extract.model_copy(
        update={
            "model": "unpriced-model",
            "input_price_usd_per_million": 1.0,
            "output_price_usd_per_million": 2.0,
        }
    )
    assert validate_m26_settings(settings, 10.0) > 0


async def test_full_smoke_is_bounded_persisted_and_redacted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = OfflineProvider()
    report_path = tmp_path / "evidence.json"

    result = await run_m26_smoke(
        settings,
        budget_usd=10.0,
        report_path=report_path,
        providers={"openai_compat": provider},
    )

    assert result == report_path
    assert provider.roles == [
        "kernel_planner",
        "character_planner",
        "outline_planner",
        "writer_a",
        "red_team",
        "plot",
        "character",
        "continuity",
        "prose",
        "judge",
        "reviser",
        "canon_curator",
    ]
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["status"] == "passed"
    assert report["missing_roles"] == []
    assert len(report["calls"]) == len(PROMPT_ROLES)
    assert {call["prompt_role"] for call in report["calls"]} == set(PROMPT_ROLES)
    assert all(call["structured_output_valid"] for call in report["calls"])
    required = {
        "prompt_role",
        "agent_role",
        "slot",
        "provider",
        "model",
        "family",
        "prompt_version",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "cost_usd",
        "status",
        "structured_output_valid",
        "input_ref",
        "output_ref",
    }
    assert all(required <= set(call) for call in report["calls"])
    assert all(call["input_ref"].endswith(":input:v1") for call in report["calls"])
    assert all(call["output_ref"].endswith(":output:v1") for call in report["calls"])
    assert report["chinese_evidence_location"]["plot"] == {
        "issues": 1,
        "located": 1,
        "unlocated": 0,
    }
    assert "SECRET-KEY-MUST-NOT-LEAK" not in report_text
    assert "茶楼灯火照着说书人" not in report_text
    assert "# 待审正文" not in report_text

    with Session(build_engine(settings.db_path)) as session:
        runs = session.exec(select(ModelRunRecord)).all()
    assert len(runs) == len(PROMPT_ROLES)
    assert all(run.input_ref and run.output_ref for run in runs)
    assert report["database"]["model_run_count"] == len(runs)
    assert report["budget"]["actual_cost_usd"] == round(
        sum(run.cost_estimate for run in runs), 6
    )


async def test_usage_bound_failure_is_durable_and_never_retries(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = OfflineProvider(excessive_usage=True)
    report_path = tmp_path / "failed.json"

    with pytest.raises(SmokeExecutionError) as caught:
        await run_m26_smoke(
            settings,
            budget_usd=10.0,
            report_path=report_path,
            providers={"openai_compat": provider},
        )

    assert caught.value.report_path == report_path
    assert provider.roles == ["kernel_planner"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["failure_kind"] == "GatewayError"
    assert report["database"]["model_run_count"] == 1


async def test_invalid_structure_never_triggers_a_repair_call(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = OfflineProvider(malformed_kernel=True)

    with pytest.raises(SmokeExecutionError):
        await run_m26_smoke(
            settings,
            budget_usd=10.0,
            report_path=tmp_path / "invalid.json",
            providers={"openai_compat": provider},
        )

    assert provider.roles == ["kernel_planner"]
