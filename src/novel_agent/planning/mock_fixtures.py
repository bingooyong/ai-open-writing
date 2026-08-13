"""规划链 mock 产物:离线走通 kernel / 角色 / 滚动 5 章,不访问网络。"""

from __future__ import annotations

import json

from novel_agent.gateway.providers.mock import MockProvider

_KERNEL_BASE = dict(
    premise="如果一个说书人发现自己讲的故事会成真",
    logline="落魄说书人为救妹妹,用会成真的故事对抗操纵命运的书局",
    theme_question="讲故事的人有没有权力改写别人的命运",
    dramatic_question="他能否在不牺牲无辜者的前提下救回妹妹",
    value_shift="从逃避责任到承担叙述的代价",
    ending_proof="他烧掉能成真的书,用凡人方式完成救赎",
    reader_promise="每卷一个成真故事引发的连锁危机与反转",
    expectation_debts=["开篇即展示故事成真的代价"],
    do_not_write=["禁无代价全能", "禁无故虐杀"],
)

PLANNING_KERNELS: list[dict] = [
    _KERNEL_BASE,
    {
        **_KERNEL_BASE,
        "premise": "如果书局用别人的命运当纸墨",
        "logline": "书局学徒偷出禁书,想改写被写成炮灰的故人",
        "theme_question": "被写成故事的人能否夺回自己的结局",
        "dramatic_question": "学徒能否在被写成反派之前救出故人",
        "value_shift": "从服从叙事到撕毁剧本",
        "ending_proof": "他在终章空白处写下自己的真名并停笔",
        "reader_promise": "纸上生死与城中巷战交错的权谋奇幻",
    },
    {
        **_KERNEL_BASE,
        "premise": "如果听众才是故事成真的燃料",
        "logline": "茶楼老板娘发现满堂喝彩会把评书写进现实,她要关掉这座城的耳朵",
        "theme_question": "被观看是否等于被决定",
        "dramatic_question": "她能否在不让城市失声的前提下切断成真",
        "value_shift": "从取悦听众到拒绝被观看",
        "ending_proof": "她把最后一场书讲成沉默,城市第一次自己做选择",
        "reader_promise": "市井声口与命运契约的对照实验",
    },
]

PLANNING_CHARACTERS: list[dict] = [
    dict(
        character_id="ch_su",
        name="苏晚生",
        identity="临安城茶楼说书人",
        story_function="主角",
        external_goal="赎回被书局扣押的妹妹",
        internal_need="承认自己无法置身故事之外",
        motivation="妹妹是他唯一亲人",
        fear="自己的话害死无辜者",
        misbelief="只要不认真讲,故事就不会伤人",
        start_state="只求糊口、回避是非",
        end_state="接受叙述者的责任",
        strengths=["临场编造", "市井耳目"],
        flaws=["逃避", "嘴快"],
        red_lines=["出卖妹妹"],
    ),
    dict(
        character_id="ch_shuju",
        name="霍执事",
        identity="书局外务执事",
        story_function="对手",
        external_goal="把苏晚生签进书局当活字",
        internal_need="证明自己不是可替换的笔",
        motivation="书局许他一页改命的纸",
        fear="被写成无名配角",
        misbelief="掌控别人的故事就能掌控自己的结局",
        start_state="冷静收网、礼貌胁迫",
        end_state="发现自己也是书中人",
        strengths=["情报", "契约"],
        flaws=["把人当素材"],
        red_lines=["当众撕毁书局律令"],
    ),
]

PLANNING_RELATIONSHIPS: list[dict] = [
    dict(
        parties=["ch_su", "ch_shuju"],
        state="胁迫与试探",
        evidence="书局执事以纵火案上门,逼他在契约上签字",
    ),
]

