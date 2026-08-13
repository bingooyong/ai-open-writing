"""写作台 HTTP 路由:项目 / bible / graph / 章节。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm.exc import NoResultFound
from sqlmodel import Session

from novel_agent.api.deps import get_app_settings, get_session, require_project
from novel_agent.api.schemas import (
    ProjectCreate,
    ProjectPatch,
    ResumeBody,
    RoundConfirm,
    WriteBatchBody,
    WriteChapterBody,
    loop_payload,
)
from novel_agent.config import Settings
from novel_agent.domain.models import ProjectRecord
from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
from novel_agent.graph.projector import project_graph
from novel_agent.planning.chain import PlanningAborted, PlanningError, PlanningGates
from novel_agent.planning.conversation import run_bible_conversation
from novel_agent.planning.rounds import bible_snapshot, confirm_round, generate_pending_round
from novel_agent.planning.runtime import build_planning_deps
from novel_agent.production.batch import BatchError, resume_project, run_write_batch
from novel_agent.production.export import export_project
from novel_agent.production.loop import ChapterLoopError, ChapterLoopGates, run_chapter_loop
from novel_agent.production.review import ReviewError, approve_chapter
from novel_agent.production.runtime import build_production_deps
from novel_agent.workflow.errors import WorkflowPaused

router = APIRouter()


def _project_out(rec: ProjectRecord, completed: list[str] | None = None) -> dict[str, object]:
    return {
        "id": rec.id,
        "title": rec.title,
        "genre": rec.genre,
        "status": rec.status,
        "spark": rec.spark,
        "brief": rec.brief,
        "completed_rounds": completed or [],
    }


def _planning_http(exc: PlanningError | PlanningAborted) -> HTTPException:
    if isinstance(exc, PlanningAborted):
        return HTTPException(status_code=409, detail=f"已中止规划阶段 {exc.stage}")
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/projects")
def list_projects(
    include_archived: bool = False,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    planning = PlanningRepo(session)
    rows = planning.list_projects()
    if not include_archived:
        rows = [row for row in rows if row.status != "archived"]
    bible = BibleRepo(session)
    return [
        _project_out(row, sorted(bible.round_complete(row.id or 0)))
        for row in rows
        if row.id is not None
    ]


@router.post("/projects")
async def create_project(
    body: ProjectCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    spark = body.spark.strip()
    if body.auto_bible and not spark:
        raise HTTPException(status_code=400, detail="自动生成 Story Bible 需要 spark")
    if body.select < 1:
        raise HTTPException(status_code=400, detail="select 必须 >= 1")
    if body.chapters < 1:
        raise HTTPException(status_code=400, detail="chapters 必须 >= 1")
    planning = PlanningRepo(session)
    project = planning.create_project(title, genre=body.genre.strip())
    if project.id is None:
        raise HTTPException(status_code=500, detail="项目写入失败")
    project_id = project.id
    if spark:
        project.spark = spark
        project.brief = spark
        session.add(project)
    session.commit()
    deps = build_planning_deps(settings, session, project_id)
    try:
        if body.auto_bible:
            await run_bible_conversation(
                planning,
                BibleRepo(session),
                CanonRepo(session),
                deps,
                spark,
                PlanningGates.auto(select_index=body.select - 1),
                volume_id=body.volume_id,
                chapters_needed=body.chapters,
            )
        else:
            await generate_pending_round(
                session,
                deps,
                project_id,
                spark,
                volume_id=body.volume_id,
                chapters_needed=body.chapters,
            )
    except (PlanningError, PlanningAborted) as exc:
        raise _planning_http(exc) from exc
    session.commit()
    rec = planning.get_project(project_id)
    bible = bible_snapshot(session, project_id)
    return {**_project_out(rec, list(bible["completed"])), "bible": bible}


@router.get("/projects/{project_id}")
def get_project(
    project_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    planning = PlanningRepo(session)
    rec = require_project(planning, project_id)
    completed = sorted(BibleRepo(session).round_complete(project_id))
    return _project_out(rec, completed)


@router.patch("/projects/{project_id}")
def patch_project(
    project_id: int,
    body: ProjectPatch,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    rec = planning.update_project(
        project_id, title=body.title, genre=body.genre, spark=body.spark
    )
    completed = sorted(BibleRepo(session).round_complete(project_id))
    return _project_out(rec, completed)


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    rec = planning.archive_project(project_id)
    completed = sorted(BibleRepo(session).round_complete(project_id))
    return _project_out(rec, completed)


@router.get("/projects/{project_id}/bible")
def get_bible(project_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    require_project(PlanningRepo(session), project_id)
    return bible_snapshot(session, project_id)


@router.post("/projects/{project_id}/bible/rounds/{round_index}/generate")
async def generate_bible_round(
    project_id: int,
    round_index: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    rec = require_project(planning, project_id)
    deps = build_planning_deps(settings, session, project_id)
    try:
        return await generate_pending_round(
            session, deps, project_id, rec.spark or rec.brief, round_index=round_index
        )
    except (PlanningError, PlanningAborted) as exc:
        raise _planning_http(exc) from exc


@router.post("/projects/{project_id}/bible/rounds/{round_index}/confirm")
async def confirm_bible_round(
    project_id: int,
    round_index: int,
    body: RoundConfirm = Body(default_factory=RoundConfirm),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    rec = require_project(planning, project_id)
    payload = body
    deps = build_planning_deps(settings, session, project_id)
    try:
        return await confirm_round(
            session,
            deps,
            project_id,
            round_index,
            rec.spark or rec.brief,
            select=payload.select,
        )
    except (PlanningError, PlanningAborted) as exc:
        raise _planning_http(exc) from exc


@router.get("/projects/{project_id}/graph")
def get_graph(project_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    graph = project_graph(project_id, planning, BibleRepo(session), CanonRepo(session))
    return graph.to_dict()


@router.get("/projects/{project_id}/chapters")
def list_chapters(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    rows: list[dict[str, object]] = []
    for chapter in planning.list_chapters(project_id):
        rows.append(
            {
                "chapter_key": chapter.chapter_key,
                "title": chapter.title,
                "status": chapter.status.value,
                "order_index": chapter.order_index,
                "revision_round": chapter.revision_round,
            }
        )
    return rows


@router.post("/projects/{project_id}/chapters/{chapter_key}/write-chapter")
async def write_chapter(
    project_id: int,
    chapter_key: str,
    body: WriteChapterBody = Body(default_factory=WriteChapterBody),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    try:
        planning.get_chapter(project_id, chapter_key)
    except NoResultFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"章节不存在 project_id={project_id} chapter_key={chapter_key}",
        ) from exc
    payload = body
    gates = ChapterLoopGates.auto() if payload.yes else ChapterLoopGates.hold()
    deps = build_production_deps(settings, session, project_id)
    try:
        result = await run_chapter_loop(
            session, deps, project_id, chapter_key, gates=gates, settings=settings
        )
    except ChapterLoopError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkflowPaused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return loop_payload(result)


@router.post("/projects/{project_id}/chapters/{chapter_key}/approve")
async def approve(
    project_id: int,
    chapter_key: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    try:
        planning.get_chapter(project_id, chapter_key)
    except NoResultFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"章节不存在 project_id={project_id} chapter_key={chapter_key}",
        ) from exc
    deps = build_production_deps(settings, session, project_id)
    try:
        result = await approve_chapter(session, deps, project_id, chapter_key, settings=settings)
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChapterLoopError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return loop_payload(result)


@router.post("/projects/{project_id}/write-batch")
async def write_batch(
    project_id: int,
    body: WriteBatchBody = Body(default_factory=WriteBatchBody),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    payload = body
    deps = build_production_deps(settings, session, project_id)
    try:
        batch = await run_write_batch(
            session,
            deps,
            project_id,
            chapter_count=payload.chapters,
            yes=payload.yes,
            settings=settings,
        )
    except (BatchError, ChapterLoopError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkflowPaused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "project_id": batch.project_id,
        "batch_id": batch.batch_id,
        "results": [loop_payload(item) for item in batch.results],
    }


@router.post("/projects/{project_id}/resume")
async def resume(
    project_id: int,
    body: ResumeBody = Body(default_factory=ResumeBody),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    payload = body
    if payload.chapter_key:
        try:
            planning.get_chapter(project_id, payload.chapter_key)
        except NoResultFound as exc:
            raise HTTPException(
                status_code=404,
                detail=f"章节不存在 project_id={project_id} chapter_key={payload.chapter_key}",
            ) from exc
    deps = build_production_deps(settings, session, project_id)
    try:
        results = await resume_project(
            session,
            deps,
            project_id,
            payload.chapter_key,
            yes=payload.yes,
            settings=settings,
        )
    except ChapterLoopError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkflowPaused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"project_id": project_id, "results": [loop_payload(item) for item in results]}


@router.get("/projects/{project_id}/export")
def export_chapters(
    project_id: int,
    fmt: str = Query(default="md", alias="format"),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    if fmt not in {"txt", "md"}:
        raise HTTPException(status_code=400, detail="format 必须是 txt 或 md")
    text = export_project(session, project_id, fmt)  # type: ignore[arg-type]
    if not isinstance(text, str):
        text = text.read_text(encoding="utf-8")
    media = "text/markdown; charset=utf-8" if fmt == "md" else "text/plain; charset=utf-8"
    return PlainTextResponse(text, media_type=media)
