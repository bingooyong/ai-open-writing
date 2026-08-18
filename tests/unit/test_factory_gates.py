"""工厂门禁:短稿剔除、Judge 空包识别、修订范围映射。"""

from test_schemas import SCENE, _issue

from novel_agent.domain.schemas import (
    DraftCandidate,
    HardGate,
    JudgeVerdict,
    ReviewIssue,
    SceneCard,
    VerdictType,
)
from novel_agent.production.factory import (
    _HARD_GATE_LEAK_RE,
    LockGates,
    chapter_index_from_key,
    critical_parse_failure_should_raise,
    enforce_lockable_verdict,
    has_hard_gate_leak,
    is_empty_packet_verdict,
    is_lockable_draft,
    is_usable_draft,
    pick_lockable_candidate,
    pick_sole_lockable_candidate,
    resolve_revision_scope,
    strip_allowed_name_boundaries,
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


def test_empty_packet_with_source_risk_and_overnight_wording() -> None:
    v012 = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["source_risk"],
            "reasoning_summary": (
                "输入内容为空，未检测到任何场景候选，按 source_risk 退回人工审核。"
            ),
        }
    )
    assert is_empty_packet_verdict(v012) is True

    v013 = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["source_risk"],
            "reasoning_summary": "未提供实际场景数据进行裁决，因此按 source_risk 退回人工审核。",
        }
    )
    assert is_empty_packet_verdict(v013) is True

    v020 = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "unknown",
            "hard_gate_failures": ["source_risk"],
            "reasoning_summary": (
                "上次输出误将JSON Schema定义本身作为输出内容，"
                "缺少必需字段verdict、selected_candidate和reasoning_summary。"
            ),
        }
    )
    assert is_empty_packet_verdict(v020) is True

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


def test_left_eye_haze_is_usable_but_not_lockable() -> None:
    haze = _long_prose() + "左眼薄雾又压上来，监视器上的脸花成一团。"
    flower = _long_prose() + "左眼花了三回，他还是没喊 cut。"
    backlash = _long_prose() + "偷技法的反噬让他当晚不敢再借。"
    notebook = _long_prose() + "他合上笔记本，把工作笔记收进抽屉。"
    assert is_usable_draft(haze) and is_usable_draft(flower) and is_usable_draft(backlash)
    assert pick_lockable_candidate([_candidate("candidate_1", haze)], []) is None
    assert pick_lockable_candidate([_candidate("candidate_1", flower)], []) is None
    assert pick_lockable_candidate([_candidate("candidate_1", backlash)], []) is None
    assert pick_lockable_candidate([_candidate("candidate_1", notebook)], []) is not None


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


_NAMES = ["林朔", "柳奕妃", "许静蕾", "樊冰屏", "周洵", "张紫衣"]


def test_wrong_book_prose_not_lockable_when_names_required() -> None:
    republican = (
        "周意坐在窗前读书，陆怀坐在客位上，裴谈把名帖折成两折，撑伞走进雨里。" * 40
    )
    onbrief = _long_prose() + "林朔没喊 cut。柳奕妃把话筒轻轻放回去。"
    assert "林朔" not in republican
    leaked = _candidate("candidate_1", republican)
    clean = _candidate("candidate_2", onbrief)
    assert pick_lockable_candidate([leaked], [], required_names=_NAMES) is None
    picked = pick_sole_lockable_candidate([leaked, clean], [], required_names=_NAMES)
    assert picked is not None and picked.candidate_id == "candidate_2"


def test_sole_lockable_single_onbrief_candidate() -> None:
    clean = _candidate("candidate_1", _long_prose() + "林朔在监视器前坐下。")
    picked = pick_sole_lockable_candidate([clean], [], required_names=["林朔"])
    assert picked is not None and picked.candidate_id == "candidate_1"


