"""请求体与共用序列化。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from novel_agent.production.loop import ChapterLoopResult


class ProjectCreate(BaseModel):
    title: str
    spark: str = ""
    genre: str = ""
    auto_bible: bool = True
    chapters: int = 5
    volume_id: str = "v1"
    select: int = 1
    skip_concept_judge: bool = False


class ProjectPatch(BaseModel):
    title: str | None = None
    genre: str | None = None
    spark: str | None = None
    enable_writer_b: bool | None = None
    enable_reader_advocate: bool | None = None


class RoundConfirm(BaseModel):
    select: int = 1


class WriteChapterBody(BaseModel):
    yes: bool = False


class WriteBatchBody(BaseModel):
    chapters: int = Field(default=3, ge=3, le=5)
    yes: bool = False
    from_chapter: str | None = None


class PlanMoreBody(BaseModel):
    window: int = Field(default=5, ge=1)
    chapters: int | None = Field(default=None, ge=1)
    open_volume: bool | None = None


class ResumeBody(BaseModel):
    chapter_key: str | None = None
    yes: bool = False


class EditOutlineBody(BaseModel):
    yaml: str = ""


class LockedRangesBody(BaseModel):
    ranges: list[str] = Field(default_factory=list)


def loop_payload(result: ChapterLoopResult) -> dict[str, object]:
    return {
        "project_id": result.project_id,
        "chapter_key": result.chapter_key,
        "status": result.status.value,
        "verdict": result.verdict.value if result.verdict else None,
        "revision_round": result.revision_round,
        "stopped_at": result.stopped_at,
        "reason": result.reason,
    }
