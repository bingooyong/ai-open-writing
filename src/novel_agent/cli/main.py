"""novel 命令行入口(阶段0:Typer)。

命令面随里程碑逐步填充:
  Story Bible  init / bible / graph
  M3.2         plan (规划链子程序)
  M3.3         write-chapter / smoke-chapter
  M3.3b        edit-outline
  M3.4         review-batch / approve
  M3.5         write-batch / resume / export
  渠道导出      export --channel qidian|fanqie|generic|epub
  卷工厂        plan-more
  长跑          run-volume
  Stage 2      retrieve / retrieve-eval
  M4           smoke-stage0
  Stage 1      serve
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy.orm.exc import NoResultFound
from sqlmodel import Session

from novel_agent import __version__
from novel_agent.config import get_settings
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import StoryKernel
from novel_agent.eval.retrieval import (
    default_golden_path,
    format_report,
    run_eval_on_temp_db,
)
from novel_agent.graph.export import to_json, to_mermaid
from novel_agent.graph.projector import project_graph
from novel_agent.memory.embeddings import HashEmbedding, build_embedder
from novel_agent.memory.factory import memory_retrieval_for_session
from novel_agent.planning.chain import (
    PlanningAborted,
    PlanningError,
    PlanningGates,
    PlanningResult,
    run_planning_chain,
)
from novel_agent.planning.conversation import BibleResult, run_bible_conversation
from novel_agent.planning.runtime import build_planning_deps
from novel_agent.planning.volume import (
    DEFAULT_WINDOW,
    PlanMoreError,
    PlanMoreResult,
    plan_more,
)
from novel_agent.production.batch import BatchError, resume_project, run_write_batch
from novel_agent.production.export import ExportSpecError, export_project, resolve_channel_format
from novel_agent.production.loop import ChapterLoopError, ChapterLoopGates, run_chapter_loop
from novel_agent.production.outline import (
    OutlineEditError,
    apply_outline_edit,
    dump_outline_yaml,
    export_outline_bundle,
)
from novel_agent.production.review import (
    ReviewError,
    ReviewItem,
    approve_chapter,
    list_review_queue,
    mark_locked_ranges,
    reject_chapter,
)
from novel_agent.production.runtime import build_production_deps
from novel_agent.production.volume_run import VolumeBusyError, VolumeRunError, run_volume
from novel_agent.runtime.agents import AgentDeps
from novel_agent.verification.m26_smoke import (
    SmokeExecutionError,
    SmokeGateError,
    run_m26_smoke,
)
from novel_agent.verification.m33_smoke import run_m33_smoke
from novel_agent.verification.stage0_smoke import run_stage0_smoke
from novel_agent.workflow.errors import WorkflowPaused

app = typer.Typer(help="本地优先的 AI 长篇小说创作智能体(阶段0)", no_args_is_help=True)


@app.command()
def version() -> None:
    """显示版本。"""
    typer.echo(f"novel-agent {__version__}")


@app.command()
def doctor() -> None:
    """检查环境与配置(模型槽位、数据库路径)。"""
    s = get_settings()
    typer.echo(f"db_path: {s.db_path}")
    typer.echo(f"api_url: http://{s.api_host}:{s.api_port}")
    typer.echo(f"desk_url: http://127.0.0.1:{s.web_port}")
    for name in ("creative", "review", "judge", "extract"):
        slot = getattr(s, name)
        typer.echo(
            f"{name:8s} provider={slot.provider:12s} model={slot.model} family={slot.family}"
        )
    typer.echo(
        f"embedding provider={s.embedding.provider:12s} model={s.embedding.model}"
    )
    typer.echo(
        f"预算: 单章最大调用 {s.max_calls_per_chapter} 次;"
        f"修订轮次上限 {s.max_revision_rounds}(固定)"
    )


@app.command()
def serve(
    host: Annotated[str | None, typer.Option("--host", help="绑定地址,默认 127.0.0.1")] = None,
    port: Annotated[int | None, typer.Option("--port", help="API 端口,默认 8765")] = None,
) -> None:
    """启动本地写作台 API(FastAPI/uvicorn)。前端 Vite 固定 18765,不要用 5173。"""
    import uvicorn

    s = get_settings()
    bind_host = host or s.api_host
    bind_port = port or s.api_port
    typer.echo(f"api_url: http://{bind_host}:{bind_port}")
    typer.echo(f"desk_url: http://127.0.0.1:{s.web_port}")
    uvicorn.run(
        "novel_agent.api.app:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
    )


@app.command("smoke-m26")
def smoke_m26(
    confirm_real_models: Annotated[
        bool,
        typer.Option(
            "--confirm-real-models",
            help="显式确认本命令将调用并计费真实模型",
        ),
    ] = False,
    budget_usd: Annotated[
        float | None,
        typer.Option("--budget-usd", help="本次运行不可超过的 USD 硬上限"),
    ] = None,
    report: Annotated[
        Path | None, typer.Option("--report", help="脱敏 JSON 证据报告路径")
    ] = None,
) -> None:
    """M2.6 受限真实模型冒烟;默认拒绝执行。"""
    if not confirm_real_models:
        typer.echo("拒绝: 缺少 --confirm-real-models", err=True)
        raise typer.Exit(2)
    if budget_usd is None or budget_usd <= 0:
        typer.echo("拒绝: --budget-usd 必须是正数", err=True)
        raise typer.Exit(2)

    try:
        path = asyncio.run(
            run_m26_smoke(get_settings(), budget_usd=budget_usd, report_path=report)
        )
    except SmokeGateError as exc:
        typer.echo(f"拒绝: {exc}", err=True)
        raise typer.Exit(2) from None
    except ValidationError:
        typer.echo("拒绝: 模型槽位配置无效（详情已脱敏）", err=True)
        raise typer.Exit(2) from None
    except SmokeExecutionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"M2.6 smoke passed; redacted report: {path}")


def _require_yes_or_tty(yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        typer.echo("拒绝: 非交互环境请使用 --yes", err=True)
        raise typer.Exit(2)


def _cli_gates(yes: bool, select: int) -> PlanningGates:
    if yes:
        return PlanningGates.auto(select_index=select - 1)

    def select_kernel(candidates: list[StoryKernel]) -> int:
        typer.echo("内核候选:")
        for i, kernel in enumerate(candidates, start=1):
            typer.echo(f"  [{i}] {kernel.logline}")
        chosen = typer.prompt("选定内核候选编号", type=int)
        return int(chosen) - 1

    def confirm(prompt: str) -> bool:
        return bool(typer.confirm(prompt, default=False))

    return PlanningGates(select_kernel=select_kernel, confirm=confirm)


def _echo_planning_result(result: PlanningResult | BibleResult | PlanMoreResult) -> None:
    typer.echo(f"project_id={result.project_id}")
    typer.echo(f"volume={result.volume_id}")
    typer.echo(f"unit={result.unit_id}")
    typer.echo(f"chapters={','.join(result.chapter_keys)}")
    if result.skipped:
        typer.echo(f"skipped={','.join(result.skipped)}")
    if isinstance(result, PlanMoreResult):
        typer.echo(f"opened_new_volume={str(result.opened_new_volume).lower()}")
        return
    typer.echo(f"kernel_version={result.kernel_version}")
    typer.echo(f"characters={','.join(result.character_ids)}")


def _text_from_stored_brief(stored: str, spark: str) -> str:
    if spark.strip():
        return spark.strip()
    try:
        payload = json.loads(stored)
    except json.JSONDecodeError:
        return stored
    if isinstance(payload, dict) and str(payload.get("spark", "")).strip():
        return str(payload["spark"]).strip()
    return stored


def _store_brief(repo: PlanningRepo, project_id: int, brief: str) -> None:
    project = repo.get_project(project_id)
    text = brief.strip()
    project.brief = text
    if not (project.spark or "").strip():
        project.spark = text
    repo.s.add(project)


def _resolve_brief(repo: PlanningRepo, project_id: int, brief: str) -> str:
    if brief.strip():
        return brief.strip()
    project = repo.get_project(project_id)
    stored = (project.brief or "").strip()
    if stored:
        return _text_from_stored_brief(stored, project.spark or "")
    spark = (project.spark or "").strip()
    if spark:
        return spark
    legacy = (project.channel_profile or {}).get("brief", "")
    if not isinstance(legacy, str) or not legacy.strip():
        typer.echo("拒绝: 请提供 --brief(项目尚未保存创作简报)", err=True)
        raise typer.Exit(2)
    migrated = legacy.strip()
    project.brief = migrated
    if not (project.spark or "").strip():
        project.spark = migrated
    repo.s.add(project)
    return migrated


async def _run_bible(
    session: Session,
    deps: AgentDeps,
    spark: str,
    yes: bool,
    select: int,
    volume_id: str,
    chapters: int,
    skip_concept_judge: bool = False,
) -> BibleResult:
    planning = PlanningRepo(session)
    try:
        return await run_bible_conversation(
            planning,
            BibleRepo(session),
            CanonRepo(session),
            deps,
            spark,
            _cli_gates(yes, select),
            volume_id=volume_id,
            chapters_needed=chapters,
            skip_concept_judge=skip_concept_judge,
        )
    except PlanningAborted as exc:
        typer.echo(f"已中止规划阶段 {exc.stage};project_id={exc.project_id}", err=True)
        raise typer.Exit(1) from None
    except PlanningError as exc:
        typer.echo(f"规划失败: {exc}", err=True)
        raise typer.Exit(1) from None


async def _run_chain(
    session: Session,
    deps: AgentDeps,
    brief: str,
    yes: bool,
    select: int,
    volume_id: str,
    chapters: int,
) -> PlanningResult:
    repo = PlanningRepo(session)
    try:
        return await run_planning_chain(
            repo,
            deps,
            brief,
            _cli_gates(yes, select),
            volume_id=volume_id,
            chapters_needed=chapters,
        )
    except PlanningAborted as exc:
        typer.echo(f"已中止规划阶段 {exc.stage};project_id={exc.project_id}", err=True)
        raise typer.Exit(1) from None
    except PlanningError as exc:
        typer.echo(f"规划失败: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def init(
    title: Annotated[str, typer.Argument(help="作品标题")],
    brief: Annotated[str, typer.Option("--brief", help="创作简报(题材/受众/禁写项)")],
    genre: Annotated[str, typer.Option("--genre", help="类型标签")] = "",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="非交互:选定内核并确认后续阶段")] = False,
    select: Annotated[int, typer.Option("--select", help="非交互时选定的内核候选编号(从1起)")] = 1,
    chapters: Annotated[int, typer.Option("--chapters", help="滚动章纲数量")] = 5,
    volume_id: Annotated[str, typer.Option("--volume-id", help="卷业务键")] = "v1",
    skip_concept_judge: Annotated[
        bool,
        typer.Option("--skip-concept-judge", help="跳过规划对抗(Concept Judge),加快 CI"),
    ] = False,
) -> None:
    """新建项目并跑 Story Bible 对话(R0–R5)。"""
    _require_yes_or_tty(yes)
    if select < 1:
        typer.echo("拒绝: --select 必须 >= 1", err=True)
        raise typer.Exit(2)

    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project(title, genre=genre)
        project_id = project.id
        if project_id is None:
            typer.echo("拒绝: 项目写入失败", err=True)
            raise typer.Exit(1)
        _store_brief(repo, project_id, brief)
        session.commit()
        deps = build_planning_deps(settings, session, project_id)
        result = asyncio.run(
            _run_bible(
                session, deps, brief, yes, select, volume_id, chapters, skip_concept_judge
            )
        )
        session.commit()
    _echo_planning_result(result)


@app.command()
def plan(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    brief: Annotated[str, typer.Option("--brief", help="创作简报;缺省则读项目已存简报")] = "",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="非交互:选定内核并确认后续阶段")] = False,
    select: Annotated[int, typer.Option("--select", help="非交互时选定的内核候选编号(从1起)")] = 1,
    chapters: Annotated[int, typer.Option("--chapters", help="滚动章纲数量")] = 5,
    volume_id: Annotated[str, typer.Option("--volume-id", help="卷业务键")] = "v1",
) -> None:
    """对已有项目续跑规划链;已入库阶段会跳过。"""
    _require_yes_or_tty(yes)
    if select < 1:
        typer.echo("拒绝: --select 必须 >= 1", err=True)
        raise typer.Exit(2)

    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        resolved = _resolve_brief(repo, project_id, brief)
        if brief.strip():
            _store_brief(repo, project_id, resolved)
            session.commit()
        deps = build_planning_deps(settings, session, project_id)
        result = asyncio.run(
            _run_chain(session, deps, resolved, yes, select, volume_id, chapters)
        )
        session.commit()
    _echo_planning_result(result)


@app.command("plan-more")
def plan_more_cmd(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    window: Annotated[
        int, typer.Option("--window", help="保持的已规划未锁定章数")
    ] = DEFAULT_WINDOW,
    chapters: Annotated[
        int | None, typer.Option("--chapters", help="本次生成章数;缺省则补满窗口")
    ] = None,
    open_volume: Annotated[
        bool, typer.Option("--open-volume", help="开下一卷(v2…)而不是续写当前卷")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="非交互确认写入")] = False,
) -> None:
    """滚动窗口缩小时续规划下一截章纲/场景卡;单元已锁定或 --open-volume 时开新卷。"""
    _require_yes_or_tty(yes)
    if window < 1:
        typer.echo("拒绝: --window 必须 >= 1", err=True)
        raise typer.Exit(2)
    if chapters is not None and chapters < 1:
        typer.echo("拒绝: --chapters 必须 >= 1", err=True)
        raise typer.Exit(2)

    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        deps = build_planning_deps(settings, session, project_id)
        try:
            result = asyncio.run(
                plan_more(
                    repo,
                    BibleRepo(session),
                    CanonRepo(session),
                    deps,
                    project_id,
                    _cli_gates(yes, 1),
                    window=window or settings.rolling_window,
                    chapters=chapters,
                    open_volume=True if open_volume else None,
                )
            )
        except PlanningAborted as exc:
            typer.echo(f"已中止规划阶段 {exc.stage};project_id={exc.project_id}", err=True)
            raise typer.Exit(1) from None
        except (PlanMoreError, PlanningError) as exc:
            typer.echo(f"续规划失败: {exc}", err=True)
            raise typer.Exit(1) from None
        session.commit()
    _echo_planning_result(result)


@app.command()
def bible(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    brief: Annotated[
        str, typer.Option("--brief", help="火花/简报;缺省则读项目已存 spark/brief")
    ] = "",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="非交互:选定内核并确认后续轮次")] = False,
    select: Annotated[int, typer.Option("--select", help="非交互时选定的内核候选编号(从1起)")] = 1,
    chapters: Annotated[int, typer.Option("--chapters", help="滚动章纲数量")] = 5,
    volume_id: Annotated[str, typer.Option("--volume-id", help="卷业务键")] = "v1",
    skip_concept_judge: Annotated[
        bool,
        typer.Option("--skip-concept-judge", help="跳过规划对抗(Concept Judge),加快 CI"),
    ] = False,
) -> None:
    """对已有项目续跑 Story Bible 对话;已完成轮次会跳过。"""
    _require_yes_or_tty(yes)
    if select < 1:
        typer.echo("拒绝: --select 必须 >= 1", err=True)
        raise typer.Exit(2)

    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        resolved = _resolve_brief(repo, project_id, brief)
        if brief.strip():
            _store_brief(repo, project_id, resolved)
            session.commit()
        deps = build_planning_deps(settings, session, project_id)
        result = asyncio.run(
            _run_bible(
                session, deps, resolved, yes, select, volume_id, chapters, skip_concept_judge
            )
        )
        session.commit()
    _echo_planning_result(result)


@app.command()
def graph(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    fmt: Annotated[
        str, typer.Option("--format", help="json 或 mermaid")
    ] = "json",
) -> None:
    """导出关系图投影(正史视图,不调用模型)。"""
    if fmt not in {"json", "mermaid"}:
        typer.echo("拒绝: --format 必须是 json 或 mermaid", err=True)
        raise typer.Exit(2)
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        projection = project_graph(
            project_id, repo, BibleRepo(session), CanonRepo(session)
        )
    if fmt == "json":
        typer.echo(to_json(projection))
    else:
        typer.echo(to_mermaid(projection))


@app.command("write-chapter")
def write_chapter(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    chapter_key: Annotated[str, typer.Option("--chapter-key", help="章节业务键,如 v1c001")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="PASS 后自动批准并提交正史")] = False,
) -> None:
    """对已规划章节跑 N1→N9 单章循环;默认在 HUMAN_REVIEW 停下。"""
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
            repo.get_chapter(project_id, chapter_key)
        except NoResultFound:
            typer.echo(
                f"拒绝: 项目或章节不存在 project_id={project_id} chapter_key={chapter_key}",
                err=True,
            )
            raise typer.Exit(2) from None
        if yes:
            gates = ChapterLoopGates.auto()
        elif sys.stdin.isatty():
            gates = ChapterLoopGates(
                approve=lambda _preview: bool(typer.confirm("批准本章并提交正史?", default=False))
            )
        else:
            gates = ChapterLoopGates.hold()
        deps = build_production_deps(settings, session, project_id)
        try:
            result = asyncio.run(
                run_chapter_loop(
                    session,
                    deps,
                    project_id,
                    chapter_key,
                    gates=gates,
                    settings=settings,
                )
            )
        except ChapterLoopError as exc:
            typer.echo(f"单章循环失败: {exc}", err=True)
            raise typer.Exit(1) from None
        except WorkflowPaused as exc:
            typer.echo(f"工作流暂停: {exc}", err=True)
            raise typer.Exit(1) from None
        session.commit()
    typer.echo(f"project_id={result.project_id}")
    typer.echo(f"chapter_key={result.chapter_key}")
    typer.echo(f"status={result.status.value}")
    typer.echo(f"verdict={result.verdict.value if result.verdict else ''}")
    typer.echo(f"revision_round={result.revision_round}")
    typer.echo(f"stopped_at={result.stopped_at}")


@app.command("smoke-chapter")
def smoke_chapter(
    confirm_real_models: Annotated[
        bool,
        typer.Option(
            "--confirm-real-models",
            help="显式确认本命令将调用并计费真实模型",
        ),
    ] = False,
    budget_usd: Annotated[
        float | None,
        typer.Option("--budget-usd", help="本次运行不可超过的 USD 硬上限"),
    ] = None,
    report: Annotated[
        Path | None, typer.Option("--report", help="脱敏 JSON 证据报告路径")
    ] = None,
) -> None:
    """M3.3 受限真实模型单章冒烟;默认拒绝执行。"""
    if not confirm_real_models:
        typer.echo("拒绝: 缺少 --confirm-real-models", err=True)
        raise typer.Exit(2)
    if budget_usd is None or budget_usd <= 0:
        typer.echo("拒绝: --budget-usd 必须是正数", err=True)
        raise typer.Exit(2)

    try:
        path = asyncio.run(
            run_m33_smoke(get_settings(), budget_usd=budget_usd, report_path=report)
        )
    except SmokeGateError as exc:
        typer.echo(f"拒绝: {exc}", err=True)
        raise typer.Exit(2) from None
    except ValidationError:
        typer.echo("拒绝: 模型槽位配置无效（详情已脱敏）", err=True)
        raise typer.Exit(2) from None
    except SmokeExecutionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"M3.3 chapter smoke finished; redacted report: {path}")


@app.command("smoke-stage0")
def smoke_stage0(
    confirm_real_models: Annotated[
        bool,
        typer.Option(
            "--confirm-real-models",
            help="显式确认本命令将调用并计费真实模型",
        ),
    ] = False,
    budget_usd: Annotated[
        float | None,
        typer.Option("--budget-usd", help="本次运行不可超过的 USD 硬上限"),
    ] = None,
    report: Annotated[
        Path | None, typer.Option("--report", help="脱敏 JSON 证据报告路径")
    ] = None,
) -> None:
    """受限真实模型三章冒烟;默认拒绝,不进默认 CI。

    必须同时提供 --confirm-real-models 与正数 --budget-usd。
    四槽位任一为 mock 则拒绝(视为跳过付费冒烟)。
    judge.family 必须不同于 creative.family。
    保守预检按当前工厂首轮计价,必须落入 --budget-usd。
    """
    if not confirm_real_models:
        typer.echo("拒绝: 缺少 --confirm-real-models", err=True)
        raise typer.Exit(2)
    if budget_usd is None or budget_usd <= 0:
        typer.echo("拒绝: --budget-usd 必须是正数", err=True)
        raise typer.Exit(2)

    try:
        path = asyncio.run(
            run_stage0_smoke(get_settings(), budget_usd=budget_usd, report_path=report)
        )
    except SmokeGateError as exc:
        typer.echo(f"拒绝: {exc}", err=True)
        raise typer.Exit(2) from None
    except ValidationError:
        typer.echo("拒绝: 模型槽位配置无效（详情已脱敏）", err=True)
        raise typer.Exit(2) from None
    except SmokeExecutionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"M4.2 stage0 smoke finished; redacted report: {path}")


def _resolve_chapter_key(chapter: str | None, chapter_key: str) -> str:
    key = (chapter or chapter_key).strip()
    if not key:
        typer.echo("拒绝: 请提供章节参数或 --chapter-key", err=True)
        raise typer.Exit(2)
    if chapter and chapter_key and chapter != chapter_key:
        typer.echo("拒绝: 位置参数与 --chapter-key 不一致", err=True)
        raise typer.Exit(2)
    return key


@app.command("edit-outline")
def edit_outline(
    chapter: Annotated[str | None, typer.Argument(help="章节业务键,如 v1c001")] = None,
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")] = 0,
    chapter_key: Annotated[str, typer.Option("--chapter-key", help="章节业务键")] = "",
    from_file: Annotated[
        Path | None, typer.Option("--from-file", help="导入已编辑的 YAML")
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", help="导出 YAML 路径")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="非交互确认导入")] = False,
) -> None:
    """导出/导入章纲与场景卡;导入后 bump outline_ver 并回到 N1。"""
    if project_id <= 0:
        typer.echo("拒绝: 请提供 --project-id", err=True)
        raise typer.Exit(2)
    key = _resolve_chapter_key(chapter, chapter_key)
    if from_file is None and out is None:
        _require_yes_or_tty(yes)

    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
            repo.get_chapter(project_id, key)
        except NoResultFound:
            typer.echo(
                f"拒绝: 项目或章节不存在 project_id={project_id} chapter_key={key}",
                err=True,
            )
            raise typer.Exit(2) from None
        bundle = export_outline_bundle(repo, project_id, key)
        yaml_text = dump_outline_yaml(bundle)
        if from_file is None:
            target = out or Path(f"{key}.outline.yaml")
            target.write_text(yaml_text, encoding="utf-8")
            session.commit()
            typer.echo(f"exported={target}")
            typer.echo(f"outline_ver={repo.get_chapter(project_id, key).outline_version}")
            return
        _require_yes_or_tty(yes)
        try:
            text = from_file.read_text(encoding="utf-8")
            new_ver = apply_outline_edit(session, project_id, key, text)
        except (OSError, OutlineEditError) as exc:
            typer.echo(f"拒绝: {exc}", err=True)
            raise typer.Exit(2) from None
        session.commit()
    typer.echo(f"project_id={project_id}")
    typer.echo(f"chapter_key={key}")
    typer.echo(f"outline_ver={new_ver}")
    typer.echo("status=PLANNED")


def _echo_review_item(item: ReviewItem) -> None:
    verdict = item.verdict.value if item.verdict else ""
    typer.echo(f"chapter_key={item.chapter_key} status={item.status.value} verdict={verdict}")
    preview = item.draft_text.replace("\n", " ")[:400]
    typer.echo(f"draft={preview}")
    for issue in item.issues:
        typer.echo(f"issue={issue.issue_id} severity={issue.severity.value} {issue.claim}")


@app.command("review-batch")
def review_batch(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    chapter_key: Annotated[str, typer.Option("--chapter-key", help="只处理指定章节")] = "",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="非交互:自动批准 PASS 待审章")] = False,
    reject: Annotated[bool, typer.Option("--reject", help="退回重规划(进入 edit-outline)")] = False,
    lock_range: Annotated[
        list[str] | None,
        typer.Option("--lock-range", help="段落指令重写标记,写入 locked_ranges"),
    ] = None,
) -> None:
    """列出 HUMAN_REVIEW 待审章;可批准、退回或标记锁定段落。"""
    _require_yes_or_tty(yes)
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        queue = list_review_queue(session, project_id)
        if chapter_key:
            queue = [item for item in queue if item.chapter_key == chapter_key]
        if not queue:
            typer.echo("待审章节: (无)")
            session.commit()
            return
        for item in queue:
            _echo_review_item(item)
        ranges = lock_range or []
        try:
            if reject:
                if not chapter_key:
                    typer.echo("拒绝: --reject 需要 --chapter-key", err=True)
                    raise typer.Exit(2)
                stale = reject_chapter(session, project_id, chapter_key)
                session.commit()
                typer.echo(f"rejected={chapter_key}")
                if stale:
                    typer.echo(f"stale={','.join(stale)}")
                return
            if ranges:
                if not chapter_key:
                    typer.echo("拒绝: --lock-range 需要 --chapter-key", err=True)
                    raise typer.Exit(2)
                mark_locked_ranges(session, project_id, chapter_key, ranges)
                session.commit()
                typer.echo(f"locked_ranges={chapter_key}")
                return
            deps = build_production_deps(settings, session, project_id)
            for item in queue:
                result = asyncio.run(
                    approve_chapter(session, deps, project_id, item.chapter_key)
                )
                typer.echo(f"approved={result.chapter_key} status={result.status.value}")
            session.commit()
        except ReviewError as exc:
            typer.echo(f"拒绝: {exc}", err=True)
            raise typer.Exit(1) from None


@app.command()
def approve(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    chapter_key: Annotated[str, typer.Option("--chapter-key", help="章节业务键")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="非交互确认批准并提交正史")] = False,
) -> None:
    """批准 HUMAN_REVIEW 章节,触发 CanonWriter 提交。"""
    _require_yes_or_tty(yes)
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
            repo.get_chapter(project_id, chapter_key)
        except NoResultFound:
            typer.echo(
                f"拒绝: 项目或章节不存在 project_id={project_id} chapter_key={chapter_key}",
                err=True,
            )
            raise typer.Exit(2) from None
        deps = build_production_deps(settings, session, project_id)
        try:
            result = asyncio.run(approve_chapter(session, deps, project_id, chapter_key))
        except ReviewError as exc:
            typer.echo(f"拒绝: {exc}", err=True)
            raise typer.Exit(1) from None
        except ChapterLoopError as exc:
            typer.echo(f"单章循环失败: {exc}", err=True)
            raise typer.Exit(1) from None
        session.commit()
    typer.echo(f"project_id={result.project_id}")
    typer.echo(f"chapter_key={result.chapter_key}")
    typer.echo(f"status={result.status.value}")


@app.command("write-batch")
def write_batch(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    chapters: Annotated[int, typer.Option("--chapters", help="连跑章数(3~5)")] = 3,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="PASS 后自动批准并提交正史")] = False,
    from_chapter: Annotated[
        str, typer.Option("--from-chapter", help="从指定章起写;缺省则跳过已锁定章")
    ] = "",
) -> None:
    """3~5 章顺序连跑;后章可读前章 provisional canon overlay(D15)。"""
    if chapters < 3 or chapters > 5:
        typer.echo("拒绝: --chapters 必须是 3~5", err=True)
        raise typer.Exit(2)
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        deps = build_production_deps(settings, session, project_id)
        try:
            batch = asyncio.run(
                run_write_batch(
                    session,
                    deps,
                    project_id,
                    chapter_count=chapters,
                    yes=yes,
                    settings=settings,
                    from_chapter=from_chapter or None,
                )
            )
        except (BatchError, ChapterLoopError) as exc:
            typer.echo(f"批次连跑失败: {exc}", err=True)
            raise typer.Exit(1) from None
        except WorkflowPaused as exc:
            typer.echo(f"工作流暂停: {exc}", err=True)
            raise typer.Exit(1) from None
        session.commit()
    for item in batch.results:
        typer.echo(
            f"chapter_key={item.chapter_key} status={item.status.value} "
            f"stopped_at={item.stopped_at}"
        )


@app.command("run-volume")
def run_volume_cmd(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="PASS 后自动批准并提交正史")] = False,
    budget_usd: Annotated[
        float | None,
        typer.Option("--budget-usd", help="本次运行不可超过的 USD 硬上限"),
    ] = None,
    max_chapters: Annotated[
        int | None, typer.Option("--max-chapters", help="本次最多新锁定章数")
    ] = None,
    open_volume: Annotated[
        bool, typer.Option("--open-volume", help="窗口续规划时开下一卷")
    ] = False,
) -> None:
    """无人值守卷长跑:窗口不足则 plan-more,再写未锁定章;遇预算/人工门禁停下。"""
    _require_yes_or_tty(yes)
    if budget_usd is None or budget_usd <= 0:
        typer.echo("拒绝: --budget-usd 必须是正数", err=True)
        raise typer.Exit(2)
    if max_chapters is not None and max_chapters < 1:
        typer.echo("拒绝: --max-chapters 必须 >= 1", err=True)
        raise typer.Exit(2)

    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        deps = build_production_deps(settings, session, project_id)
        try:
            result = asyncio.run(
                run_volume(
                    session,
                    deps,
                    project_id,
                    budget_usd=budget_usd,
                    yes=yes,
                    max_chapters=max_chapters,
                    open_volume=open_volume,
                    settings=settings,
                )
            )
        except VolumeBusyError as exc:
            typer.echo(f"拒绝: {exc}", err=True)
            raise typer.Exit(2) from None
        except VolumeRunError as exc:
            typer.echo(f"长跑失败: {exc}", err=True)
            raise typer.Exit(1) from None
        except (ChapterLoopError, BatchError) as exc:
            typer.echo(f"长跑失败: {exc}", err=True)
            raise typer.Exit(1) from None
        except WorkflowPaused as exc:
            typer.echo(f"工作流暂停: {exc}", err=True)
            raise typer.Exit(1) from None
        session.commit()
    typer.echo(f"project_id={result.project_id}")
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"chapters_done={result.chapters_done}")
    typer.echo(f"spent_usd={result.spent_usd}")
    typer.echo(f"stop_reason={result.stop_reason}")
    for item in result.results:
        typer.echo(
            f"chapter_key={item.chapter_key} status={item.status.value} "
            f"stopped_at={item.stopped_at}"
        )


@app.command()
def resume(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    chapter_key: Annotated[str, typer.Option("--chapter-key", help="只恢复指定章节")] = "",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="PASS 后自动批准并提交正史")] = False,
) -> None:
    """从最后 SUCCESS 节点续跑未完成章节。"""
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
            if chapter_key:
                repo.get_chapter(project_id, chapter_key)
        except NoResultFound:
            typer.echo(
                f"拒绝: 项目或章节不存在 project_id={project_id} chapter_key={chapter_key}",
                err=True,
            )
            raise typer.Exit(2) from None
        deps = build_production_deps(settings, session, project_id)
        try:
            results = asyncio.run(
                resume_project(
                    session,
                    deps,
                    project_id,
                    chapter_key or None,
                    yes=yes,
                    settings=settings,
                )
            )
        except ChapterLoopError as exc:
            typer.echo(f"恢复失败: {exc}", err=True)
            raise typer.Exit(1) from None
        except WorkflowPaused as exc:
            typer.echo(f"工作流暂停: {exc}", err=True)
            raise typer.Exit(1) from None
        session.commit()
    if not results:
        typer.echo("resume: 无未完成章节")
        return
    for item in results:
        typer.echo(
            f"chapter_key={item.chapter_key} status={item.status.value} "
            f"stopped_at={item.stopped_at}"
        )


@app.command()
def export(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    fmt: Annotated[str, typer.Option("--format", help="txt、md 或 epub")] = "md",
    channel: Annotated[
        str, typer.Option("--channel", help="generic / qidian / fanqie / epub")
    ] = "generic",
    out: Annotated[Path | None, typer.Option("--out", help="输出文件路径")] = None,
    include_drafts: Annotated[
        bool, typer.Option("--include-drafts", help="含未锁定稿(写作台预览)")
    ] = False,
) -> None:
    """按渠道模板导出已锁定章节;默认 generic 的 txt/md 行为保持可用。"""
    try:
        resolved_channel, resolved_fmt = resolve_channel_format(channel, fmt)
    except ExportSpecError as exc:
        typer.echo(f"拒绝: {exc}", err=True)
        raise typer.Exit(2) from None
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        target = out
        if target is None and resolved_fmt == "epub":
            target = Path(f"project-{project_id}-epub.epub")
        result = export_project(
            session,
            project_id,
            resolved_fmt,
            target,
            channel=resolved_channel,
            include_drafts=include_drafts,
        )
    if isinstance(result, Path):
        typer.echo(f"exported={result}")
    elif isinstance(result, bytes):
        typer.echo(f"exported=project-{project_id}-epub.epub")
    else:
        typer.echo(result)


@app.command()
def retrieve(
    project_id: Annotated[int, typer.Option("--project-id", help="已有项目 id")],
    query: Annotated[str, typer.Option("--query", help="检索问句")],
    limit: Annotated[int, typer.Option("--limit", help="返回条数")] = 8,
    include_provisional: Annotated[
        bool, typer.Option("--include-provisional", help="包含提案态事实")
    ] = False,
) -> None:
    """打印与问句最相关的已索引事实(调试用,不改正史)。"""
    cleaned = query.strip()
    if not cleaned:
        typer.echo("拒绝: --query 不能为空", err=True)
        raise typer.Exit(2)
    if limit < 1:
        typer.echo("拒绝: --limit 必须 >= 1", err=True)
        raise typer.Exit(2)
    settings = get_settings()
    engine = build_engine(settings.db_path)
    create_all(engine)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        try:
            repo.get_project(project_id)
        except NoResultFound:
            typer.echo(f"拒绝: 项目不存在 project_id={project_id}", err=True)
            raise typer.Exit(2) from None
        hits = memory_retrieval_for_session(session, settings).retrieve(
            project_id,
            cleaned,
            limit=limit,
            include_provisional=include_provisional,
        )
    if not hits:
        typer.echo("(无检索命中)")
        return
    for fact in hits:
        flag = "provisional" if fact.provisional else "committed"
        typer.echo(
            f"fact_id={fact.fact_id} kind={fact.kind.value} "
            f"source={fact.source} score={fact.score:.3f} {flag}"
        )
        typer.echo(fact.text)


@app.command("retrieve-eval")
def retrieve_eval(
    golden: Annotated[
        Path | None,
        typer.Option("--golden", help="冻结金标 JSON;默认 eval/retrieval/golden_queries.json"),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="人类可读报告路径;默认 reports/retrieval-eval.md")
    ] = None,
    compare_real: Annotated[
        bool,
        typer.Option(
            "--compare-real",
            help="另跑 openai_compat 嵌入对照;需已配置 embedding 槽位,默认 CI 不要开",
        ),
    ] = False,
) -> None:
    """离线评测 Stage 2 检索。默认 hash 嵌入,不访问网络。"""
    settings = get_settings()
    if compare_real and settings.embedding.provider != "openai_compat":
        typer.echo(
            "拒绝: --compare-real 需要 embedding.provider=openai_compat 且已配置 api_key/base_url",
            err=True,
        )
        raise typer.Exit(2)
    try:
        golden_path = golden if golden is not None else default_golden_path()
    except FileNotFoundError as exc:
        typer.echo(f"拒绝: {exc}", err=True)
        raise typer.Exit(2) from None
    if not golden_path.is_file():
        typer.echo(f"拒绝: 金标文件不存在 {golden_path}", err=True)
        raise typer.Exit(2)

    report_path = out or Path("reports/retrieval-eval.md")
    with tempfile.TemporaryDirectory(prefix="novel-retrieve-eval-") as raw:
        work = Path(raw)
        hash_report = run_eval_on_temp_db(golden_path, work / "hash", embedder=HashEmbedding())
        reports = [hash_report]
        if compare_real:
            reports.append(
                run_eval_on_temp_db(
                    golden_path,
                    work / "real",
                    embedder=build_embedder(settings.embedding),
                )
            )
        text = format_report(*reports)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    typer.echo(text.rstrip())
    typer.echo(f"report={report_path}")


if __name__ == "__main__":
    app()