def test_allowed_variant_name_is_not_content_boundary() -> None:
    issue = ReviewIssue.model_validate(
        {
            "issue_id": "i1",
            "reviewer_role": "red_team",
            "claim": "许静蕾真名",
            "evidence": [{"scene_id": "v1c009_s1", "quote": "许静蕾把杯子转了半圈"}],
            "violated_rule": "禁真名",
            "hard_gate": "content_boundary",
            "severity": "P0",
            "failure_consequence": "违禁",
            "recommended_rollback_level": "chapter_outline",
            "confidence": 0.9,
        }
    )
    verdict = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["content_boundary"],
            "rulings": [{"issue_id": "i1", "accepted": True, "reason": "真名"}],
            "reasoning_summary": "许静蕾是真名，升级人工",
        }
    )
    cleaned = strip_allowed_name_boundaries(
        verdict, [issue], allowed_names=["许静蕾", "林朔"]
    )
    assert HardGate.CONTENT_BOUNDARY not in cleaned.hard_gate_failures
    assert not any(item.issue_id == "i1" and item.accepted for item in cleaned.rulings)

    dirty = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["content_boundary"],
            "reasoning_summary": "出现章子怡真名",
        }
    )
    kept = strip_allowed_name_boundaries(dirty, [], allowed_names=["许静蕾"])
    assert HardGate.CONTENT_BOUNDARY in kept.hard_gate_failures

    xu = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["content_boundary"],
            "reasoning_summary": "出现徐静蕾真名",
        }
    )
    kept_xu = strip_allowed_name_boundaries(xu, [], allowed_names=["许静蕾"])
    assert HardGate.CONTENT_BOUNDARY in kept_xu.hard_gate_failures

    mixed = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["content_boundary"],
            "reasoning_summary": "许静蕾与章子怡真名同时出现",
        }
    )
    kept_mixed = strip_allowed_name_boundaries(
        mixed, [], allowed_names=["许静蕾", "林朔"]
    )
    assert HardGate.CONTENT_BOUNDARY in kept_mixed.hard_gate_failures

    other = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["content_boundary", "canon_conflict"],
            "rulings": [
                {"issue_id": "i1", "accepted": True, "reason": "真名"},
                {"issue_id": "i2", "accepted": True, "reason": "正史冲突"},
            ],
            "reasoning_summary": "许静蕾是真名，升级人工",
        }
    )
    canon_issue = ReviewIssue.model_validate(
        {
            **_issue(),
            "issue_id": "i2",
            "claim": "正史冲突",
            "hard_gate": "canon_conflict",
        }
    )
    cleaned_other = strip_allowed_name_boundaries(
        other, [issue, canon_issue], allowed_names=["许静蕾"]
    )
    assert HardGate.CONTENT_BOUNDARY not in cleaned_other.hard_gate_failures
    assert HardGate.CANON_CONFLICT in cleaned_other.hard_gate_failures
    assert any(item.issue_id == "i2" and item.accepted for item in cleaned_other.rulings)
    assert not any(item.issue_id == "i1" and item.accepted for item in cleaned_other.rulings)


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


def test_critical_parse_failure_should_raise() -> None:
    assert critical_parse_failure_should_raise([], ["continuity"], {"continuity"}) is True
    assert critical_parse_failure_should_raise([object()], ["continuity"], {"continuity"}) is False
    assert critical_parse_failure_should_raise([], ["prose"], {"continuity"}) is False


V1C001_OPEN = "场记板上的墨迹没干透，我用拇指抹了一下：第三十二场。"
V1C002_OPEN = "林朔把凉透的茶水搁在椅脚边，手心还攥着杯壁。"


def test_chapter_index_from_key() -> None:
    assert chapter_index_from_key("v1c001") == 1
    assert chapter_index_from_key("v1c013") == 13
    assert chapter_index_from_key("nope") is None


def test_first_person_dominant_is_not_lockable_when_pov_is_name() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    prose = _long_prose() + V1C001_OPEN * 10
    assert is_usable_draft(prose)
    assert is_lockable_draft(prose, [], ["林朔"], gates) is False
    assert pick_lockable_candidate([_candidate("candidate_1", prose)], [], ["林朔"], gates) is None


def test_first_person_dominant_not_lockable_even_when_name_appears() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    prose = _long_prose() + "林朔还在场。" + V1C001_OPEN * 10
    assert "林朔" in prose
    assert is_usable_draft(prose)
    assert is_lockable_draft(prose, [], ["林朔"], gates) is False


def test_third_person_linshuo_still_lockable() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    prose = _long_prose() + "林朔盯着监视器。兆薇从化妆间出来。" * 5
    v1c002 = _long_prose() + V1C002_OPEN * 10
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True
    assert is_lockable_draft(v1c002, [], ["林朔"], gates) is True
    picked = pick_lockable_candidate([_candidate("candidate_1", prose)], [], ["林朔"], gates)
    assert picked is not None


