"""Story Bible 契约:schema、仓储、lint、规划对话与 CLI。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from novel_agent.domain.schemas.structure import (
    Conflict,
    GoldenThreeChapter,
    IdentityAlias,
    PayoffBeat,
    StoryBrief,
    StructureBeat,
    StructureMap,
)

_BEAT = dict(summary="开场承诺被打破")
_GOLDEN = dict(
    promise="主角当场面对会成真的评书",
    escalation="代价落到身边人",
    payoff_or_hook="小闭环后留下新问",
)


def _structure_map(**over: object) -> dict:
    data = dict(
        inciting_incident=_BEAT,
        commitment=_BEAT,
        midpoint=_BEAT,
        all_is_lost=_BEAT,
        climax=_BEAT,
        resolution=_BEAT,
        golden_three=[_GOLDEN, _GOLDEN, _GOLDEN],
    )
    data.update(over)
    return data


def test_story_brief_and_structure_map_validate() -> None:
    brief = StoryBrief.model_validate(dict(spark="说书人发现故事会成真"))
    assert brief.genre == ""
    assert brief.audience == ""
    assert brief.do_not_write == []

    smap = StructureMap.model_validate(_structure_map())
    assert smap.template == "three_act"
    assert len(smap.golden_three) == 3
    assert isinstance(smap.inciting_incident, StructureBeat)
    assert isinstance(smap.golden_three[0], GoldenThreeChapter)


def test_golden_three_must_have_exactly_three_chapters() -> None:
    with pytest.raises(ValidationError):
        StructureMap.model_validate(_structure_map(golden_three=[_GOLDEN, _GOLDEN]))
    with pytest.raises(ValidationError):
        StructureMap.model_validate(_structure_map(golden_three=[_GOLDEN] * 4))


def test_conflict_rejects_invalid_kind() -> None:
    base = dict(
        conflict_id="cf_1",
        kind="interest",
        parties=["ch_su", "ch_shuju"],
        stake="签约与否",
        temperature="setup",
        must_affect="both",
        payoff_chapter_key="v1c005",
    )
    Conflict.model_validate(base)
    with pytest.raises(ValidationError):
        Conflict.model_validate({**base, "kind": "plot"})


def test_payoff_beat_requires_chapter_key_or_unit_id() -> None:
    base = dict(
        beat_id="pb_1",
        scale="small",
        kind="reveal",
        pressure_before="被当众点名纵火",
        hit="当众讲出成真规则的一角",
        order_index=1,
    )
    with pytest.raises(ValidationError):
        PayoffBeat.model_validate(base)
    PayoffBeat.model_validate({**base, "chapter_key": "v1c003"})
    PayoffBeat.model_validate({**base, "unit_id": "u1"})


def test_identity_alias_validates() -> None:
    alias = IdentityAlias.model_validate(
        dict(canonical_character_id="ch_su", alias="苏说书的")
    )
    assert alias.alias == "苏说书的"
