"""M4.3: Judge calibration — R5 not a blocker, R6 not false-killed, Judge input anonymized."""

from __future__ import annotations

from pathlib import Path

from novel_agent.domain.repos import ProductionRepo
from novel_agent.domain.schemas import ChapterStatus, VerdictType
from novel_agent.runtime.blinding import DEFAULT_FORBIDDEN, assert_no_leak
from tests.regression.support import (
    judge_requests,
    list_sample_dirs,
    load_sample,
    run_sample,
)

SAMPLES = {
    sample["id"]: sample
    for sample in (load_sample(path / "sample.yaml") for path in list_sample_dirs())
}


async def test_r5_evidenceless_opinion_is_not_a_blocker(tmp_path: Path) -> None:
    session, _deps, _mock, result = await run_sample(tmp_path, SAMPLES["R5"])
    try:
        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        issues = ProductionRepo(session).list_issues(result.draft_id or 0)
        downweighted = [issue for issue in issues if issue.downweighted]
        assert downweighted
        assert all(not issue.evidence for issue in downweighted)
        verdict = ProductionRepo(session).latest_verdict(result.chapter_key)
        assert verdict is not None
        downweighted_ids = {issue.issue_id for issue in downweighted}
        assert all(
            not ruling.accepted or ruling.issue_id not in downweighted_ids
            for ruling in verdict.rulings
        )
        assert not verdict.hard_gate_failures
    finally:
        session.close()


async def test_r6_clean_sample_is_not_false_killed(tmp_path: Path) -> None:
    session, _deps, _mock, result = await run_sample(tmp_path, SAMPLES["R6"])
    try:
        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        verdict = ProductionRepo(session).latest_verdict(result.chapter_key)
        assert verdict is not None
        assert not verdict.hard_gate_failures
    finally:
        session.close()


async def test_judge_input_has_no_agent_or_model_ids(tmp_path: Path) -> None:
    for sample_id in ("R1", "R5", "R6"):
        session, _deps, mock, _result = await run_sample(tmp_path / sample_id, SAMPLES[sample_id])
        try:
            requests = judge_requests(mock)
            assert requests, sample_id
            for req in requests:
                payload = f"{req.system}\n{req.user}"
                assert_no_leak(payload, DEFAULT_FORBIDDEN)
                lowered = payload.lower()
                assert "reviewer_role" not in lowered
                assert "writer_a" not in lowered
                assert "mock-model" not in lowered
        finally:
            session.close()
