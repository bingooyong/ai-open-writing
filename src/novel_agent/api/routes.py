"""写作台 HTTP 路由:项目 / bible / graph / 章节。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.engine import Engine
from sqlmodel import Session

from novel_agent.api.deps import get_app_settings, get_session, require_chapter, require_project
from novel_agent.api.schemas import (
    EditOutlineBody,
    LockedRangesBody,
    PlanMoreBody,
    ProjectCreate,
    ProjectPatch,
    ResumeBody,
    RoundConfirm,
    RunVolumeBody,
    WriteBatchBody,
    WriteChapterBody,
    loop_payload,
)
from novel_agent.config import Settings
from novel_agent.domain.models import ProjectRecord
from novel_agent.domain.repos import BibleRepo, CanonRepo, OpsRepo, PlanningRepo
from novel_agent.graph.projector import project_graph
from novel_agent.planning.chain import PlanningAborted, PlanningError, PlanningGates
from novel_agent.planning.conversation import run_bible_conversation
from novel_agent.planning.outline_tree import assemble_outline_tree
from novel_agent.planning.rounds import bible_snapshot, confirm_round, generate_pending_round
from novel_agent.planning.runtime import build_planning_deps
from novel_agent.planning.settings import desk_settings
from novel_agent.planning.volume import PlanMoreError, plan_more
from novel_agent.production.batch import BatchError, resume_project, run_write_batch
from novel_agent.production.export import export_project
from novel_agent.production.loop import ChapterLoopError, ChapterLoopGates, run_chapter_loop
from novel_agent.production.outline import (
    OutlineEditError,
    apply_outline_edit,
    dump_outline_yaml,
    export_outline_bundle,
)
from novel_agent.production.review import (
    ReviewError,
    approve_chapter,
    list_review_desk,
    mark_locked_ranges,
    reject_chapter,
)
from novel_agent.production.runtime import build_production_deps
from novel_agent.production.volume_run import (
    KIND,
    idle_volume_status,
    run_volume,
    status_from_run,
    volume_is_active,
)
from novel_agent.workflow.errors import WorkflowPaused

router = APIRouter()


def _project_out(rec: ProjectRecord, completed: list[str] | None = None) -> dict[str, object]:
    flags = desk_settings(rec)
    return {
        "id": rec.id,
        "title": rec.title,
        "genre": rec.genre,
        "status": rec.status,
        "spark": rec.spark,
        "brief": rec.brief,
        "completed_rounds": completed or [],
        "enable_writer_b": flags["enable_writer_b"],
        "enable_reader_advocate": flags["enable_reader_advocate"],
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
                skip_concept_judge=body.skip_concept_judge,
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
        project_id,
        title=body.title,
        genre=body.genre,
        spark=body.spark,
        enable_writer_b=body.enable_writer_b,
        enable_reader_advocate=body.enable_reader_advocate,
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
    skip_concept_judge: bool = Query(default=False),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    rec = require_project(planning, project_id)
    deps = build_planning_deps(settings, session, project_id)
    try:
        return await generate_pending_round(
            session,
            deps,
            project_id,
            rec.spark or rec.brief,
            round_index=round_index,
            skip_concept_judge=skip_concept_judge,
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
    skip_concept_judge: bool = Query(default=False),
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
            skip_concept_judge=skip_concept_judge,
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


@router.get("/projects/{project_id}/outline-tree")
def get_outline_tree(
    project_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    return assemble_outline_tree(planning, project_id)


@router.post("/projects/{project_id}/plan-more")
async def plan_more_endpoint(
    project_id: int,
    body: PlanMoreBody = Body(default_factory=PlanMoreBody),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    deps = build_planning_deps(settings, session, project_id)
    try:
        result = await plan_more(
            planning,
            BibleRepo(session),
            CanonRepo(session),
            deps,
            project_id,
            PlanningGates.auto(),
            window=body.window or settings.rolling_window,
            chapters=body.chapters,
            open_volume=body.open_volume,
        )
    except PlanningAborted as exc:
        raise _planning_http(exc) from exc
    except (PlanMoreError, PlanningError) as exc:
        raise _planning_http(exc) from exc
    return {
        "project_id": result.project_id,
        "volume_id": result.volume_id,
        "unit_id": result.unit_id,
        "chapter_keys": result.chapter_keys,
        "opened_new_volume": result.opened_new_volume,
        "skipped": result.skipped,
        "outline_tree": assemble_outline_tree(planning, project_id),
    }


@router.get("/projects/{project_id}/chapters/{chapter_key}/outline.yaml")
def get_outline_yaml(
    project_id: int, chapter_key: str, session: Session = Depends(get_session)
) -> PlainTextResponse:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    require_chapter(planning, project_id, chapter_key)
    text = dump_outline_yaml(export_outline_bundle(planning, project_id, chapter_key))
    return PlainTextResponse(text, media_type="application/yaml; charset=utf-8")


@router.post("/projects/{project_id}/chapters/{chapter_key}/edit-outline")
def edit_outline(
    project_id: int,
    chapter_key: str,
    body: EditOutlineBody,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    require_chapter(planning, project_id, chapter_key)
    if not body.yaml.strip():
        raise HTTPException(status_code=400, detail="yaml 不能为空")
    try:
        version = apply_outline_edit(session, project_id, chapter_key, body.yaml)
    except OutlineEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chapter = planning.get_chapter(project_id, chapter_key)
    return {
        "chapter_key": chapter_key,
        "outline_version": version,
        "status": chapter.status.value,
        "title": chapter.title,
    }


@router.get("/projects/{project_id}/review")
def get_review(
    project_id: int, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    require_project(PlanningRepo(session), project_id)
    return list_review_desk(session, project_id)


@router.post("/projects/{project_id}/chapters/{chapter_key}/reject")
def reject(
    project_id: int, chapter_key: str, session: Session = Depends(get_session)
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    require_chapter(planning, project_id, chapter_key)
    try:
        stale = reject_chapter(session, project_id, chapter_key)
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    chapter = planning.get_chapter(project_id, chapter_key)
    return {
        "chapter_key": chapter_key,
        "status": chapter.status.value,
        "stale": stale,
    }


@router.post("/projects/{project_id}/chapters/{chapter_key}/locked-ranges")
def lock_ranges(
    project_id: int,
    chapter_key: str,
    body: LockedRangesBody,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    require_chapter(planning, project_id, chapter_key)
    try:
        mark_locked_ranges(session, project_id, chapter_key, body.ranges)
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"chapter_key": chapter_key, "locked_ranges": body.ranges}


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
    require_chapter(planning, project_id, chapter_key)
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
    require_chapter(planning, project_id, chapter_key)
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
            from_chapter=payload.from_chapter,
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
        require_chapter(planning, project_id, payload.chapter_key)
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


async def _run_volume_job(
    engine: Engine,
    settings: Settings,
    project_id: int,
    run_id: int,
    budget_usd: float,
    max_chapters: int | None,
    open_volume: bool,
    yes: bool,
) -> None:
    with Session(engine) as session:
        try:
            deps = build_production_deps(settings, session, project_id)
            await run_volume(
                session,
                deps,
                project_id,
                budget_usd=budget_usd,
                yes=yes,
                max_chapters=max_chapters,
                open_volume=open_volume,
                settings=settings,
                run_id=run_id,
            )
            session.commit()
        except Exception:
            session.rollback()
            with Session(engine) as fail:
                try:
                    OpsRepo(fail).update_workflow(run_id, status="failed")
                    fail.commit()
                except Exception:
                    fail.rollback()
            raise


@router.post("/projects/{project_id}/run-volume")
async def start_run_volume(
    project_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    body: RunVolumeBody,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    planning = PlanningRepo(session)
    require_project(planning, project_id)
    if body.budget_usd <= 0:
        raise HTTPException(status_code=400, detail="budget_usd 必须是正数")
    if volume_is_active(project_id):
        raise HTTPException(status_code=409, detail="卷长跑已在进行")
    ops = OpsRepo(session)
    run = ops.find_resumable_run(project_id, KIND) or ops.create_workflow_run(
        project_id, KIND
    )
    assert run.id is not None
    session.commit()
    engine = request.app.state.engine
    if not isinstance(engine, Engine):
        raise HTTPException(status_code=500, detail="应用未注入数据库引擎")
    background_tasks.add_task(
        _run_volume_job,
        engine,
        settings,
        project_id,
        run.id,
        body.budget_usd,
        body.max_chapters,
        body.open_volume,
        body.yes,
    )
    return status_from_run(project_id, run)


@router.get("/projects/{project_id}/run-volume")
def get_run_volume(
    project_id: int, session: Session = Depends(get_session)
) -> dict[str, object]:
    require_project(PlanningRepo(session), project_id)
    run = OpsRepo(session).latest_workflow(project_id, KIND)
    if run is None:
        return idle_volume_status(project_id)
    return status_from_run(project_id, run)


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
