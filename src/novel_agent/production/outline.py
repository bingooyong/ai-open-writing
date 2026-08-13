"""M3.3b:章纲/场景卡 YAML 导出导入,bump outline_ver,回 N1。"""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import ValidationError
from sqlmodel import Session

from novel_agent.domain.repos import PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterOutline, ChapterStatus, SceneCard

_EDITABLE = frozenset(
    {ChapterStatus.NEEDS_REPLAN, ChapterStatus.PLANNED, ChapterStatus.STALE}
)


class OutlineEditError(Exception):
    """章纲导入失败(状态非法或 Schema 校验失败)。"""


def export_outline_bundle(
    planning: PlanningRepo, project_id: int, chapter_key: str
) -> dict[str, Any]:
    outline = planning.get_outline(project_id, chapter_key)
    scenes = planning.list_scene_cards(project_id, chapter_key)
    return {
        "outline": outline.model_dump(mode="json"),
        "scenes": [card.model_dump(mode="json") for card in scenes],
    }


def dump_outline_yaml(bundle: dict[str, Any]) -> str:
    return yaml.safe_dump(bundle, allow_unicode=True, sort_keys=False)


def _coerce_schema_version(payload: Any) -> Any:
    if isinstance(payload, dict):
        out = dict(payload)
        if "schema_version" in out:
            out["schema_version"] = str(out["schema_version"])
        return {key: _coerce_schema_version(value) for key, value in out.items()}
    if isinstance(payload, list):
        return [_coerce_schema_version(item) for item in payload]
    return payload


def parse_outline_yaml(text: str) -> tuple[ChapterOutline, list[SceneCard]]:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise OutlineEditError("YAML 根节点必须是映射,含 outline 与 scenes")
    raw = _coerce_schema_version(raw)
    if "outline" not in raw or "scenes" not in raw:
        raise OutlineEditError("YAML 必须包含 outline 与 scenes")
    try:
        outline = ChapterOutline.model_validate(raw["outline"])
        scenes_raw = raw["scenes"]
        if not isinstance(scenes_raw, list) or not scenes_raw:
            raise OutlineEditError("scenes 必须是非空列表")
        scenes = [SceneCard.model_validate(item) for item in scenes_raw]
    except ValidationError as exc:
        raise OutlineEditError(f"章纲/场景卡 Schema 校验失败: {exc}") from exc
    return outline, scenes


def apply_outline_edit(
    session: Session, project_id: int, chapter_key: str, yaml_text: str
) -> int:
    """导入校验通过后 bump outline_ver、作废旧谱系、重置轮次并回到 PLANNED。"""
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    chapter = planning.get_chapter(project_id, chapter_key)
    if chapter.status not in _EDITABLE:
        raise OutlineEditError(
            f"章节状态 {chapter.status.value} 不可 edit-outline,请先退回重规划"
        )
    outline, scenes = parse_outline_yaml(yaml_text)
    if outline.chapter_key != chapter_key:
        raise OutlineEditError(
            f"YAML chapter_key={outline.chapter_key} 与目标 {chapter_key} 不一致"
        )
    for card in scenes:
        if card.chapter_key != chapter_key:
            raise OutlineEditError(f"场景卡 {card.scene_id} 的 chapter_key 与章节不一致")
    planning.replace_scene_cards(project_id, chapter_key, scenes)
    new_ver = planning.update_outline(project_id, chapter_key, outline)
    production.void_lineage(project_id, chapter_key)
    return new_ver
