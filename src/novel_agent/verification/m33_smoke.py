"""Bounded M3.3 real-model single-chapter smoke. No automatic entrypoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from novel_agent.config import Settings, SlotConfig
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.models import ModelRunRecord
from novel_agent.domain.repos import PlanningRepo
from novel_agent.gateway.base import estimate_cost, slot_pricing
from novel_agent.planning.chain import PlanningGates, run_planning_chain
from novel_agent.production.loop import ChapterLoopGates, run_chapter_loop
from novel_agent.production.runtime import build_production_deps
from novel_agent.verification.m26_smoke import SmokeExecutionError, SmokeGateError

_SLOT_NAMES = ("creative", "review", "judge", "extract")
_PREFLIGHT = (
    ("creative", 1, 16_000),
    ("review", 5, 8_000),
    ("judge", 1, 6_000),
    ("extract", 1, 6_000),
)
_PREFLIGHT_INPUT = 12_000


def _price(slot: SlotConfig) -> tuple[float, float]:
    pricing = slot_pricing(slot)
    if pricing is None:
        raise SmokeGateError(
            f"model pricing unknown for {slot.model!r}; configure both explicit price overrides"
        )
    return pricing


def validate_m33_settings(settings: Settings, budget_usd: float) -> float:
    """Reject unsafe configuration; return first-round conservative preflight cost."""
    if budget_usd <= 0:
        raise SmokeGateError("--budget-usd must be positive")
    for name in _SLOT_NAMES:
        slot = getattr(settings, name)
        if slot.provider == "mock":
            raise SmokeGateError(f"slot {name} is mock; all four slots must be real")
        _price(slot)
    if settings.creative.family == settings.judge.family:
        raise SmokeGateError("judge.family must differ from creative.family")

    worst = 0.0
    for slot_name, calls, output_tokens in _PREFLIGHT:
        slot = getattr(settings, slot_name)
        worst += calls * estimate_cost(
            slot.model, _PREFLIGHT_INPUT, output_tokens, pricing=_price(slot)
        )
    worst = round(worst, 6)
    if worst > budget_usd:
        raise SmokeGateError(
            f"budget ${budget_usd:.6f} is below conservative preflight ${worst:.6f}"
        )
    return worst


async def run_m33_smoke(
    settings: Settings,
    *,
    budget_usd: float,
    report_path: Path | None = None,
) -> Path:
    """Plan a miniature project and drive one chapter N1→N9 with real slots."""
    preflight = validate_m33_settings(settings, budget_usd)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = report_path or Path("artifacts/verification") / f"m33-smoke-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    db_path = out.with_suffix(".db")

    engine = build_engine(db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("M3.3 单章冒烟", genre="奇幻")
        assert project.id is not None
        session.commit()
        deps = build_production_deps(settings, session, project.id)
        planned = await run_planning_chain(
            repo,
            deps,
            brief="说书人发现故事会成真",
            gates=PlanningGates.auto(),
            volume_id="v1",
            chapters_needed=1,
        )
        session.commit()
        result = await run_chapter_loop(
            session,
            deps,
            project.id,
            planned.chapter_keys[0],
            gates=ChapterLoopGates.auto(),
            settings=settings,
        )
        session.commit()
        runs = list(session.exec(select(ModelRunRecord)).all())
        spent = round(sum(float(run.cost_estimate or 0) for run in runs), 6)
        payload = {
            "kind": "m33-chapter-smoke",
            "created_at": stamp,
            "preflight_usd": preflight,
            "spent_usd": spent,
            "budget_usd": budget_usd,
            "project_id": result.project_id,
            "chapter_key": result.chapter_key,
            "status": result.status.value,
            "verdict": result.verdict.value if result.verdict else None,
            "revision_round": result.revision_round,
            "stopped_at": result.stopped_at,
            "model_runs": len(runs),
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if spent > budget_usd:
            raise SmokeExecutionError(out, "budget_exceeded")
        if result.status.value not in {"CANON_LOCKED", "HUMAN_REVIEW", "NEEDS_REPLAN"}:
            raise SmokeExecutionError(out, f"unexpected_status_{result.status.value}")
    return out
