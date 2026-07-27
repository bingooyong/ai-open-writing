"""M1.1 DoD:每个 Schema 的有效/非法样例;JSON Schema 可导出;裁决一致性校验。"""

import pytest
from pydantic import ValidationError

from novel_agent.domain.schemas import (
    CanonDelta,
    ChapterContextPackage,
    ChapterOutline,
    CharacterCard,
    DraftCandidate,
    EntityStateChange,
    JudgeVerdict,
    PlotUnitCard,
    RelationshipChange,
    ReviewIssue,
    SceneCard,
    StoryKernel,
    VerdictType,
)

# ---------- 共享有效样例(测试与后续 fixture 复用) ----------

KERNEL = dict(
    premise="如果一个说书人发现自己讲的故事会成真",
    logline="落魄说书人为救妹妹,用会成真的故事对抗操纵命运的书局",
    theme_question="讲故事的人有没有权力改写别人的命运",
    dramatic_question="他能否在不牺牲无辜者的前提下救回妹妹",
    value_shift="从逃避责任到承担叙述的代价",
    ending_proof="他烧掉能成真的书,用凡人方式完成救赎",
    reader_promise="每卷一个成真故事引发的连锁危机与反转",
)

CHARACTER = dict(
    character_id="ch_su",
    name="苏晚生",
    identity="临安城茶楼说书人",
    story_function="主角",
    external_goal="赎回被书局扣押的妹妹",
    internal_need="承认自己无法置身故事之外",
    motivation="妹妹是他唯一亲人",
    fear="自己的话害死无辜者",
    start_state="只求糊口、回避是非",
    end_state="接受叙述者的责任",
)

UNIT = dict(
    unit_id="u1",
    position_in_volume="第一卷开局单元(1-5章)",
    promise_or_debt="兑现'故事成真'的核心设定展示",
    trigger="随口编的失火故事次日成真",
    protagonist_goal="查明故事为何成真并撇清嫌疑",
    opposition="书局执事以纵火案胁迫他签约",
    escalation_beats=["成真范围扩大", "官府介入", "妹妹被扣为质"],
    midpoint_change="发现书局早知他的能力",
    irreversible_choice="签下卖身契换妹妹平安",
    climax="第一次主动讲述一个救人的故事",
    payoff="能力规则首次明确:代价由讲述者承担",
)

OUTLINE = dict(
    chapter_key="v1c001",
    volume_id="v1",
    unit_id="u1",
    core_event="说书人随口编的故事一夜成真",
    pov="苏晚生",
    time_location="临安城,春夜茶楼",
    protagonist_goal="讲完今晚的书换到赏钱",
    key_choice="为博彩头临场编造失火桥段",
    start_state="穷困但平静",
    end_state="被卷入失火案,平静破碎",
    emotion_shift="轻快→惊惧",
    entry_point="茶楼满座,他抛出新故事",
    exit_hook="衙役上门:昨夜西市果然失火",
    target_words=3000,
)

SCENE = dict(
    scene_id="v1c001_s1",
    chapter_key="v1c001",
    pov="苏晚生",
    time="春夜",
    location="临安茶楼",
    entry_state="听众渐散,赏钱寥寥",
    goal="用新桥段留住客人",
    obstacle="老听客嫌故事陈旧起哄",
    stakes="今晚赏钱与说书名声",
    turning_point="他临场编出西市失火的新段子",
    choice="不顾忌讳把火写到真实街巷",
    outcome="满堂彩,赏钱翻倍",
    emotional_shift="窘迫→得意",
    word_budget=1200,
)


def _issue(**over: object) -> dict:
    d = dict(
        issue_id="i1",
        reviewer_role="continuity",
        claim="主角在第2场景使用了他不可能知道的信息",
        evidence=[{"scene_id": "v1c001_s1", "quote": "他早知道西市的布局"}],
        violated_rule="POV 信息边界(章纲 reveal_forbidden)",
        hard_gate="info_violation",
        severity="P0",
        failure_consequence="读者发现主角未卜先知,信息线崩塌",
        recommended_rollback_level="scene_card",
        confidence=0.9,
    )
    d.update(over)
    return d


# ---------- 有效样例逐一构造 ----------


