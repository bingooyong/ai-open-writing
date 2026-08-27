"""内置风格包加载(JSON fixture,随包分发)。"""

from __future__ import annotations

import json
from pathlib import Path

from novel_agent.style.schema import StylePack

PACKS_DIR = Path(__file__).resolve().parent / "packs"


class UnknownStylePack(KeyError):
    """CLI/API 指定了不存在的内置 pack id。"""


def list_builtin_pack_ids() -> list[str]:
    return sorted(path.stem for path in PACKS_DIR.glob("*.json"))


def load_builtin_pack(pack_id: str) -> StylePack:
    path = PACKS_DIR / f"{pack_id}.json"
    if not path.is_file():
        known = ", ".join(list_builtin_pack_ids()) or "(none)"
        raise UnknownStylePack(f"未知风格包 {pack_id!r};可选: {known}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StylePack.model_validate(payload)
