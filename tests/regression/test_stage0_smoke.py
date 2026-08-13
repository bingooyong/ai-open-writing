"""M4.2: smoke-stage0 is gated, never calls paid APIs from pytest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, SlotConfig
from novel_agent.gateway import MockProvider
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults
from novel_agent.verification.m26_smoke import SmokeGateError
from novel_agent.verification.stage0_smoke import run_stage0_smoke, validate_stage0_settings


def _slot(family: str, model: str = "claude-sonnet-4") -> SlotConfig:
    return SlotConfig.model_validate(
        {
            "provider": "openai_compat",
            "model": model,
            "family": family,
            "api_key": "sk-test",
            "base_url": "https://example.invalid/v1",
        }
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "stage0.db",
        creative=_slot("creative-family"),
        review=_slot("review-family"),
        judge=_slot("judge-family", "gpt-5-mini"),
        extract=_slot("extract-family"),
    )


@pytest.mark.parametrize(
    "args",
    [
        ["smoke-stage0"],
        ["smoke-stage0", "--confirm-real-models"],
        ["smoke-stage0", "--budget-usd", "10"],
    ],
)
def test_smoke_stage0_refuses_without_explicit_confirm(args: list[str]) -> None:
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    assert "passed" not in result.output.lower()


def test_mock_slots_are_skipped_before_any_provider(tmp_path: Path) -> None:
    with pytest.raises(SmokeGateError, match="mock"):
        validate_stage0_settings(Settings(_env_file=None, db_path=tmp_path / "x.db"), 10.0)


def test_same_family_and_tiny_budget_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.judge = settings.judge.model_copy(update={"family": settings.creative.family})
    with pytest.raises(SmokeGateError, match="family"):
        validate_stage0_settings(settings, 50.0)
    with pytest.raises(SmokeGateError, match="preflight"):
        validate_stage0_settings(_settings(tmp_path), 0.01)


async def test_stage0_smoke_writes_redacted_checklist_without_paid_apis(
    tmp_path: Path,
) -> None:
    mock = MockProvider()
    register_planning_defaults(mock)
    register_chapter_loop_defaults(mock)
    report_path = tmp_path / "stage0.json"
    result = await run_stage0_smoke(
        _settings(tmp_path),
        budget_usd=50.0,
        report_path=report_path,
        providers={"openai_compat": mock},
    )
    assert result == report_path
    text = report_path.read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["kind"] == "stage0-three-chapter-smoke"
    assert set(report["exit_conditions"]) == {
        "1_three_chapter_drafts",
        "2_implanted_conflicts",
        "3_resume",
        "4_revision_cap",
        "5_model_runs",
    }
    assert all(item["ok"] for item in report["exit_conditions"].values())
    lowered = text.lower()
    assert "sk-test" not in lowered
    assert "api_key" not in lowered
    assert "<<<scene:" not in lowered
    assert "醒木" not in text

