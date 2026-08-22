"""章纲 sanitizer:从持久化章纲里剥过夜泄露条目。"""

from test_schemas import OUTLINE

from novel_agent.domain.schemas import ChapterOutline
from novel_agent.lint.bible import lint_outline_citations, sanitize_outline
from novel_agent.planning.volume import (
    apply_inherited_spoilers,
    coerce_outline_citations,
    continuation_recap,
    redact_remaining_spoilers,
)


def _outline(**overrides: object) -> ChapterOutline:
    return ChapterOutline.model_validate({**OUTLINE, **overrides})


def test_sanitize_outline_strips_overnight_forbidden_items() -> None:
    outline = _outline(
        reveal_forbidden=[
            "穿越身份",
            "默写分镜笔记的存在",
            "反噬设定",
            "前世、借技法、代价账本、额角跳痛、耳鸣、偏头痛、左眼花",
            "主角主人真名",
            "笔记本备用",
        ],
        cited_conflict_ids=["c2_借技法反噬", "c001"],
        cited_beat_ids=["b1_救场立身份", "b001"],
    )
    cleaned = sanitize_outline(outline)
    assert "穿越身份" in cleaned.reveal_forbidden
    assert "主角主人真名" in cleaned.reveal_forbidden
    assert "笔记本备用" in cleaned.reveal_forbidden  # substring 笔记 must NOT drop this
    assert "反噬设定" not in cleaned.reveal_forbidden
    assert "默写分镜笔记的存在" not in cleaned.reveal_forbidden
    assert not any(
        "耳鸣" in item or "左眼花" in item or "左眼薄雾" in item
        for item in cleaned.reveal_forbidden
    )
    assert "c2_借技法反噬" not in cleaned.cited_conflict_ids  # contains 反噬
    assert "c001" in cleaned.cited_conflict_ids
    assert "b1_救场立身份" in cleaned.cited_beat_ids  # no strip token; membership is Task 2
    assert "b001" in cleaned.cited_beat_ids


def test_sanitize_outline_drops_left_eye_mist_item() -> None:
    outline = _outline(reveal_forbidden=["左眼薄雾", "穿越身份"])
    cleaned = sanitize_outline(outline)
    assert "左眼薄雾" not in cleaned.reveal_forbidden
    assert "穿越身份" in cleaned.reveal_forbidden


def test_lint_outline_citations_rejects_invented_ids() -> None:
    findings = lint_outline_citations(
        ["c2_借技法反噬"],
        ["b1_救场立身份"],
        "v1c001",
        known_conflict_ids={"c001", "c002"},
        known_beat_ids={"b001", "b002"},
    )
    assert findings
    blob = " ".join(item.message for item in findings)
    assert "b1_救场立身份" in blob
    assert "c2_借技法反噬" in blob

    ok = lint_outline_citations(
        ["c001"],
        ["b001"],
        "v1c001",
        known_conflict_ids={"c001"},
        known_beat_ids={"b001"},
    )
    assert ok == []

    empty = lint_outline_citations([], [], "v1c009")
    assert empty and "未引用" in empty[0].message

    skipped = lint_outline_citations(
        [],
        ["b1_救场立身份"],
        "v1c001",
        known_conflict_ids=set(),
        known_beat_ids=set(),
    )
    assert skipped == []  # empty known sets skip membership; not empty-both


def test_apply_inherited_spoilers_strips_leak_tokens() -> None:
    result = apply_inherited_spoilers(
        [_outline(reveal_forbidden=["穿越身份"])],
        ["反噬设定", "主角主人真名"],
    )
    forbidden = result[0].reveal_forbidden
    assert "主角主人真名" in forbidden
    assert "穿越身份" in forbidden
    assert "反噬设定" not in forbidden


def test_coerce_outline_citations_maps_invented_ids() -> None:
    outline = _outline(
        cited_conflict_ids=["c2_借技法反噬", "c001"],
        cited_beat_ids=["b1_救场立身份", "unknown_beat"],
    )
    coerced = coerce_outline_citations(
        outline,
        known_conflict_ids={"c001", "c002"},
        known_beat_ids={"b001", "b002"},
    )
    assert coerced.cited_conflict_ids == ["c002", "c001"]
    assert coerced.cited_beat_ids == ["b001"]
    assert "c2_借技法反噬" not in coerced.cited_conflict_ids
    assert "unknown_beat" not in coerced.cited_beat_ids

    empty_known = coerce_outline_citations(
        _outline(cited_conflict_ids=[], cited_beat_ids=["b1_救场立身份"]),
        known_conflict_ids={"c001"},
        known_beat_ids={"b001"},
    )
    assert empty_known.cited_beat_ids == ["b001"]
    assert empty_known.cited_conflict_ids == ["c001"]


def test_redact_remaining_spoilers_from_visible_fields() -> None:
    outline = _outline(
        title="书局主人真名现身",
        core_event="当场喊出书局主人真名并借技法",
        exit_hook="钩子:书局主人真名还没走",
        key_choice="是否公开书局主人真名",
    )
    redacted = redact_remaining_spoilers(outline, ["书局主人真名"])
    assert "书局主人真名" not in redacted.title
    assert "书局主人真名" not in redacted.core_event
    assert "书局主人真名" not in redacted.exit_hook
    assert "书局主人真名" not in redacted.key_choice
    assert redacted.core_event.strip()
    assert redacted.exit_hook.strip()
    assert redacted.key_choice.strip()


def test_continuation_recap_includes_recent_ends() -> None:
    recap = continuation_recap(
        [_outline(chapter_key="v1c005", title="救人", end_state="代价显形")],
        canon_notes="ch_su.status=已知评书会成真 (committed v1c001)",
    )
    assert "v1c005" in recap
    assert "代价显形" in recap
    assert "ch_su.status" in recap
