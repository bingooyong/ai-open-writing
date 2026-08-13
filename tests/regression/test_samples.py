"""M4.1: Spec §8 R1–R6 samples driven through existing loop/lint/judge under mock."""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_agent.domain.repos import OpsRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus, VerdictType
from tests.regression.support import (
    list_sample_dirs,
    load_sample,
    reviewer_roles_called,
    run_sample,
)

SAMPLES = [load_sample(path / "sample.yaml") for path in list_sample_dirs()]
SAMPLE_BY_ID = {sample["id"]: sample for sample in SAMPLES}


def test_regression_samples_are_complete() -> None:
    assert set(SAMPLE_BY_ID) == {"R1", "R2", "R3", "R4", "R5", "R6"}


@pytest.mark.parametrize("sample", SAMPLES, ids=[sample["id"] for sample in SAMPLES])
async def test_regression_sample_matches_expected_verdict(tmp_path: Path, sample: dict) -> None:
    session, _deps, mock, result = await run_sample(tmp_path, sample)
    expect = sample["expect"]
    try:
        called = reviewer_roles_called(mock)
        if expect["reviewers_called"]:
            assert called == {
                "red_team",
                "plot",
                "character",
                "continuity",
                "prose",
                "reader_advocate",
            }
            assert any(role == "judge" for role, _req in mock.calls)
        else:
            assert called == set()
            assert all(role != "judge" for role, _req in mock.calls)
            assert result.stopped_at == "n4_lint"
            n4 = [
                rec
                for rec in OpsRepo(session).node_history(result.workflow_run_id)
                if rec.node_name == "n4_lint"
            ]
            assert n4
            assert n4[-1].output_snapshot.get("passed") is False
            assert "leak" in n4[-1].output_snapshot.get("blocking_codes", [])

        assert result.status is ChapterStatus(expect["status"])
        expected_verdict = expect["verdict"]
        if expected_verdict is None:
            assert result.verdict is None
        else:
            assert result.verdict is VerdictType(expected_verdict)

        if expect["judge_blocks"]:
            assert result.verdict is not VerdictType.PASS
            assert result.status is not ChapterStatus.CANON_LOCKED
            verdict = ProductionRepo(session).latest_verdict(result.chapter_key)
            assert verdict is not None
            assert verdict.rollback_target is not None
            assert verdict.rollback_target.value in expect["rollback"]
        elif not expect["lint_blocks"]:
            assert result.verdict is VerdictType.PASS
    finally:
        session.close()


def test_r1_r3_quotes_are_implanted() -> None:
    for sample_id, needle in (
        ("R1", "已经身亡的苏晚梅推开茶楼的门走了进来"),
        ("R2", "苏晚生心里清楚书局主人其实叫赵无咎"),
        ("R3", "霍执事把已签好的契书收进袖中"),
        ("R4", '{"issue_id": "prompt_leak"}'),
    ):
        blob = "\n".join(item["content"] for item in SAMPLE_BY_ID[sample_id]["draft_scenes"])
        assert needle in blob
