"""项目写作风格包(存 project.settings["style"],注入 ChapterContextPackage.style_rules)。"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_SAMPLE_HEADING = "节奏样例（只学句长、空行、叙述距离，不学情节）"


class StyleProfile(BaseModel):
    """抽象节奏参数;不注入正文,只随包持久化。"""

    model_config = ConfigDict(extra="ignore")

    paragraph_unit: str = "sentence"
    avg_sentence_chars: tuple[int, int] = (8, 22)
    punch_line_max_chars: int = 8
    dialogue_ratio_hint: float = 0.4
    narrator_distance: str = "close_camera"
    interior: str = "short_judgment"
    time_place: str = "isolated_lines"
    result_first: bool = True


class StylePack(BaseModel):
    """作者批准的项目风格包。校验失败时读路径应降级为空规则,不抛给生产循环。"""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    profile: StyleProfile = Field(default_factory=StyleProfile)
    rules: str = ""
    samples: list[str] = Field(default_factory=list)


def parse_style_pack(raw: object) -> StylePack | None:
    """读路径:缺失/未知/非法 → None,不抛。"""
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        pack = StylePack.model_validate(raw)
    except ValidationError:
        return None
    if not pack.id.strip() or not pack.label.strip():
        return None
    return pack


def compile_style_rules(pack: StylePack) -> str:
    """rules + 标注样例;保持短,不当成一章 few-shot。"""
    parts: list[str] = []
    rules = pack.rules.strip()
    if rules:
        parts.append(rules)
    samples = [sample.strip() for sample in pack.samples if sample and sample.strip()]
    if samples:
        numbered = "\n\n".join(
            f"{index}.\n{sample}" for index, sample in enumerate(samples, start=1)
        )
        parts.append(f"{_SAMPLE_HEADING}\n\n{numbered}")
    return "\n\n".join(parts)


def style_rules_from_settings(settings: object) -> str:
    """从 project.settings 编译注入文本;任何坏数据都变成空串。"""
    raw = settings if isinstance(settings, dict) else {}
    pack = parse_style_pack(raw.get("style"))
    if pack is None:
        return ""
    return compile_style_rules(pack)
