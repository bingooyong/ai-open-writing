"""M4.2: smoke-stage0 is gated, never calls paid APIs from pytest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, SlotConfig
from novel_agent.gateway import MockProvider
from novel_agent.gateway.base import estimate_cost, slot_pricing
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.planning.settings import BASE_REVIEW_ROLES
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults
from novel_agent.verification.m26_smoke import SmokeGateError
from novel_agent.verification.stage0_smoke import (
    STAGE0_PREFLIGHT,
    run_stage0_smoke,
    validate_stage0_settings,
)

_PREFLIGHT_INPUT = 12_000
_LEGACY_PREFLIGHT = (
    ("creative", 6, 16_000),
    ("review", 15, 8_000),
    ("judge", 3, 6_000),
    ("extract", 1, 6_000),
)


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


def _table_cost(settings: Settings, table: tuple[tuple[str, int, int], ...]) -> float:
    worst = 0.0
    for slot_name, calls, output_tokens in table:
        slot = getattr(settings, slot_name)
        pricing = slot_pricing(slot)
        assert pricing is not None
        worst += calls * estimate_cost(
            slot.model, _PREFLIGHT_INPUT, output_tokens, pricing=pricing
        )
    return round(worst, 6)


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
        "6_later_retrieval_facts",
    }
    assert all(item["ok"] for item in report["exit_conditions"].values())
    lowered = text.lower()
    assert "sk-test" not in lowered
    assert "api_key" not in lowered
    assert "<<<scene:" not in lowered
    assert "醒木" not in text
    factory = report["factory"]
    assert factory["enable_writer_b"] is True
    assert factory["enable_reader_advocate"] is True
    assert factory["review_role_count"] == len(BASE_REVIEW_ROLES) + 1
    assert factory["planning"] == "run_planning_chain"
    later = [
        row
        for row in report["exit_conditions"]["1_three_chapter_drafts"]["chapters"]
        if row["chapter_key"] != report["planned_chapters"][0]
    ]
    assert later
    assert all(row["retrieval_facts"] >= 1 for row in later)
    assert report["exit_conditions"]["6_later_retrieval_facts"]["ok"] is True


def test_preflight_tracks_dual_writer_advocate_and_per_chapter_extract() -> None:
    """Would have failed while the table still counted 1 writer / 5 reviewers / 1 extract."""
    reviewers = len(BASE_REVIEW_ROLES) + 1
    by_slot = {name: calls for name, calls, _tokens in STAGE0_PREFLIGHT}
    assert by_slot == {
        "creative": 3 + 3 * 2,
        "review": 3 * reviewers,
        "judge": 3,
        "extract": 3,
    }
    assert by_slot["creative"] > 6
    assert by_slot["review"] > 15
    assert by_slot["extract"] > 1


def test_budget_that_only_covers_legacy_preflight_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    legacy = _table_cost(settings, _LEGACY_PREFLIGHT)
    current = validate_stage0_settings(settings, 50.0)
    assert current > legacy
    mid = round((legacy + current) / 2, 6)
    with pytest.raises(SmokeGateError, match="preflight"):
        validate_stage0_settings(settings, mid)


def test_smoke_stage0_help_documents_gates() -> None:
    result = CliRunner().invoke(app, ["smoke-stage0", "--help"])
    assert result.exit_code == 0, result.output
    text = result.output.lower()
    assert "--confirm-real-models" in result.output
    assert "--budget-usd" in result.output
    assert "mock" in text
    assert "ci" in text or "预算" in result.output