def test_pov_gate_skipped_when_gates_omitted() -> None:
    prose = _long_prose() + V1C001_OPEN * 10
    assert is_usable_draft(prose)
    assert pick_lockable_candidate([_candidate("candidate_1", prose)], []) is not None


def test_judge_pass_on_first_person_dominant_does_not_lock_without_sibling() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    leaked = _candidate("candidate_1", _long_prose() + V1C001_OPEN * 10)
    verdict = JudgeVerdict.model_validate(
        {
            "verdict": "PASS",
            "selected_candidate": "candidate_1",
            "reasoning_summary": "PASS",
        }
    )
    out = enforce_lockable_verdict(verdict, [leaked], [], ["林朔"], gates)
    assert out.verdict is VerdictType.HUMAN_REVIEW


def test_judge_pass_on_first_person_picks_third_person_sibling() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    leaked = _candidate("candidate_1", _long_prose() + V1C001_OPEN * 10)
    clean = _candidate(
        "candidate_2",
        _long_prose() + "林朔盯着监视器。兆薇从化妆间出来。" * 5,
    )
    verdict = JudgeVerdict.model_validate(
        {
            "verdict": "PASS",
            "selected_candidate": "candidate_1",
            "reasoning_summary": "PASS",
        }
    )
    out = enforce_lockable_verdict(verdict, [leaked, clean], [], ["林朔"], gates)
    assert out.verdict is VerdictType.PASS
    assert out.selected_candidate == "candidate_2"


XU_JIE = "王师傅说，徐姐那边在找能看粗剪的人"
INTERN = "北影厂实习场记的通告单背在兜里硌着胯骨。"


def _linshuo_pad(extra: str) -> str:
    return _long_prose() + "林朔盯着监视器。" + extra


def test_xujie_adjacency_and_intern_clapper_are_not_lockable() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    assert has_hard_gate_leak(XU_JIE) is True

    xujie = _linshuo_pad(XU_JIE)
    assert is_usable_draft(xujie)
    assert is_lockable_draft(xujie, [], ["林朔"], gates) is False

    xujinglei = _linshuo_pad("许静蕾走进来")
    assert is_lockable_draft(xujinglei, [], ["林朔"], gates) is True

    zhang = _linshuo_pad("章子怡走进来")
    assert is_lockable_draft(zhang, [], ["林朔"], gates) is False

    zhoujie = _linshuo_pad("周姐把通告递过来。")
    assert is_lockable_draft(zhoujie, [], ["林朔"], gates) is True

    intern = _linshuo_pad(INTERN)
    assert has_hard_gate_leak(INTERN) is True
    assert is_lockable_draft(intern, [], ["林朔"], gates) is False

    laoshi = _linshuo_pad("李老师在棚顶换泡")
    assert is_lockable_draft(laoshi, [], ["林朔"], gates) is True

    tokens = _HARD_GATE_LEAK_RE.pattern.split("|")
    assert "笔记" not in _HARD_GATE_LEAK_RE.pattern
    assert "左眼" not in tokens
    assert "左眼花" in tokens
    assert "左眼薄雾" in tokens

    leaked = _candidate("candidate_1", xujie)
    clean = _candidate("candidate_2", _linshuo_pad("兆薇从化妆间出来。"))
    picked = pick_sole_lockable_candidate([leaked, clean], [], ["林朔"], gates)
    assert picked is not None and picked.candidate_id == "candidate_2"


MECH_C001 = "我没解释我为什么会知道这个焦段在这个距离上是对的。"
MECH_C005A = "他不能解释自己为什么会按电视剧节拍贴。"
MECH_C005B = "他不写笔记。"
OK_NOTEBOOK = "他把场记本合上，通告单还在监视器边上。"


