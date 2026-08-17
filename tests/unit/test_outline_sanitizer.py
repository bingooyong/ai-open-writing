"""章纲 sanitizer:从持久化章纲里剥过夜泄露条目。"""

from test_schemas import OUTLINE

from novel_agent.domain.schemas import ChapterOutline
from novel_agent.lint.bible import lint_outline_citations, sanitize_outline
from novel_agent.planning.volume import apply_inherited_spoilers


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