@pytest.mark.parametrize(
    ("cls", "data"),
    [
        (StoryKernel, KERNEL),
        (CharacterCard, CHARACTER),
        (PlotUnitCard, UNIT),
        (ChapterOutline, OUTLINE),
        (SceneCard, SCENE),
        (ReviewIssue, _issue()),
    ],
)
def test_valid_samples(cls: type, data: dict) -> None:
    obj = cls.model_validate(data)
    assert obj.schema_version == "1.0"
    # JSON Schema 可导出(DoD)
    assert cls.model_json_schema()["type"] == "object"


# ---------- 非法样例:必填缺失 / 越界 / 未知字段 ----------


def test_missing_required_rejected() -> None:
    bad = dict(KERNEL)
    del bad["ending_proof"]
    with pytest.raises(ValidationError):
        StoryKernel.model_validate(bad)


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        SceneCard.model_validate({**SCENE, "totally_unknown": 1})


def test_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate(_issue(confidence=1.5))


def test_candidate_id_blinded_pattern() -> None:
    ok = dict(
        candidate_id="candidate_1",
        chapter_key="v1c001",
        scenes=[{"scene_id": "v1c001_s1", "content": "夜里茶楼灯火未熄。"}],
        chapter_summary="说书人编的故事成真",
    )
    assert DraftCandidate.model_validate(ok).full_text().startswith("夜里")
    with pytest.raises(ValidationError):
        DraftCandidate.model_validate({**ok, "candidate_id": "writer_a"})  # 泄漏身份


# ---------- JudgeVerdict 一致性(PRD §9.4) ----------


def _verdict(**over: object) -> dict:
    d = dict(
        verdict="PASS",
        selected_candidate="candidate_1",
        reasoning_summary="无硬门禁失败,软问题不足以阻断",
    )
    d.update(over)
    return d


def test_pass_with_hard_gate_rejected() -> None:
    with pytest.raises(ValidationError, match="硬门禁"):
        JudgeVerdict.model_validate(_verdict(hard_gate_failures=["canon_conflict"]))


def test_revise_local_requires_scope() -> None:
    with pytest.raises(ValidationError, match="revision_scope"):
        JudgeVerdict.model_validate(_verdict(verdict="REVISE_LOCAL"))
    ok = JudgeVerdict.model_validate(
        _verdict(verdict="REVISE_LOCAL", revision_scope=["v1c001_s1"])
    )
    assert ok.verdict == VerdictType.REVISE_LOCAL


def test_replan_requires_rollback_target() -> None:
    with pytest.raises(ValidationError, match="rollback_target"):
        JudgeVerdict.model_validate(_verdict(verdict="REPLAN_SCENE"))


# ---------- CanonDelta 与上下文包 ----------


def test_canon_delta_and_context_provisional() -> None:
    delta = CanonDelta.model_validate(
        dict(
            chapter_key="v1c001",
            base_canon_version="canon_v0",
            character_state_changes=[
                EntityStateChange(
                    entity_id="ch_su",
                    state_type="status",
                    new_value="被官府列为失火案关联人",
                    reason="衙役上门问话",
                ).model_dump()
            ],
            relationship_changes=[
                RelationshipChange(
                    parties=["ch_su", "ch_shuju"],
                    from_state="陌生",
                    to_state="试探",
                    evidence="书局执事旁听说书并留下名帖",
                ).model_dump()
            ],
        )
    )
    assert delta.character_state_changes[0].entity_id == "ch_su"

    pkg = ChapterContextPackage.model_validate(
        dict(
            chapter_key="v1c002",
            canon_version="canon_v1",
            task_brief="写第二章",
            outline={**OUTLINE, "chapter_key": "v1c002"},
            scene_cards=[{**SCENE, "scene_id": "v1c002_s1", "chapter_key": "v1c002"}],
            kernel_summary="说书人故事成真",
            volume_summary="第一卷:入局",
            unit_card=UNIT,
            hard_constraints=[
                {"content": "苏晚生已被列为关联人", "provisional": True, "source_chapter": "v1c001"}
            ],
        )
    )
    assert pkg.has_provisional() is True  # D15:STALE 级联判定依据
