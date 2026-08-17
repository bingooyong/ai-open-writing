"""章纲 sanitizer:从持久化章纲里剥过夜泄露条目。"""

from test_schemas import OUTLINE

from novel_agent.domain.schemas import ChapterOutline
from novel_agent.lint.bible import sanitize_outline


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
