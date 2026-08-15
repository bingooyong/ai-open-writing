"""工厂门禁:短稿剔除、Judge 空包识别、修订范围映射。"""

from test_schemas import SCENE, _issue

from novel_agent.domain.schemas import DraftCandidate, JudgeVerdict, ReviewIssue, SceneCard
from novel_agent.production.factory import (
    is_empty_packet_verdict,
    is_usable_draft,
    pick_lockable_candidate,
    resolve_revision_scope,
)


def _long_prose() -> str:
    return "临安茶楼里灯火通明，苏晚生一拍醒木。" * 30


def test_short_writer_b_and_placeholder_rejected() -> None:
    assert not is_usable_draft("（正文）")
    assert not is_usable_draft("短稿十个字而已。")
    assert is_usable_draft(_long_prose())


def test_empty_packet_verdict_detected_without_hard_gate() -> None:
    empty = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "reasoning_summary": "用户未提供评审材料，强制 HUMAN_REVIEW",
        }
    )
    assert is_empty_packet_verdict(empty) is True

    real = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["canon_conflict"],
            "reasoning_summary": "正史冲突，升级人工",
        }
    )
    assert is_empty_packet_verdict(real) is False


def test_pick_lockable_skips_junk_and_boundary_hits() -> None:
    junk = DraftCandidate.model_validate(
        dict(
            candidate_id="candidate_2",
            chapter_key="v1c001",
            scenes=[{"scene_id": "v1c001_s1", "content": "（正文）"}],
            chapter_summary="空",
        )
    )
    dirty = DraftCandidate.model_validate(
        dict(
            candidate_id="candidate_1",
            chapter_key="v1c001",
            scenes=[{"scene_id": "v1c001_s1", "content": _long_prose() + "禁无代价全能"}],
            chapter_summary="脏",
        )
    )
    clean = DraftCandidate.model_validate(
        dict(
            candidate_id="candidate_1",
            chapter_key="v1c001",
            scenes=[{"scene_id": "v1c001_s1", "content": _long_prose() + "又一段干净收束。"}],
            chapter_summary="好",
        )
    )
    picked = pick_lockable_candidate([junk, dirty, clean], ["禁无代价全能"])
    assert picked is not None
    assert "禁无代价全能" not in picked.full_text()


def test_chinese_revision_scope_falls_back_to_issue_scenes() -> None:
    draft = DraftCandidate.model_validate(
        dict(
            candidate_id="candidate_1",
            chapter_key="v1c001",
            scenes=[
                {"scene_id": "v1c001_s1", "content": "一"},
                {"scene_id": "v1c001_s2", "content": "二"},
            ],
            chapter_summary="s",
        )
    )
    issue = ReviewIssue.model_validate(
        {
            **_issue(),
            "evidence": [{"scene_id": "v1c001_s2", "quote": "二"}],
        }
    )
    cards = [
        SceneCard.model_validate({**SCENE, "scene_id": "v1c001_s1"}),
        SceneCard.model_validate({**SCENE, "scene_id": "v1c001_s2"}),
    ]
    assert resolve_revision_scope(["只修后巷对峙"], draft, cards=cards, issues=[issue]) == [
        "v1c001_s2"
    ]
    assert resolve_revision_scope(["v1c001_s1"], draft, cards=cards) == ["v1c001_s1"]