PLANNING_STRUCTURE: dict = dict(
    template="three_act",
    inciting_incident=dict(summary="随口编的失火故事成真", chapter_key="v1c001", volume_id="v1"),
    commitment=dict(summary="为救妹妹签下卖身契", chapter_key="v1c004", volume_id="v1"),
    midpoint=dict(summary="发现书局早知他的能力", chapter_key="v1c003", volume_id="v1"),
    all_is_lost=dict(summary="妹妹被扣为人质", chapter_key="v1c004", volume_id="v1"),
    climax=dict(summary="第一次主动讲救人的故事", chapter_key="v1c005", volume_id="v1"),
    resolution=dict(summary="代价规则首次明确", chapter_key="v1c005", volume_id="v1"),
    golden_three=[
        dict(
            promise="主角当场面对会成真的评书",
            escalation="西市失火牵连他",
            payoff_or_hook="衙役上门留下危机",
        ),
        dict(
            promise="压力落到证人与名声",
            escalation="书局执事现身",
            payoff_or_hook="纵火案成为把柄",
        ),
        dict(
            promise="小闭环:他必须开口或封口",
            escalation="签约胁迫升级",
            payoff_or_hook="新问题:妹妹安危",
        ),
    ],
)

PLANNING_CONFLICTS: list[dict] = [
    dict(
        conflict_id="cf_sign",
        kind="interest",
        parties=["ch_su", "ch_shuju"],
        stake="是否签入书局",
        temperature="rising",
        must_affect="both",
        payoff_chapter_key="v1c005",
    ),
    dict(
        conflict_id="cf_voice",
        kind="value",
        parties=["ch_su"],
        stake="讲真话还是保命",
        temperature="setup",
        must_affect="plot",
        payoff_chapter_key="v1c003",
    ),
    dict(
        conflict_id="cf_time",
        kind="time",
        parties=["ch_su", "ch_shuju"],
        stake="天亮前必须给出答复",
        temperature="peak",
        must_affect="plot",
        payoff_chapter_key="v1c004",
    ),
]

PLANNING_PAYOFFS: list[dict] = [
    dict(
        beat_id="pb_micro1",
        scale="micro",
        kind="reveal",
        pressure_before="听众起哄嫌旧",
        hit="临场新段子满堂彩",
        chapter_key="v1c001",
        order_index=1,
    ),
    dict(
        beat_id="pb_small1",
        scale="small",
        kind="face-slap",
        pressure_before="被当众点名纵火",
        hit="证人反而证明他在茶楼",
        chapter_key="v1c002",
        order_index=2,
    ),
    dict(
        beat_id="pb_small2",
        scale="small",
        kind="bond",
        pressure_before="执事礼貌胁迫",
        hit="他看清对方也怕被写成配角",
        chapter_key="v1c003",
        order_index=3,
    ),
    dict(
        beat_id="pb_large1",
        scale="large",
        kind="reversal",
        pressure_before="妹妹被扣为人质",
        hit="他签契换来一线生机",
        chapter_key="v1c004",
        order_index=4,
    ),
    dict(
        beat_id="pb_large2",
        scale="large",
        kind="power",
        pressure_before="第一次主动讲述的代价压顶",
        hit="救人故事成真且规则显形",
        chapter_key="v1c005",
        order_index=5,
    ),
]

_CITATIONS = (
    (["cf_voice"], ["pb_micro1"]),
    (["cf_sign"], ["pb_small1"]),
    (["cf_voice"], ["pb_small2"]),
    (["cf_time"], ["pb_large1"]),
    (["cf_sign"], ["pb_large2"]),
)

_UNIT = dict(
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
    aftermath="他成为书局名义上的说书人",
    new_debt="妹妹仍在书局,下一卷必须还清故事债",
    canon_constraints=["不得提前揭示书局真正主人", "不得让能力无代价"],
)


