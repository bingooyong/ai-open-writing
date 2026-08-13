"""阶段0 最小 TXT/Markdown 导出(Spec D13)。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, assert_never

from sqlmodel import Session

from novel_agent.domain.repos import PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus
from novel_agent.production.loop import draft_from_record

ExportFormat = Literal["txt", "md"]

_EXPORTABLE = frozenset(
    {
        ChapterStatus.HUMAN_REVIEW,
        ChapterStatus.APPROVED,
        ChapterStatus.CANON_LOCKED,
        ChapterStatus.EXPORTED,
        ChapterStatus.NEEDS_REVISION,
        ChapterStatus.ADVERSARIAL_REVIEW,
        ChapterStatus.JUDGING,
        ChapterStatus.DRAFTING,
    }
)


def _chapter_block(fmt: ExportFormat, chapter_key: str, title: str, body: str) -> str:
    heading = title or chapter_key
    if fmt == "md":
        return f"## {chapter_key} {heading}\n\n{body.strip()}\n"
    if fmt == "txt":
        return f"{chapter_key} {heading}\n{body.strip()}\n"
    assert_never(fmt)


def render_export(session: Session, project_id: int, fmt: ExportFormat) -> str:
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    project = planning.get_project(project_id)
    chunks: list[str] = []
    if fmt == "md":
        chunks.append(f"# {project.title}\n")
    elif fmt == "txt":
        chunks.append(f"{project.title}\n")
    else:
        assert_never(fmt)
    for chapter in planning.list_chapters(project_id):
        if chapter.status not in _EXPORTABLE:
            continue
        draft = production.latest_chapter_draft(project_id, chapter.chapter_key)
        if draft is None:
            continue
        body = draft_from_record(draft).full_text()
        chunks.append(_chapter_block(fmt, chapter.chapter_key, chapter.title, body))
    return "\n".join(chunks).rstrip() + "\n"


def export_project(
    session: Session, project_id: int, fmt: ExportFormat, out: Path | None = None
) -> Path | str:
    text = render_export(session, project_id, fmt)
    if out is None:
        return text
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
