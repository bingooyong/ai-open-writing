"""Project-level writing style configuration.

Packs live in project.settings["style"] (no new table). Readers must treat
invalid or missing packs as empty rather than raising.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from novel_agent.style.schema import StylePack, StyleProfile

PACKS_DIR = Path(__file__).resolve().parent / "packs"
SAMPLE_HEADER = "节奏样例（只学句长、空行、叙述距离，不学情节）："
ALIASES: dict[str, str] = {
    "镜头短句": "oral_short_beat",
    "职业白描": "craft_baimiao",
    "对话场": "dialogue_scene",
    "双线切开": "dual_cut",
    "心理密距": "close_interior",
}


def parse_style_pack(raw: object) -> StylePack | None:
    """Validate a stored pack. Missing or invalid input yields None."""
    if isinstance(raw, StylePack):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StylePack.model_validate(raw)
    except ValidationError:
        return None


def compile_style_rules(style: object) -> str:
    """Join compiled Chinese rules with rhythm samples for Writer/Prose few-shot."""
    pack = parse_style_pack(style)
    if pack is None:
        return ""
    samples = "\n\n".join(sample.strip("\n") for sample in pack.samples if str(sample).strip())
    body = pack.rules.strip()
    if not body:
        return ""
    if not samples:
        return body
    return f"{body}\n\n{SAMPLE_HEADER}\n\n{samples}"


def load_frozen_pack(pack_id: str) -> StylePack | None:
    """Load a repo-shipped pack by id or Chinese alias. Unknown or invalid files yield None."""
    if not pack_id or not isinstance(pack_id, str):
        return None
    resolved = ALIASES.get(pack_id, pack_id)
    if any(part in resolved for part in ("/", "\\", "..")):
        return None
    path = PACKS_DIR / f"{resolved}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return parse_style_pack(data)


def list_frozen_pack_ids() -> list[str]:
    if not PACKS_DIR.is_dir():
        return []
    return sorted(path.stem for path in PACKS_DIR.glob("*.json"))


__all__ = [
    "ALIASES",
    "PACKS_DIR",
    "SAMPLE_HEADER",
    "StylePack",
    "StyleProfile",
    "compile_style_rules",
    "list_frozen_pack_ids",
    "load_frozen_pack",
    "parse_style_pack",
]