def _chapter(n: int) -> dict:
    key = f"v1c{n:03d}"
    events = (
        "说书人随口编的故事一夜成真",
        "西市余烬里出现听过评书的证人",
        "书局执事以纵火案上门",
        "妹妹被扣为人质",
        "他第一次主动讲一个救人的故事",
    )
    return dict(
        chapter_key=key,
        volume_id="v1",
        unit_id="u1",
        title=f"第{n}章",
        core_event=events[n - 1],
        pov="苏晚生",
        time_location=f"临安城,第{n}日",
        protagonist_goal="在不被写成罪人的前提下活过今晚",
        key_choice="选择继续讲还是封口",
        start_state="尚未看清代价",
        end_state="被迫前进一步",
        emotion_shift="侥幸→收紧",
        entry_point="茶楼或街巷的可见事件",
        exit_hook="下一层压力露出边角",
        target_words=3000,
        reveal_forbidden=["书局主人真名"],
        cited_conflict_ids=_CITATIONS[(n - 1) % len(_CITATIONS)][0],
        cited_beat_ids=_CITATIONS[(n - 1) % len(_CITATIONS)][1],
    )


def _scenes(n: int) -> list[dict]:
    key = f"v1c{n:03d}"
    return [
        dict(
            scene_id=f"{key}_s1",
            chapter_key=key,
            pov="苏晚生",
            time="日间",
            location="临安茶楼或街巷",
            entry_state="压力尚未落地",
            goal="弄清眼前变故",
            obstacle="证人、捕快或执事挡路",
            stakes="名声与人身安全",
            turning_point="他意识到评书与现实对上了",
            choice="承认或抵赖",
            outcome="局势更紧",
            emotional_shift="侥幸→发冷",
            word_budget=1400,
        ),
        dict(
            scene_id=f"{key}_s2",
            chapter_key=key,
            pov="苏晚生",
            time="入夜",
            location="茶楼后巷或书局门口",
            entry_state="已经无法装傻",
            goal="把伤害从妹妹身上挪开",
            obstacle="对方握有把柄",
            stakes="亲人安危",
            turning_point="他必须决定下一句讲不讲",
            choice="开口或沉默",
            outcome="本章压力落地并留下钩子",
            emotional_shift="发冷→咬牙",
            word_budget=1600,
        ),
    ]


def planning_outline_payload(chapters_needed: int = 5) -> dict:
    outlines = [_chapter(i) for i in range(1, chapters_needed + 1)]
    scene_cards = [card for i in range(1, chapters_needed + 1) for card in _scenes(i)]
    return {"unit": _UNIT, "outlines": outlines, "scene_cards": scene_cards}


def kernel_candidate_payload() -> dict:
    return {
        "candidates": PLANNING_KERNELS,
        "differentiation_notes": "题材切入分别为说书人改命、学徒夺笔、听众即燃料,冲突结构不同",
    }


def register_planning_defaults(mock: MockProvider) -> None:
    """为 mock provider 注册规划链三角色的合法 JSON 回包。"""
    mock.register(
        "kernel_planner",
        lambda _req: json.dumps(kernel_candidate_payload(), ensure_ascii=False),
    )
    mock.register(
        "character_planner",
        lambda _req: json.dumps(
            {
                "characters": PLANNING_CHARACTERS,
                "relationship_proposals": PLANNING_RELATIONSHIPS,
            },
            ensure_ascii=False,
        ),
    )
    mock.register(
        "structure_planner",
        lambda _req: json.dumps(PLANNING_STRUCTURE, ensure_ascii=False),
    )
    mock.register(
        "conflict_planner",
        lambda _req: json.dumps({"conflicts": PLANNING_CONFLICTS}, ensure_ascii=False),
    )
    mock.register(
        "payoff_planner",
        lambda _req: json.dumps({"beats": PLANNING_PAYOFFS}, ensure_ascii=False),
    )
    mock.register(
        "outline_planner",
        lambda _req: json.dumps(planning_outline_payload(), ensure_ascii=False),
    )
    mock.register(
        "concept_judge",
        lambda _req: json.dumps(
            {
                "verdict": "PASS",
                "after_round": "R2",
                "reasons": ["内核与黄金三章可以支撑开书"],
                "repair_notes": "",
                "repair_attempted": False,
            },
            ensure_ascii=False,
        ),
    )
