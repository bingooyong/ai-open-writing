"""隔夜长跑:窗口不足时 plan-more,再写下一截未锁定章;预算与人工门禁处停下。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import assert_never

from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.domain.models import ChapterRecord, WorkflowRunRecord
from novel_agent.domain.repos import BibleRepo, CanonRepo, OpsRepo, PlanningRepo
from novel_agent.domain.schemas import ChapterStatus
from novel_agent.gateway.base import slot_pricing
from novel_agent.planning.chain import PlanningAborted, PlanningError, PlanningGates
from novel_agent.planning.volume import DEFAULT_WINDOW, PlanMoreError, plan_more, window_deficit
from novel_agent.production.loop import (
    ChapterLoopError,
    ChapterLoopGates,
    ChapterLoopResult,
    run_chapter_loop,
    stage_chapter_overlay,
)
from novel_agent.runtime.agents import AgentDeps
from novel_agent.workflow import BudgetExceeded, WorkflowPaused

KIND = "volume"
_DONE = frozenset({ChapterStatus.CANON_LOCKED, ChapterStatus.EXPORTED})
_active_lock = threading.Lock()
_active_projects: set[int] = set()
_stop_requested: set[int] = set()


class VolumeStopReason(StrEnum):
    BUDGET = "BUDGET"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    NEEDS_REPLAN = "NEEDS_REPLAN"
    STALE = "STALE"
    MAX_CHAPTERS = "MAX_CHAPTERS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class VolumeRunError(Exception):
    """长跑参数或前置条件非法。"""


class VolumeBusyError(VolumeRunError):
    """同一项目已有进行中的卷长跑(进程内)。"""


@dataclass
class VolumeRunResult:
    project_id: int
    run_id: int
    status: str
    chapters_done: int
    chapter_keys: list[str]
    spent_usd: float
    budget_usd: float
    stop_reason: str
    results: list[ChapterLoopResult] = field(default_factory=list)
    current_chapter: str = ""
    max_chapters: int | None = None

    def to_status(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "status": self.status,
            "chapters_done": self.chapters_done,
            "chapter_keys": list(self.chapter_keys),
            "spent_usd": self.spent_usd,
            "budget_usd": self.budget_usd,
            "stop_reason": self.stop_reason,
            "current_chapter": self.current_chapter,
            "max_chapters": self.max_chapters,
            "cancel_requested": False,
        }


def volume_is_active(project_id: int) -> bool:
    with _active_lock:
        return project_id in _active_projects


def request_volume_stop(project_id: int) -> bool:
    """协作停止:下一章检查点生效,不杀进程。进行中则记下请求。"""
    with _active_lock:
        if project_id not in _active_projects:
            return False
        _stop_requested.add(project_id)
        return True


def volume_stop_requested(project_id: int) -> bool:
    with _active_lock:
        return project_id in _stop_requested


def idle_volume_status(project_id: int) -> dict[str, object]:
    return {
        "project_id": project_id,
        "run_id": None,
        "status": "idle",
        "chapters_done": 0,
        "chapter_keys": [],
        "spent_usd": 0.0,
        "budget_usd": 0.0,
        "stop_reason": "",
        "current_chapter": "",
        "max_chapters": None,
        "cancel_requested": False,
    }


def status_from_run(project_id: int, run: WorkflowRunRecord) -> dict[str, object]:
    spent = run.budget_spent if isinstance(run.budget_spent, dict) else {}
    keys = [str(item) for item in (spent.get("chapter_keys") or [])]
    max_raw = spent.get("max_chapters")
    return {
        "project_id": project_id,
        "run_id": run.id,
        "status": run.status,
        "chapters_done": int(spent.get("chapters_done") or len(keys)),
        "chapter_keys": keys,
        "spent_usd": float(spent.get("spent_usd") or 0),
        "budget_usd": float(spent.get("budget_usd") or 0),
        "stop_reason": str(spent.get("stop_reason") or ""),
        "current_chapter": str(spent.get("current_chapter") or run.current_node or ""),
        "max_chapters": int(max_raw) if max_raw is not None else None,
        "cancel_requested": bool(spent.get("cancel_requested"))
        or volume_stop_requested(project_id),
    }


def _blocker_reason(status: ChapterStatus) -> VolumeStopReason | None:
    if status is ChapterStatus.HUMAN_REVIEW:
        return VolumeStopReason.HUMAN_REVIEW
    if status is ChapterStatus.NEEDS_REPLAN:
        return VolumeStopReason.NEEDS_REPLAN
    if status is ChapterStatus.STALE:
        return VolumeStopReason.STALE
    if status in {
        ChapterStatus.PLANNED,
        ChapterStatus.DRAFTING,
        ChapterStatus.ADVERSARIAL_REVIEW,
        ChapterStatus.JUDGING,
        ChapterStatus.NEEDS_REVISION,
        ChapterStatus.APPROVED,
        ChapterStatus.CANON_LOCKED,
        ChapterStatus.EXPORTED,
    }:
        return None
    assert_never(status)


def _next_unfinished(chapters: list[ChapterRecord]) -> ChapterRecord | None:
    for chapter in chapters:
        if chapter.status not in _DONE:
            return chapter
    return None


def _require_budget(budget_usd: float) -> None:
    if budget_usd <= 0:
        raise VolumeRunError("--budget-usd 必须是正数")


def _require_real_pricing(settings: Settings) -> None:
    for name in ("creative", "review", "judge", "extract"):
        slot = getattr(settings, name)
        if slot.provider == "mock":
            continue
        if slot_pricing(slot) is None:
            raise VolumeRunError(f"真实模型槽位 {name} 缺少单价,无法执行 USD 硬上限")


def _occupy(project_id: int) -> Callable[[], None]:
    with _active_lock:
        if project_id in _active_projects:
            raise VolumeBusyError(f"项目 {project_id} 已有进行中的卷长跑")
        _active_projects.add(project_id)
        _stop_requested.discard(project_id)

    def release() -> None:
        with _active_lock:
            _active_projects.discard(project_id)
            _stop_requested.discard(project_id)

    return release


async def run_volume(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    *,
    budget_usd: float,
    yes: bool = False,
    max_chapters: int | None = None,
    open_volume: bool = False,
    window: int | None = None,
    settings: Settings | None = None,
    git_root: Path | None = None,
    run_id: int | None = None,
) -> VolumeRunResult:
    """无人值守卷长跑:plan-more 补窗口,写未锁定章,遇门禁/预算停下。可从 SUCCESS 节点续跑。"""
    _require_budget(budget_usd)
    if max_chapters is not None and max_chapters < 1:
        raise VolumeRunError("--max-chapters 必须 >= 1")
    if settings is None:
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
    _require_real_pricing(settings)
    if deps.project_id is None:
        deps.project_id = project_id

    planning = PlanningRepo(session)
    try:
        planning.get_project(project_id)
    except Exception as exc:
        raise VolumeRunError(f"项目不存在: {project_id}") from exc
    if not planning.list_chapters(project_id):
        raise VolumeRunError("长跑需要先完成开书滚动章纲")

    roll_window = window or settings.rolling_window or DEFAULT_WINDOW
    ops = OpsRepo(session)
    release = _occupy(project_id)
    try:
        return await _run_occupied(
            session,
            deps,
            planning,
            ops,
            project_id,
            budget_usd=budget_usd,
            yes=yes,
            max_chapters=max_chapters,
            open_volume=open_volume,
            roll_window=roll_window,
            settings=settings,
            git_root=git_root,
            run_id=run_id,
        )
    finally:
        release()


async def _run_occupied(
    session: Session,
    deps: AgentDeps,
    planning: PlanningRepo,
    ops: OpsRepo,
    project_id: int,
    *,
    budget_usd: float,
    yes: bool,
    max_chapters: int | None,
    open_volume: bool,
    roll_window: int,
    settings: Settings,
    git_root: Path | None,
    run_id: int | None,
) -> VolumeRunResult:
    run = _resolve_run(ops, project_id, run_id)
    assert run.id is not None
    spent_blob = dict(run.budget_spent or {})
    written = [str(item) for item in (spent_blob.get("chapter_keys") or [])]
    results: list[ChapterLoopResult] = []
    spent_at_start = float(spent_blob.get("spent_usd_at_start") or ops.spent_usd(project_id))
    payload: dict[str, object] = {
        "budget_usd": budget_usd,
        "spent_usd_at_start": spent_at_start,
        "spent_usd": 0.0,
        "max_chapters": max_chapters,
        "open_volume": open_volume,
        "window": roll_window,
        "yes": yes,
        "chapter_keys": list(written),
        "chapters_done": len(written),
        "stop_reason": "",
        "current_chapter": "",
        "cancel_requested": False,
    }
    ops.update_workflow(run.id, status="running", current_node="", budget_spent=payload)
    session.commit()

    gates = ChapterLoopGates.auto() if yes else ChapterLoopGates.hold()
    plan_gates = PlanningGates.auto()
    bible = BibleRepo(session)
    canon = CanonRepo(session)
    stop = VolumeStopReason.COMPLETE
    current = ""
    workflow_id = run.id

    def spent_now() -> float:
        return round(max(0.0, ops.spent_usd(project_id) - spent_at_start), 6)

    def persist(*, status: str | None = "running", reason: str = "") -> None:
        payload["spent_usd"] = spent_now()
        payload["chapter_keys"] = list(written)
        payload["chapters_done"] = len(written)
        payload["stop_reason"] = reason
        payload["current_chapter"] = current
        payload["cancel_requested"] = bool(payload.get("cancel_requested")) or volume_stop_requested(
            project_id
        )
        ops.update_workflow(
            workflow_id,
            status=status,
            current_node=current,
            budget_spent=dict(payload),
        )
        session.commit()

    try:
        while True:
            persist()
            if volume_stop_requested(project_id) or payload.get("cancel_requested"):
                stop = VolumeStopReason.CANCELLED
                break
            if max_chapters is not None and len(written) >= max_chapters:
                stop = VolumeStopReason.MAX_CHAPTERS
                break
            if spent_now() >= budget_usd:
                stop = VolumeStopReason.BUDGET
                break

            chapters = planning.list_chapters(project_id)
            nxt = _next_unfinished(chapters)
            if nxt is not None:
                blocked = _blocker_reason(nxt.status)
                if blocked is not None:
                    current = nxt.chapter_key
                    stop = blocked
                    break

            if window_deficit(chapters, roll_window) > 0:
                try:
                    await plan_more(
                        planning,
                        bible,
                        canon,
                        deps,
                        project_id,
                        plan_gates,
                        window=roll_window,
                        open_volume=True if open_volume else None,
                    )
                except PlanningAborted as exc:
                    raise VolumeRunError(f"续规划已中止: {exc.stage}") from exc
                except (PlanMoreError, PlanningError) as exc:
                    raise VolumeRunError(f"续规划失败: {exc}") from exc
                session.commit()
                if spent_now() >= budget_usd:
                    stop = VolumeStopReason.BUDGET
                    break
                chapters = planning.list_chapters(project_id)

            nxt = _next_unfinished(chapters)
            if nxt is None:
                stop = VolumeStopReason.COMPLETE
                break
            blocked = _blocker_reason(nxt.status)
            if blocked is not None:
                current = nxt.chapter_key
                stop = blocked
                break
            if max_chapters is not None and len(written) >= max_chapters:
                stop = VolumeStopReason.MAX_CHAPTERS
                break

            current = nxt.chapter_key
            persist()
            try:
                result = await run_chapter_loop(
                    session,
                    deps,
                    project_id,
                    nxt.chapter_key,
                    gates=gates,
                    settings=settings,
                    git_root=git_root,
                    include_provisional=True,
                )
            except (BudgetExceeded, WorkflowPaused):
                stop = VolumeStopReason.BUDGET
                persist(status="paused", reason=VolumeStopReason.BUDGET.value)
                return _finish(
                    project_id,
                    workflow_id,
                    "paused",
                    written,
                    results,
                    spent_now(),
                    budget_usd,
                    VolumeStopReason.BUDGET,
                    current,
                    max_chapters,
                )
            except ChapterLoopError as exc:
                persist(status="failed", reason=str(exc))
                raise VolumeRunError(str(exc)) from exc

            if not yes and result.status is ChapterStatus.HUMAN_REVIEW:
                await stage_chapter_overlay(session, deps, project_id, result.chapter_key)
            session.commit()
            results.append(result)
            if result.status is ChapterStatus.CANON_LOCKED:
                if result.chapter_key not in written:
                    written.append(result.chapter_key)
                current = ""
                continue
            after = _blocker_reason(result.status)
            if after is not None:
                current = result.chapter_key
                stop = after
                break
            if result.status is ChapterStatus.EXPORTED:
                continue
            current = result.chapter_key
            stop = VolumeStopReason.HUMAN_REVIEW
            break
    except VolumeRunError:
        persist(status="failed")
        raise

    if stop is VolumeStopReason.CANCELLED:
        final_status = "cancelled"
    elif stop in {
        VolumeStopReason.HUMAN_REVIEW,
        VolumeStopReason.NEEDS_REPLAN,
        VolumeStopReason.STALE,
        VolumeStopReason.BUDGET,
    }:
        final_status = "paused"
    elif stop in {VolumeStopReason.MAX_CHAPTERS, VolumeStopReason.COMPLETE}:
        final_status = "succeeded"
    else:
        assert_never(stop)
    persist(status=final_status, reason=stop.value)
    return _finish(
        project_id,
        workflow_id,
        final_status,
        written,
        results,
        spent_now(),
        budget_usd,
        stop,
        current,
        max_chapters,
    )


def _resolve_run(ops: OpsRepo, project_id: int, run_id: int | None) -> WorkflowRunRecord:
    if run_id is not None:
        return ops.get_workflow_run(run_id)
    existing = ops.find_resumable_run(project_id, KIND)
    if existing is not None:
        return existing
    return ops.create_workflow_run(project_id, KIND)


def _finish(
    project_id: int,
    run_id: int,
    status: str,
    written: list[str],
    results: list[ChapterLoopResult],
    spent_usd: float,
    budget_usd: float,
    stop: VolumeStopReason,
    current: str,
    max_chapters: int | None,
) -> VolumeRunResult:
    return VolumeRunResult(
        project_id=project_id,
        run_id=run_id,
        status=status,
        chapters_done=len(written),
        chapter_keys=list(written),
        spent_usd=spent_usd,
        budget_usd=budget_usd,
        stop_reason=stop.value,
        results=results,
        current_chapter=current,
        max_chapters=max_chapters,
    )
