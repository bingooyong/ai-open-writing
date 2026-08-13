"""M3.5:批次连跑、resume、D15 STALE 级联。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.domain.repos import CanonRepo, OpsRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus, VerdictType
from novel_agent.planning.volume import PlanMoreError, select_write_batch_keys
from novel_agent.production.loop import (
    ChapterLoopGates,
    ChapterLoopResult,
    run_chapter_loop,
    stage_chapter_overlay,
)
from novel_agent.runtime.agents import AgentDeps
from novel_agent.workflow import transition
from novel_agent.workflow.state_machine import STALEABLE


class BatchError(Exception):
    """批次连跑失败。"""


@dataclass
class BatchResult:
    project_id: int
    results: list[ChapterLoopResult] = field(default_factory=list)
    batch_id: str = ""


def select_batch_chapters(
    planning: PlanningRepo,
    project_id: int,
    chapter_count: int,
    *,
    from_chapter: str | None = None,
) -> list[str]:
    return select_write_batch_keys(
        planning, project_id, chapter_count, from_chapter=from_chapter
    )


def unfinished_chapter_keys(planning: PlanningRepo, project_id: int) -> list[str]:
    skip = {ChapterStatus.CANON_LOCKED, ChapterStatus.EXPORTED}
    return [
        chapter.chapter_key
        for chapter in planning.list_chapters(project_id)
        if chapter.status not in skip
    ]


def cascade_stale(session: Session, project_id: int, rejected_chapter_key: str) -> list[str]:
    """D15:退回第 k 章后,k+1..n 置 STALE,作废稿件与 provisional 增量。"""
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    ops = OpsRepo(session)
    canon = CanonRepo(session)
    rejected = planning.get_chapter(project_id, rejected_chapter_key)
    stale_keys: list[str] = []
    for later in planning.list_chapters_after(project_id, rejected.order_index):
        if later.status not in STALEABLE:
            continue
        transition(planning, project_id, later.chapter_key, ChapterStatus.STALE)
        canon.discard_provisional(project_id, later.chapter_key)
        production.void_lineage(project_id, later.chapter_key)
        ops.void_succeeded_nodes_for_chapter(later.chapter_key)
        run = ops.find_resumable_run(project_id, "chapter_loop", later.chapter_key)
        if run is not None and run.id is not None:
            ops.update_workflow(run.id, status="cancelled", current_node="stale")
        stale_keys.append(later.chapter_key)
    return stale_keys


async def run_write_batch(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    *,
    chapter_count: int = 3,
    yes: bool = False,
    settings: Settings | None = None,
    git_root: Path | None = None,
    from_chapter: str | None = None,
) -> BatchResult:
    if chapter_count < 3 or chapter_count > 5:
        raise BatchError("write-batch 的 --chapters 必须是 3~5")
    planning = PlanningRepo(session)
    try:
        keys = select_batch_chapters(
            planning, project_id, chapter_count, from_chapter=from_chapter
        )
    except PlanMoreError as exc:
        raise BatchError(str(exc)) from exc
    if not keys:
        raise BatchError("没有可写的已规划章节;请先 plan-more")
    batch_id = uuid.uuid4().hex[:12]
    OpsRepo(session).create_workflow_run(project_id, "batch", batch_id=batch_id)
    session.commit()
    results: list[ChapterLoopResult] = []
    gates = ChapterLoopGates.auto() if yes else ChapterLoopGates.hold()
    for key in keys:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            key,
            gates=gates,
            settings=settings,
            git_root=git_root,
            include_provisional=True,
        )
        if (
            not yes
            and result.status is ChapterStatus.HUMAN_REVIEW
            and result.verdict is VerdictType.PASS
        ):
            await stage_chapter_overlay(session, deps, project_id, key)
            session.commit()
        results.append(result)
        if result.status is ChapterStatus.NEEDS_REPLAN:
            break
    return BatchResult(project_id=project_id, results=results, batch_id=batch_id)


async def resume_project(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str | None = None,
    *,
    yes: bool = False,
    settings: Settings | None = None,
    git_root: Path | None = None,
) -> list[ChapterLoopResult]:
    planning = PlanningRepo(session)
    keys = [chapter_key] if chapter_key else unfinished_chapter_keys(planning, project_id)
    gates = ChapterLoopGates.auto() if yes else ChapterLoopGates.hold()
    results: list[ChapterLoopResult] = []
    for key in keys:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            key,
            gates=gates,
            settings=settings,
            git_root=git_root,
            include_provisional=True,
        )
        if (
            not yes
            and result.status is ChapterStatus.HUMAN_REVIEW
            and result.verdict is VerdictType.PASS
        ):
            await stage_chapter_overlay(session, deps, project_id, key)
            session.commit()
        results.append(result)
    return results
