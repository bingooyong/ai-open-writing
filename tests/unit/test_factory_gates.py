"""工厂门禁:短稿剔除、Judge 空包识别、修订范围映射。"""

from test_schemas import SCENE, _issue

from novel_agent.domain.schemas import DraftCandidate, JudgeVerdict, ReviewIssue, SceneCard
from novel_agent.production.factory import (
    is_empty_packet_verdict,
    is_usable_draft,
    pick_lockable_candidate,
    pick_sole_lockable_candidate,
    resolve_revision_scope,
)


def _long_prose() -> str:
    return "临安茶楼里灯火通明，苏晚生一拍醒木。" * 50


def test_short_writer_b_and_placeholder_rejected() -> None:
    assert not is_usable_draft("（正文）")
    assert not is_usable_draft("短稿十个字而已。")
    assert is_usable_draft(_long_prose())


def test_meta_refusal_asking_for_scene_cards_is_rejected() -> None:
    """Live v1c007 Writer B: 656 字拒稿要操作员补场景卡,不得进 Judge。"""
    refusal = (
        "抱歉，我当前仍未收到本场景的场景卡字段、上下文包与硬约束。"
        "请将以下内容补齐后重新下发：scene_id、entry_state、goal、obstacle、硬约束清单。"
        "```\n<<<SCENE:v1c007_s1>>>\n（正文）\n<<<END>>>\n```\n"
    ) * 6
    assert len("".join(refusal.split())) > 400
    assert not is_usable_draft(refusal)


def test_repeated_placeholder_and_scene_scaffold_rejected_even_if_long() -> None:
    padded = ("<<<SCENE:v1c007_s1>>>\n（正文）\n<<<END>>>\n") * 40
    assert len("".join(padded.split())) > 400
    assert not is_usable_draft(padded)


def test_short_complaint_letter_rejected_beside_real_candidate() -> None:
    """656 字抱怨信即使不含占位词,也不能跟杀青戏并列进 Judge。"""
    complaint = "这一场我写不下去，材料不够，请再给一点提示。" * 22
    assert 400 < len("".join(complaint.split())) < 800
    assert not is_usable_draft(complaint)
    killing = "杀青那天灯刚亮，她把最后一条通告夹进夹板，场务已经在拆轨道。" * 40
    assert is_usable_draft(killing)


def test_in_story_scene_card_mention_is_not_a_refusal() -> None:
    """《穿回去当导演》正文可以写场景卡,不得误杀。"""
    prose = (
        "她翻开场景卡，把今晚的杀青戏又过了一遍，场记在旁边点头。"
        "通告单上的硬约束只有一条：这条巷子里不能出现现代器械。"
    ) * 25
    assert is_usable_draft(prose)


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


def _candidate(cid: str, content: str) -> DraftCandidate:
    return DraftCandidate.model_validate(
        dict(
            candidate_id=cid,
            chapter_key="v1c008",
            scenes=[{"scene_id": "v1c008_s1", "content": content}],
            chapter_summary="s",
        )
    )


def _leaky_prose() -> str:
    return (
        _long_prose()
        + "监视器还没看完，她已经跑到产房门口，穿越的耳鸣炸开，实习生把笔记递上来，真名差点说出口。"
    )


def _clean_onbrief() -> str:
    return _long_prose() + "周洵还在同组，她不知道镜头在哪，私下只叫朔哥，预报名金鸡金马。"


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


def test_hard_gate_leak_is_usable_prose_but_not_lockable() -> None:
    """v1c008 A 类跑题泄漏仍是长正文,n3 放行;工厂锁门必须剔除。"""
    leaked = _leaky_prose()
    assert is_usable_draft(leaked)
    assert pick_lockable_candidate([_candidate("candidate_1", leaked)], []) is None
    assert pick_lockable_candidate([_candidate("candidate_1", _clean_onbrief())], []) is not None


def test_sole_lockable_candidate_ignores_leaky_sibling() -> None:
    leaked = _candidate("candidate_1", _leaky_prose())
    clean = _candidate("candidate_2", _clean_onbrief())
    picked = pick_sole_lockable_candidate([leaked, clean], [])
    assert picked is not None
    assert picked.candidate_id == "candidate_2"
    assert "穿越" not in picked.full_text()


def test_sole_lockable_none_when_both_clean_or_both_junk() -> None:
    clean_a = _candidate("candidate_1", _clean_onbrief())
    clean_b = _candidate("candidate_2", _long_prose() + "通告单夹进夹板，场务开始拆轨道。")
    assert pick_sole_lockable_candidate([clean_a, clean_b], []) is None
    leaked_a = _candidate("candidate_1", _leaky_prose())
    leaked_b = _candidate("candidate_2", _long_prose() + "天台锁一响，穿越后耳鸣没停。")
    assert pick_sole_lockable_candidate([leaked_a, leaked_b], []) is None
    assert pick_sole_lockable_candidate([clean_b], []) is None


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
