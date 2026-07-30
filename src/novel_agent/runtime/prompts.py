"""提示词加载(D14:提示词即代码,YAML frontmatter 版本化)。

文件格式(prompts/<role>.md):
    ---
    version: 1
    role: writer
    slot: creative
    ---
    正文模板,占位符用 ${var}(string.Template,避免与 JSON 花括号冲突)
"""

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

import yaml

DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
VALID_SLOTS = frozenset({"creative", "review", "judge", "extract"})


@dataclass(frozen=True)
class PromptSpec:
    role: str
    slot: str
    version: int
    input_schema: str
    output_schema: str
    body: Template

    @property
    def prompt_version(self) -> str:
        return f"{self.role}_v{self.version}"

    def render(self, **vars_: str) -> str:
        try:
            return self.body.substitute(**vars_)
        except KeyError as exc:
            raise ValueError(
                f"提示词 {self.prompt_version} 缺少模板变量: {exc.args[0]}"
            ) from exc


class PromptNotFound(Exception):
    pass


def load_prompt(role: str, prompts_dir: Path | None = None) -> PromptSpec:
    path = (prompts_dir or DEFAULT_PROMPTS_DIR) / f"{role}.md"
    if not path.is_file():
        raise PromptNotFound(f"提示词文件不存在: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} 缺少 YAML frontmatter")
    try:
        _, fm, body = text.split("---", 2)
    except ValueError as exc:
        raise ValueError(f"{path} frontmatter 未闭合") from exc
    meta: Any = yaml.safe_load(fm)
    if not isinstance(meta, dict):
        raise ValueError(f"{path} YAML frontmatter 必须是对象")
    if meta.get("role") != role:
        raise ValueError(f"{path} frontmatter role={meta.get('role')} 与文件名不符")
    slot = meta.get("slot")
    if slot not in VALID_SLOTS:
        raise ValueError(f"{path} slot={slot!r} 非法;必须是 {sorted(VALID_SLOTS)} 之一")
    version = meta.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"{path} version 必须是正整数")
    input_schema = meta.get("input_schema")
    output_schema = meta.get("output_schema")
    if not isinstance(input_schema, str) or not input_schema.strip():
        raise ValueError(f"{path} 缺少 input_schema 声明")
    if not isinstance(output_schema, str) or not output_schema.strip():
        raise ValueError(f"{path} 缺少 output_schema 声明")
    if not body.strip():
        raise ValueError(f"{path} 提示词正文为空")
    return PromptSpec(
        role=role,
        slot=slot,
        version=version,
        input_schema=input_schema.strip(),
        output_schema=output_schema.strip(),
        body=Template(body.strip()),
    )
