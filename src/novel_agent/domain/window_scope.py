"""滚动窗口与全书草图的分界。

结构图可以勾勒后半本书,但窗口外的 chapter_key(ch48/ch115 等)只是草图,
不是冲突/爽点合同。Concept Judge 入参必须先经过 scope_structure_for_judge。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, cast

from novel_agent.domain.schemas import StructureMap

_VOLUME_KEY = re.compile(r"^v(?P<vol>\d+)c(?P<num>\d+)$", re.IGNORECASE)
_BARE_CH = re.compile(r"^ch?(?P<num>\d+)$", re.IGNORECASE)
_BEAT_FIELDS = (
    "inciting_incident",
    "commitment",
    "midpoint",
    "all_is_lost",
    "climax",
    "resolution",
)


def parse_chapter_ref(key: str) -> tuple[str | None, int | None]:
    """解析 v1c001 / ch48。返回 (volume_id|None, chapter_number|None)。"""
    text = key.strip()
    if not text:
        return None, None
    match = _VOLUME_KEY.fullmatch(text)
    if match:
        return f"v{int(match.group('vol'))}", int(match.group("num"))
    match = _BARE_CH.fullmatch(text)
    if match:
        return None, int(match.group("num"))
    return None, None


def next_volume_opening_key(rolling_keys: Sequence[str]) -> str:
    volumes: list[int] = []
    for key in rolling_keys:
        volume, _number = parse_chapter_ref(key)
        if volume and volume.startswith("v"):
            volumes.append(int(volume[1:]))
    if not volumes:
        return ""
    return f"v{max(volumes) + 1}c001"


def allowed_named_chapter_keys(rolling_keys: Sequence[str]) -> frozenset[str]:
    allowed = {key.strip() for key in rolling_keys if key.strip()}
    opening = next_volume_opening_key(rolling_keys)
    if opening:
        allowed.add(opening)
    return frozenset(allowed)


def named_key_status(key: str, rolling_keys: Sequence[str]) -> str:
    """in_window | next_volume | sketch | volume_only。"""
    text = key.strip()
    if not text:
        return "volume_only"
    window = {item.strip() for item in rolling_keys if item.strip()}
    if text in window:
        return "in_window"
    opening = next_volume_opening_key(rolling_keys)
    if text == opening:
        return "next_volume"
    volume, number = parse_chapter_ref(text)
    window_numbers = {parse_chapter_ref(item)[1] for item in window}
    window_numbers.discard(None)
    window_volumes = {parse_chapter_ref(item)[0] for item in window}
    window_volumes.discard(None)
    if number is not None and number in window_numbers:
        if volume is None or volume in window_volumes:
            return "in_window"
        return "sketch"
    return "sketch"


def scope_structure_for_judge(
    structure: StructureMap, rolling_keys: Sequence[str]
) -> dict[str, Any]:
    """给 Concept Judge 的结构图:窗口外 chapter_key 清空并标 sketch。

    不回传 original_chapter_key,避免裁判把草图号重新当成合同。
    """
    data = structure.model_dump()
    for field in _BEAT_FIELDS:
        beat = cast(dict[str, Any], data[field])
        status = named_key_status(str(beat.get("chapter_key") or ""), rolling_keys)
        if status == "sketch":
            beat["chapter_key"] = ""
        beat["named_key_status"] = status
    return data
