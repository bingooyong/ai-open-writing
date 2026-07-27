"""novel 命令行入口(阶段0:Typer)。

命令面随里程碑逐步填充:
  M3.2  init / plan
  M3.3b edit-outline
  M3.4  review-batch / approve
  M3.5  write-batch / resume / export
"""

import typer

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
        typer.echo(f"{name:8s} provider={slot.provider:12s} model={slot.model}")
    typer.echo(
        f"预算: 单章最大调用 {s.max_calls_per_chapter} 次;"
        f"修订轮次上限 {s.max_revision_rounds}(固定)"
    )


if __name__ == "__main__":
    app()