def test_mechanism_naming_is_not_lockable_but_bare_notebook_is() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    for phrase in (MECH_C001, MECH_C005A, MECH_C005B):
        prose = _linshuo_pad(phrase)
        assert is_usable_draft(prose)
        assert is_lockable_draft(prose, [], ["林朔"], gates) is False

    notebook = _linshuo_pad(OK_NOTEBOOK)
    assert is_lockable_draft(notebook, [], ["林朔"], gates) is True
    assert has_hard_gate_leak(OK_NOTEBOOK) is False
    assert has_hard_gate_leak("他不写笔记") is False
    assert is_lockable_draft(_linshuo_pad("他不写笔记。"), [], ["林朔"], gates) is False
    assert "笔记" not in _HARD_GATE_LEAK_RE.pattern

    unsaid = _linshuo_pad("林朔说，我没说今晚改机位。")
    assert is_lockable_draft(unsaid, [], ["林朔"], gates) is True

    leaked = _candidate("candidate_1", _linshuo_pad(MECH_C005B))
    clean = _candidate("candidate_2", _linshuo_pad("兆薇从化妆间出来。"))
    picked = pick_sole_lockable_candidate([leaked, clean], [], ["林朔"], gates)
    assert picked is not None and picked.candidate_id == "candidate_2"


BODY = (
    "右耳还带着下午在棚里被散光灯烤过的嗡声，不重。我听见自己的心跳——"
    "不是紧张，是一种从来没有过的眩晕。"
)
SHAKE = (
    "手还在抖。不是冷的那种抖，是肾上腺素退潮之后肌肉自己找平衡的那种。"
)


def test_body_cost_gated_only_in_early_chapters() -> None:
    early = LockGates(pov="林朔", required_names=["林朔"], chapter_index=1)
    late = LockGates(pov="林朔", required_names=["林朔"], chapter_index=4)
    skipped = LockGates(pov="林朔", required_names=["林朔"], chapter_index=None)
    body = _linshuo_pad(BODY)
    shake = _linshuo_pad(SHAKE)
    assert is_usable_draft(body)
    assert is_lockable_draft(body, [], ["林朔"], early) is False
    assert is_lockable_draft(body, [], ["林朔"], late) is True
    assert is_lockable_draft(shake, [], ["林朔"], early) is True
    assert is_lockable_draft(body, [], ["林朔"], skipped) is True

    leaked = _candidate("candidate_1", body)
    clean = _candidate("candidate_2", _linshuo_pad("兆薇从化妆间出来。"))
    picked = pick_sole_lockable_candidate([leaked, clean], [], ["林朔"], early)
    assert picked is not None and picked.candidate_id == "candidate_2"


SCHEDULE = [
    (1, "片场最底层的十分钟林朔在古装权谋剧组救场林朔"),
    (2, "副助的第一次单机位兆薇在杀青戏前林朔"),
    (3, "樊冰屏的预算表林朔赴约樊冰屏林朔"),
    (4, "封闭空间开机夜林朔在监视器前林朔"),
    (5, "粗剪室里的人许静蕾临时拽来林朔"),
    (13, "黎冰屏的旧伤黎冰屏林朔"),
]
CARDS = ["林朔", "樊冰屏", "周洵", "许静蕾", "兆薇", "张紫衣", "柳奕妃", "黎冰屏"]
LI_LINE = "动作分包黎冰屏靠在墙上。下一场女演员拖行是她的活"


def test_unscheduled_character_too_early_is_not_lockable() -> None:
    early = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=4,
        card_names=CARDS,
        schedule=SCHEDULE,
    )
    li = _linshuo_pad(LI_LINE)
    assert is_usable_draft(li)
    assert is_lockable_draft(li, [], ["林朔"], early) is False

    zhaowei = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=1,
        card_names=CARDS,
        schedule=SCHEDULE,
    )
    assert is_lockable_draft(_linshuo_pad("兆薇从化妆间出来。"), [], ["林朔"], zhaowei) is True

    fan = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=2,
        card_names=CARDS,
        schedule=SCHEDULE,
    )
    assert is_lockable_draft(_linshuo_pad("樊冰屏把预算表放下。"), [], ["林朔"], fan) is True

    # 禁写项整句出现在正文里才拦；人名只是禁写项的子串不整章封杀。
    phrase_hit = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=5,
        card_names=CARDS,
        schedule=SCHEDULE,
        reveal_forbidden=["许静蕾看过笔记"],
    )
    assert (
        is_lockable_draft(
            _linshuo_pad("许静蕾看过笔记。她把本子合上。"), [], ["林朔"], phrase_hit
        )
        is False
    )
    assert is_lockable_draft(_linshuo_pad("许静蕾走进来。"), [], ["林朔"], phrase_hit) is True

    # 张紫衣从未进过 schedule 仍算未排期。
    zhang = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=9,
        card_names=CARDS,
        schedule=SCHEDULE,
        reveal_forbidden=["张紫衣反派戏终局"],
    )
    assert (
        is_lockable_draft(
            _linshuo_pad("张紫衣背对着片场大门站着。"), [], ["林朔"], zhang
        )
        is False
    )

    # 张紫衣已排期时，禁写项里带她的名字不封杀登场。
    zhang_on = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=9,
        card_names=CARDS,
        schedule=SCHEDULE + [(7, "反派戏张紫衣档期侧写张紫衣林朔")],
        reveal_forbidden=["张紫衣反派戏终局"],
    )
    assert (
        is_lockable_draft(
            _linshuo_pad("张紫衣背对着片场大门站着。"), [], ["林朔"], zhang_on
        )
        is True
    )

    skipped = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=4,
        card_names=CARDS,
        schedule=None,
    )
    assert is_lockable_draft(li, [], ["林朔"], skipped) is True

    leaked = _candidate("candidate_1", li)
    clean = _candidate("candidate_2", _linshuo_pad("兆薇从化妆间出来。"))
    picked = pick_sole_lockable_candidate([leaked, clean], [], ["林朔"], early)
    assert picked is not None and picked.candidate_id == "candidate_2"


