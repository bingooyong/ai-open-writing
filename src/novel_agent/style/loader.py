"""冻结风格包加载(JSON fixture,随包分发)。"""

from __future__ import annotations

import json
from pathlib import Path

from novel_agent.style.schema import StylePack

PACKS_DIR = Path(__file__).resolve().parent / "packs"

# 目录顺序: 一句一段·镜头短句, 职业白描, 对话场, 双线切开, 心理密距
FROZEN_CATALOG = (
    "oral_short_beat",
    "craft_baimiao",
    "dialogue_scene",
    "dual_cut",
    "close_interior",
)

PACK_ALIASES = {
    "镜头短句": "oral_short_beat",
    "职业白描": "craft_baimiao",
    "对话场": "dialogue_scene",
    "双线切开": "dual_cut",
    "心理密距": "close_interior",
}


class UnknownStylePack(KeyError):
    """CLI/API 指定了不存在的冻结 pack id / 别名。"""


def list_frozen_pack_ids() -> list[str]:
    found = {path.stem for path in PACKS_DIR.glob("*.json")}
    ordered = [pack_id for pack_id in FROZEN_CATALOG if pack_id in found]
    extras = sorted(found - set(FROZEN_CATALOG))
    return ordered + extras


def list_builtin_pack_ids() -> list[str]:
    return list_frozen_pack_ids()


def list_frozen_packs() -> list[StylePack]:
    return list_frozen_packs_uncached()


def resolve_pack_id(name: str) -> str:
    key = name.strip()
    if not key:
        raise UnknownStylePack(_unknown_message(name))
    if key in PACK_ALIASES:
        return PACK_ALIASES[key]
    if (PACKS_DIR / f"{key}.json").is_file():
        return key
    for pack in list_frozen_packs_uncached():
        if pack.mid_style == key or pack.label == key or key in pack.label:
            return pack.id
    raise UnknownStylePack(_unknown_message(name))


def list_frozen_packs_uncached() -> list[StylePack]:
    packs: list[StylePack] = []
    for pack_id in list_frozen_pack_ids():
        path = PACKS_DIR / f"{pack_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        packs.append(StylePack.model_validate(payload))
    return packs


def load_frozen_pack(name: str) -> StylePack:
    pack_id = resolve_pack_id(name)
    path = PACKS_DIR / f"{pack_id}.json"
    if not path.is_file():
        raise UnknownStylePack(_unknown_message(name))
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StylePack.model_validate(payload)


def load_builtin_pack(name: str) -> StylePack:
    """历史别名:与 load_frozen_pack 相同。"""
    return load_frozen_pack(name)


def _unknown_message(name: str) -> str:
    known = ", ".join(list_frozen_pack_ids()) or "(none)"
    aliases = ", ".join(PACK_ALIASES)
    return f"未知风格包 {name!r};可选: {known};中文别名: {aliases}"
