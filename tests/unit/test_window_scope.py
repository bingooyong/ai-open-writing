"""滚动窗口 vs 全书草图:远章键是 sketch,不是冲突合同。"""

from __future__ import annotations

from novel_agent.domain.schemas import Conflict, PayoffBeat, StructureMap
from novel_agent.domain.schemas.structure import GoldenThreeChapter, StructureBeat
from novel_agent.lint.bible import lint_bible
from novel_agent.domain.window_scope import (
    allowed_named_chapter_keys,
    named_key_status,
    next_volume_opening_key,
    parse_chapter_ref,
    scope_structure_for_judge,
)

_GOLDEN = GoldenThreeChapter(
    promise="主角当场面对余烬里的广播",
    escalation="回声把危机推到眼前",
    payoff_or_hook="小闭环后留下新问题",
)


def _beat(summary: str, chapter_key: str = "", volume_id: str = "") -> StructureBeat:
    return StructureBeat(summary=summary, chapter_key=chapter_key, volume_id=volume_id)


def yu_jin_structure() -> StructureMap:
    """末世《余烬回声》现场形态:三幕指向 ch48/ch79/ch108/ch115。"""
    return StructureMap(
        inciting_incident=_beat("余烬里传来旧日广播", "v1c001", "v1"),
        commitment=_beat("主角决定追查回声来源", "v1c003", "v1"),
        midpoint=_beat("中点反转:回声是自己发出的", "ch48", "v2"),
        all_is_lost=_beat("绝境:据点被抹除", "ch79", "v2"),
        climax=_beat("高潮:对质广播源", "ch108", "v3"),
        resolution=_beat("终局:余烬里只剩自己的声音", "ch115", "v3"),
        golden_three=[_GOLDEN, _GOLDEN, _GOLDEN],
    )


def _window_conflicts() -> list[Conflict]:
    return [
        Conflict.model_validate(
            dict(
                conflict_id="cf_echo",
                kind="identity",
                parties=["ch_lead"],
                stake="要不要回应广播",
                temperature="rising",
                must_affect="both",
                payoff_chapter_key="v1c003",
            )
        )
    ]


def _window_payoffs() -> list[PayoffBeat]:
    return [
        PayoffBeat.model_validate(
            dict(
                beat_id="pb_1",
                scale="small",
                kind="reveal",
                pressure_before="广播点名他",
                hit="他听出那是自己的声音",
                chapter_key="v1c002",
                order_index=1,
            )
        )
    ]


def test_parse_volume_and_bare_ch_keys() -> None:
    assert parse_chapter_ref("v1c001") == ("v1", 1)
    assert parse_chapter_ref("ch48") == (None, 48)
    assert parse_chapter_ref("ch115") == (None, 115)
    assert parse_chapter_ref("") == (None, None)


def test_allowed_keys_include_window_and_next_volume_opening() -> None:
    rolling = ["v1c001", "v1c002", "v1c003"]
    allowed = allowed_named_chapter_keys(rolling)
    assert {"v1c001", "v1c002", "v1c003"} <= allowed
    assert next_volume_opening_key(rolling) == "v2c001"
    assert "v2c001" in allowed
    assert named_key_status("v1c001", rolling) == "in_window"
    assert named_key_status("ch3", rolling) == "in_window"
    assert named_key_status("v2c001", rolling) == "next_volume"
    assert named_key_status("ch48", rolling) == "sketch"
    assert named_key_status("ch108", rolling) == "sketch"
    assert named_key_status("ch115", rolling) == "sketch"
    assert named_key_status("", rolling) == "volume_only"


def test_scope_structure_clears_far_keys_for_judge() -> None:
    rolling = ["v1c001", "v1c002", "v1c003"]
    scoped = scope_structure_for_judge(yu_jin_structure(), rolling)
    assert scoped["inciting_incident"]["chapter_key"] == "v1c001"
    assert scoped["inciting_incident"]["named_key_status"] == "in_window"
    assert scoped["midpoint"]["chapter_key"] == ""
    assert scoped["midpoint"]["named_key_status"] == "sketch"
    assert scoped["all_is_lost"]["named_key_status"] == "sketch"
    assert scoped["climax"]["named_key_status"] == "sketch"
    assert scoped["resolution"]["named_key_status"] == "sketch"
    assert "ch48" not in scoped["midpoint"]["chapter_key"]
    assert "original_chapter_key" not in scoped["midpoint"]


def test_r4_lint_accepts_window_engine_with_far_structure_keys() -> None:
    rolling = ["v1c001", "v1c002", "v1c003"]
    report = lint_bible(
        structure=yu_jin_structure(),
        conflicts=_window_conflicts(),
        payoff_beats=_window_payoffs(),
        rolling_keys=rolling,
    )
    assert report.passed
    assert not any(item.code == "orphan_conflict" for item in report.findings)


def test_r4_lint_empty_conflict_still_fails() -> None:
    rolling = ["v1c001", "v1c002", "v1c003"]
    report = lint_bible(
        structure=yu_jin_structure(),
        conflicts=[],
        payoff_beats=[],
        rolling_keys=rolling,
    )
    assert not report.passed
    assert any(item.code == "empty_conflict" for item in report.findings)
