"""novel 命令行入口(阶段0:Typer)。

命令面随里程碑逐步填充:
  M3.2  init / plan
  M3.3b edit-outline
  M3.4  review-batch / approve
  M3.5  write-batch / resume / export
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from novel_agent import __version__

app = typer.Typer(help="本地优先的 AI 长篇小说创作智能体(阶段0)", no_args_is_help=True)


@app.command()
def version() -> None:
    """显示版本。"""
    typer.echo(f"novel-agent {__version__}")


@app.command()
def doctor() -> None:
    """检查环境与配置(模型槽位、数据库路径)。"""
    from novel_agent.config import get_settings

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

    from novel_agent.config import get_settings
    from novel_agent.verification.m26_smoke import (
        SmokeExecutionError,
        SmokeGateError,
        run_m26_smoke,
    )

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


if __name__ == "__main__":
    app()
