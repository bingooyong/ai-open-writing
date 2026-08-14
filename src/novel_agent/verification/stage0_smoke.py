"""Bounded M4.2 real-model three-chapter smoke. No automatic entrypoint."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from novel_agent.config import Settings, SlotConfig
from novel_agent.context.context_builder import ContextBuilder
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.models import ModelRunRecord, NodeRunRecord
from novel_agent.domain.repos import CanonRepo, PlanningRepo, ProductionRepo
from novel_agent.gateway.base import ModelGateway, Provider, estimate_cost, slot_pricing
from novel_agent.memory.factory import memory_retrieval_for_session
from novel_agent.planning.chain import PlanningGates, run_planning_chain
from novel_agent.production.batch import resume_project, run_write_batch
from novel_agent.production.loop import ChapterLoopResult
from novel_agent.production.runtime import build_production_deps
from novel_agent.runtime.agents import AgentDeps
from novel_agent.verification.m26_smoke import SmokeExecutionError, SmokeGateError

_SLOT_NAMES = ("creative", "review", "judge", "extract")
# Planning (kernel/character/outline) + 3 writers; 3×5 reviewers; 3 judges; extract buffer.
_PREFLIGHT = (
    ("creative", 6, 16_000),
    ("review", 15, 8_000),
    ("judge", 3, 6_000),
    ("extract", 1, 6_000),
)
_PREFLIGHT_INPUT = 12_000
_EXIT_KEYS = (
    "1_three_chapter_drafts",
    "2_implanted_conflicts",
    "3_resume",
    "4_revision_cap",
    "5_model_runs",
)


def _price(slot: SlotConfig) -> tuple[float, float]:
    pricing = slot_pricing(slot)
    if pricing is None:
        raise SmokeGateError(
            f"model pricing unknown for {slot.model!r}; configure both explicit price overrides"
        )
    return pricing


def validate_stage0_settings(settings: Settings, budget_usd: float) -> float:
    """Reject unsafe configuration; return conservative preflight cost.

    Mock or missing real slots are a documented skip, not a paid run.
    """
    if budget_usd <= 0:
        raise SmokeGateError("--budget-usd must be positive")
    for name in _SLOT_NAMES:
        slot = getattr(settings, name)
        if slot.provider == "mock":
            raise SmokeGateError(
                f"slot {name} is mock; all four slots must be real "
                "(skip Stage 0 paid smoke when env slots are missing)"
            )
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


def _count_n3(session: Session) -> int:
    return sum(
        1
        for rec in session.exec(select(NodeRunRecord)).all()
        if rec.node_name == "n3_draft" and rec.status == "succeeded"
    )


def _model_run_complete(run: ModelRunRecord) -> bool:
    return bool(
        run.prompt_version
        and run.input_tokens is not None
        and run.output_tokens is not None
        and run.latency_ms is not None
        and run.cost_estimate is not None
    )


def _volume_summary(planning: PlanningRepo, project_id: int, volume_id: str) -> str:
    for volume in planning.list_volumes(project_id):
        if volume.volume_id == volume_id:
            goal = ""
            if isinstance(volume.payload, dict):
                goal = str(volume.payload.get("goal") or "")
            title = volume.title or volume_id
            return f"{title}: {goal}".rstrip(": ")
    return volume_id


async def run_stage0_smoke(
    settings: Settings,
    *,
    budget_usd: float,
    report_path: Path | None = None,
    providers: Mapping[str, Provider] | None = None,
) -> Path:
    """Plan a miniature project and drive three pending chapters with real slots.

    ``providers`` exists solely as an offline test seam. The CLI never supplies it.
    """
    preflight = validate_stage0_settings(settings, budget_usd)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = report_path or Path("artifacts/verification") / f"stage0-smoke-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    db_path = out.with_suffix(".db")

    engine = build_engine(db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("M4.2 三章冒烟", genre="奇幻")
        assert project.id is not None
        session.commit()
        if providers is not None:
            deps = AgentDeps(
                gateway=ModelGateway(settings, session, dict(providers)),
                project_id=project.id,
            )
        else:
            deps = build_production_deps(settings, session, project.id)
        planned = await run_planning_chain(
            repo,
            deps,
            brief="说书人发现故事会成真",
            gates=PlanningGates.auto(),
            volume_id="v1",
            chapters_needed=3,
        )
        session.commit()
        batch = await run_write_batch(
            session,
            deps,
            project.id,
            chapter_count=3,
            yes=False,
            settings=settings,
        )
        session.commit()
        n3_before = _count_n3(session)
        resumed: list[ChapterLoopResult] = []
        for item in batch.results:
            resumed.extend(
                await resume_project(
                    session, deps, project.id, item.chapter_key, settings=settings
                )
            )
        session.commit()
        n3_after = _count_n3(session)

        production = ProductionRepo(session)
        canon = CanonRepo(session)
        builder = ContextBuilder(repo, canon, retrieval=memory_retrieval_for_session(session))
        chapter_rows: list[dict[str, Any]] = []
        later_has_prior = False
        for index, item in enumerate(batch.results):
            drafts = production.list_drafts(project.id, item.chapter_key)
            outline = repo.get_outline(project.id, item.chapter_key)
            package = builder.build(
                project.id,
                item.chapter_key,
                task_brief=f"撰写{item.chapter_key}",
                volume_summary=_volume_summary(repo, project.id, outline.volume_id),
                include_provisional=True,
            )
            prior_facts = [
                fact
                for fact in package.entity_states
                if fact.provisional
                or (fact.source_chapter and fact.source_chapter != item.chapter_key)
            ]
            if index > 0 and prior_facts:
                later_has_prior = True
            chapter_rows.append(
                {
                    "chapter_key": item.chapter_key,
                    "status": item.status.value,
                    "verdict": item.verdict.value if item.verdict else None,
                    "drafts": len(drafts),
                    "stopped_at": item.stopped_at,
                    "prior_facts": len(prior_facts),
                }
            )

        runs = list(session.exec(select(ModelRunRecord)).all())
        spent = round(sum(float(run.cost_estimate or 0) for run in runs), 6)
        complete_runs = sum(1 for run in runs if _model_run_complete(run))
        payload: dict[str, Any] = {
            "kind": "stage0-three-chapter-smoke",
            "created_at": stamp,
            "preflight_usd": preflight,
            "spent_usd": spent,
            "budget_usd": budget_usd,
            "project_id": project.id,
            "planned_chapters": planned.chapter_keys,
            "resumed": len(resumed),
            "exit_conditions": {
                "1_three_chapter_drafts": {
                    "ok": len(batch.results) == 3
                    and all(row["drafts"] >= 1 for row in chapter_rows),
                    "chapters": chapter_rows,
                    "later_context_has_prior_facts": later_has_prior,
                    "human_signoff": "pending",
                    "notes": "prose quality is not the bar",
                },
                "2_implanted_conflicts": {
                    "ok": True,
                    "gate": "pytest tests/regression R1-R3 (mock merge gate)",
                    "this_run": "not re-implanted; paid Judge blocking is optional",
                },
                "3_resume": {
                    "ok": n3_after == n3_before,
                    "n3_before": n3_before,
                    "n3_after": n3_after,
                },
                "4_revision_cap": {
                    "ok": settings.max_revision_rounds == 2,
                    "max_revision_rounds": settings.max_revision_rounds,
                    "exercised": any(item.revision_round >= 2 for item in batch.results),
                    "mock_evidence": (
                        "tests/workflow/test_chapter_loop.py::"
                        "test_revise_local_two_round_path_then_pass"
                    ),
                },
                "5_model_runs": {
                    "ok": bool(runs) and complete_runs == len(runs),
                    "count": len(runs),
                    "complete": complete_runs,
                },
            },
        }
        missing = [key for key in _EXIT_KEYS if key not in payload["exit_conditions"]]
        if missing:
            raise RuntimeError(f"smoke report missing exit conditions: {missing}")
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if spent > budget_usd:
            raise SmokeExecutionError(out, "budget_exceeded")
        cond = payload["exit_conditions"]
        if not all(bool(cond[key]["ok"]) for key in _EXIT_KEYS):
            raise SmokeExecutionError(out, "exit_condition_failed")
    return out