def _annals_gates(year: int, titles: list[str], phrases: list[str] | None = None) -> LockGates:
    return LockGates(
        required_names=["林朔"],
        pov="林朔",
        annals_year=year,
        forbidden_titles=titles,
        forbidden_section_phrases=phrases or ["柏林一种关注", "戛纳年初"],
    )


def test_future_title_活埋_not_lockable_in_2005() -> None:
    gates = _annals_gates(2005, ["活埋", "小偷家族", "海边的曼彻斯特", "调音师", "入殓师"])
    prose = _long_prose() + "林朔盯着监视器。他想起《活埋》。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is False


def test_future_title_thief_family_and_manchester() -> None:
    gates = _annals_gates(2005, ["活埋", "小偷家族", "海边的曼彻斯特", "调音师", "入殓师"])
    thief = _long_prose() + "林朔说《小偷家族》已经拿了金棕榈。"
    manchester = _long_prose() + "林朔说《海边的曼彻斯特》拿了剧本奖。"
    tuner = _long_prose() + "林朔说《调音师》那种听音的办法。"
    assert is_lockable_draft(thief, [], ["林朔"], gates) is False
    assert is_lockable_draft(manchester, [], ["林朔"], gates) is False
    assert is_lockable_draft(tuner, [], ["林朔"], gates) is False


def test_departures_typo_is_fenced() -> None:
    gates = _annals_gates(2005, ["入殓师"])
    assert is_lockable_draft(_long_prose() + "林朔提了入殓师。", [], ["林朔"], gates) is False
    assert is_lockable_draft(_long_prose() + "林朔提了入检师。", [], ["林朔"], gates) is False


def test_1997_event_horizon_not_fenced() -> None:
    gates = _annals_gates(2005, ["活埋"])
    prose = _long_prose() + "林朔说《黑洞》那种1997年的封闭空间。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True


def test_lin_shuo_original_title_not_blocked() -> None:
    gates = _annals_gates(2005, ["活埋"])
    prose = _long_prose() + "林朔把《场记板》这个自己的名字写在通告上。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True


def test_berlin_un_certain_regard_not_lockable() -> None:
    gates = _annals_gates(2007, ["活埋"], ["柏林一种关注", "戛纳年初"])
    prose = _long_prose() + "林朔站在柏林一种关注放映厅门口。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is False


def test_cannes_plus_early_year_not_lockable_but_cannes_alone_ok() -> None:
    gates = _annals_gates(2008, ["活埋"], ["柏林一种关注", "戛纳年初"])
    early = _long_prose() + "林朔去戛纳，年初机票就订了。"
    may = _long_prose() + "林朔去戛纳，5月的阳光很白。"
    assert is_lockable_draft(early, [], ["林朔"], gates) is False
    assert is_lockable_draft(may, [], ["林朔"], gates) is True


def test_clean_2005_prose_still_lockable() -> None:
    gates = _annals_gates(2005, ["活埋", "小偷家族"])
    prose = _long_prose() + "手贴上去的时候没有犹豫。林朔盯着监视器。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True


def test_annals_gate_skipped_when_gates_omitted() -> None:
    prose = _long_prose() + "他想起《活埋》。林朔盯着监视器。"
    assert is_lockable_draft(prose, [], ["林朔"]) is True
