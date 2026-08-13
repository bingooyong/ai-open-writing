"""novel 命令行入口(阶段0:Typer)。

命令面随里程碑逐步填充:
  Story Bible  init / bible / graph
  M3.2         plan (规划链子程序)
  M3.3         write-chapter / smoke-chapter
  M3.3b        edit-outline
  M3.4         review-batch / approve
  M3.5         write-batch / resume / export
"""

import asyncio
import json
import sys
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
from novel_agent.graph.export import to_json, to_mermaid
from novel_agent.graph.projector import project_graph
from novel_agent.planning.chain import (
    PlanningAborted,
    PlanningError,
    PlanningGates,
    PlanningResult,
    run_planning_chain,
)
from novel_agent.planning.conversation import BibleResult, run_bible_conversation
from novel_agent.planning.runtime import build_planning_deps
from novel_agent.production.loop import ChapterLoopError, ChapterLoopGates, run_chapter_loop
from novel_agent.production.runtime import build_production_deps
from novel_agent.runtime.agents import AgentDeps
from novel_agent.verification.m26_smoke import (
    SmokeExecutionError,
    SmokeGateError,
    run_m26_smoke,
)
from novel_agent.verification.m33_smoke import run_m33_smoke
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
    for name in ("creative", "review", "judge", "extract"):
        slot = getattr(s, name)
        typer.echo(
            f"{name:8s} provider={slot.provider:12s} model={slot.model} family={slot.family}"
        )
    typer.echo(
        f"预算: 单章最大调用 {s.max_calls_per_chapter} 次;"
        f"修订轮次上限 {s.max_revision_rounds}(固定)"
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


def _echo_planning_result(result: PlanningResult | BibleResult) -> None:
    typer.echo(f"project_id={result.project_id}")
    typer.echo(f"kernel_version={result.kernel_version}")
    typer.echo(f"characters={','.join(result.character_ids)}")
    typer.echo(f"volume={result.volume_id}")
    typer.echo(f"unit={result.unit_id}")
    typer.echo(f"chapters={','.join(result.chapter_keys)}")
    if result.skipped:
        typer.echo(f"skipped={','.join(result.skipped)}")


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
            _run_bible(session, deps, brief, yes, select, volume_id, chapters)
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
            _run_bible(session, deps, resolved, yes, select, volume_id, chapters)
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


if __name__ == "__main__":
    app()
