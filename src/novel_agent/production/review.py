"""M3.4:人工门禁队列、批准、退回、段落锁定。"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.domain.models import DraftVersionRecord
from novel_agent.domain.repos import CanonRepo, OpsRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus, ReviewIssue, VerdictType
from novel_agent.production.batch import cascade_stale
from novel_agent.production.loop import (
    ChapterLoopGates,
    ChapterLoopResult,
    draft_from_record,
    run_chapter_loop,
)
from novel_agent.runtime.agents import AgentDeps
from novel_agent.workflow import transition


@dataclass(frozen=True)
class ReviewItem:
    chapter_key: str
    status: ChapterStatus
    verdict: VerdictType | None
    draft_text: str
    issues: list[ReviewIssue]
    draft_id: int | None


class ReviewError(Exception):
    """人工门禁操作失败。"""


def list_review_queue(session: Session, project_id: int) -> list[ReviewItem]:
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    items: list[ReviewItem] = []
    for chapter in planning.list_chapters(project_id):
        if chapter.status is not ChapterStatus.HUMAN_REVIEW:
            continue
        draft = production.latest_chapter_draft(project_id, chapter.chapter_key)
        issues = production.list_issues(draft.id) if draft is not None and draft.id else []
        verdict = production.latest_verdict(chapter.chapter_key)
        text = ""
        if draft is not None:
            text = draft_from_record(draft).full_text()
        items.append(
            ReviewItem(
                chapter_key=chapter.chapter_key,
                status=chapter.status,
                verdict=verdict.verdict if verdict else None,
                draft_text=text,
                issues=issues,
                draft_id=draft.id if draft is not None else None,
            )
        )
    return items


async def approve_chapter(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
    *,
    git_root: Path | None = None,
    settings: Settings | None = None,
) -> ChapterLoopResult:
    planning = PlanningRepo(session)
    chapter = planning.get_chapter(project_id, chapter_key)
    if chapter.status is not ChapterStatus.HUMAN_REVIEW:
        raise ReviewError(f"章节 {chapter_key} 不在 HUMAN_REVIEW,无法批准")
    production = ProductionRepo(session)
    verdict = production.latest_verdict(chapter_key)
    if verdict is None or verdict.verdict is not VerdictType.PASS:
        raise ReviewError(f"章节 {chapter_key} 裁决不是 PASS,无法批准提交正史")
    return await run_chapter_loop(
        session,
        deps,
        project_id,
        chapter_key,
        gates=ChapterLoopGates.auto(),
        settings=settings,
        git_root=git_root,
    )


def mark_locked_ranges(
    session: Session, project_id: int, chapter_key: str, locked_ranges: list[str]
) -> None:
    production = ProductionRepo(session)
    draft = production.latest_chapter_draft(project_id, chapter_key)
    if draft is None or draft.id is None:
        raise ReviewError(f"章节 {chapter_key} 没有可标记的稿件")
    production.set_locked_ranges(draft.id, locked_ranges)


def reject_chapter(session: Session, project_id: int, chapter_key: str) -> list[str]:
    """退回 → NEEDS_REPLAN,并按 D15 将后章置 STALE。"""
    planning = PlanningRepo(session)
    chapter = planning.get_chapter(project_id, chapter_key)
    if chapter.status is ChapterStatus.HUMAN_REVIEW:
        transition(planning, project_id, chapter_key, ChapterStatus.NEEDS_REPLAN)
    elif chapter.status is not ChapterStatus.NEEDS_REPLAN:
        raise ReviewError(f"章节 {chapter_key} 状态 {chapter.status.value} 不可退回")
    CanonRepo(session).discard_provisional(project_id, chapter_key)
    run = OpsRepo(session).find_resumable_run(project_id, "chapter_loop", chapter_key)
    if run is not None and run.id is not None:
        OpsRepo(session).update_workflow(run.id, status="paused", current_node="needs_replan")
    return cascade_stale(session, project_id, chapter_key)


def review_bucket(status: ChapterStatus) -> str | None:
    match status:
        case ChapterStatus.HUMAN_REVIEW:
            return "HUMAN_REVIEW"
        case ChapterStatus.CANON_LOCKED | ChapterStatus.EXPORTED:
            return "CANON_LOCKED"
        case (
            ChapterStatus.DRAFTING
            | ChapterStatus.ADVERSARIAL_REVIEW
            | ChapterStatus.JUDGING
            | ChapterStatus.NEEDS_REVISION
            | ChapterStatus.NEEDS_REPLAN
            | ChapterStatus.APPROVED
            | ChapterStatus.STALE
        ):
            return "IN_PROGRESS"
        case ChapterStatus.PLANNED:
            return None
        case _:
            assert_never(status)


def locate_quote(quote: str, text: str) -> tuple[int, int] | None:
    """只返回正文里真实出现的引文区间;找不到则 None,绝不编造。"""
    if not quote or not text:
        return None
    start = text.find(quote)
    if start < 0:
        return None
    return start, start + len(quote)


def _draft_text(draft: DraftVersionRecord) -> str:
    if draft.content_text:
        return draft.content_text
    try:
        return draft_from_record(draft).full_text()
    except (KeyError, ValueError):
        return ""


def _active_drafts(
    production: ProductionRepo, project_id: int, chapter_key: str
) -> list[DraftVersionRecord]:
    return [
        rec
        for rec in production.list_drafts(project_id, chapter_key)
        if not (rec.meta or {}).get("voided") and not rec.lineage_id.startswith("voided:")
    ]


def _serialize_issues(issues: list[ReviewIssue], draft_text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for issue in issues:
        evidence: list[dict[str, object]] = []
        for ref in issue.evidence:
            span = locate_quote(ref.quote, draft_text)
            evidence.append(
                {
                    "scene_id": ref.scene_id,
                    "quote": ref.quote,
                    "note": ref.note,
                    "found": span is not None,
                    "start": span[0] if span else None,
                    "end": span[1] if span else None,
                }
            )
        payload = issue.model_dump(mode="json")
        payload["evidence"] = evidence
        rows.append(payload)
    return rows


def _unified_diff(previous: str, current: str) -> str:
    return "".join(
        difflib.unified_diff(
            previous.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile="previous",
            tofile="current",
        )
    )


def list_review_desk(session: Session, project_id: int) -> list[dict[str, object]]:
    """HUMAN_REVIEW / 进行中 / CANON_LOCKED 审稿台列表(含证据定位与双稿 diff)。"""
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    items: list[dict[str, object]] = []
    for chapter in planning.list_chapters(project_id):
        bucket = review_bucket(chapter.status)
        if bucket is None:
            continue
        drafts = _active_drafts(production, project_id, chapter.chapter_key)
        latest = drafts[-1] if drafts else None
        previous = drafts[-2] if len(drafts) >= 2 else None
        text = _draft_text(latest) if latest is not None else ""
        prev_text = _draft_text(previous) if previous is not None else None
        issues = production.list_issues(latest.id) if latest is not None and latest.id else []
        verdict = production.latest_verdict(chapter.chapter_key)
        items.append(
            {
                "chapter_key": chapter.chapter_key,
                "title": chapter.title,
                "status": chapter.status.value,
                "bucket": bucket,
                "verdict": verdict.verdict.value if verdict else None,
                "verdict_payload": verdict.model_dump(mode="json") if verdict else None,
                "draft_text": text,
                "previous_draft_text": prev_text,
                "diff": _unified_diff(prev_text, text) if prev_text else None,
                "issues": _serialize_issues(issues, text),
                "draft_id": latest.id if latest is not None else None,
                "locked_ranges": list(latest.locked_ranges or []) if latest is not None else [],
            }
        )
    return items
