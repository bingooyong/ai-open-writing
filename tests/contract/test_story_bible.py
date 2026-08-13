"""Story Bible 契约:schema、仓储、lint、规划对话与 CLI。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from test_schemas import CHARACTER, KERNEL, OUTLINE

from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import BibleRepo, PlanningRepo
from novel_agent.domain.schemas import (
    ChapterOutline,
    CharacterCard,
    Conflict,
    IdentityAlias,
    PayoffBeat,
    StoryBrief,
    StoryKernel,
    StructureMap,
)
from novel_agent.domain.schemas.structure import GoldenThreeChapter, StructureBeat

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


def _conflict(**over: object) -> dict:
    data = dict(
        conflict_id="cf_1",
        kind="interest",
        parties=["ch_su", "ch_shuju"],
        stake="签约与否",
        temperature="setup",
        must_affect="both",
        payoff_chapter_key="v1c005",
    )
    data.update(over)
    return data


def _payoff(**over: object) -> dict:
    data = dict(
        beat_id="pb_1",
        scale="small",
        kind="reveal",
        pressure_before="被当众点名纵火",
        hit="当众讲出成真规则的一角",
        chapter_key="v1c003",
        order_index=1,
    )
    data.update(over)
    return data


@pytest.fixture()
def engine(tmp_path):
    e = build_engine(tmp_path / "bible.db")
    create_all(e)
    return e


def test_bible_repo_crud_and_round_complete(engine) -> None:
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        bible = BibleRepo(session)
        pid = planning.create_project("说书人传奇", boundaries=["禁无代价全能"]).id

        assert bible.round_complete(pid) == set()
        assert bible.get_brief(pid) is None
        assert bible.get_structure_map(pid) is None

        brief = StoryBrief(
            spark="说书人发现故事会成真",
            do_not_write=["禁无代价全能"],
        )
        bible.save_brief(pid, brief)
        loaded = bible.get_brief(pid)
        assert loaded is not None
        assert loaded.spark == brief.spark
        assert "R0" in bible.round_complete(pid)

        planning.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(pid, 1)
        assert {"R0", "R1"} <= bible.round_complete(pid)

        smap = StructureMap.model_validate(_structure_map())
        bible.save_structure_map(pid, smap)
        assert bible.get_structure_map(pid).golden_three[0].promise == _GOLDEN["promise"]
        assert {"R0", "R1", "R2"} <= bible.round_complete(pid)

        planning.upsert_character(pid, CharacterCard.model_validate(CHARACTER))
        assert {"R0", "R1", "R2", "R3"} <= bible.round_complete(pid)

        bible.replace_conflicts(pid, [Conflict.model_validate(_conflict())])
        bible.replace_payoff_beats(pid, [PayoffBeat.model_validate(_payoff())])
        assert bible.list_conflicts(pid)[0].conflict_id == "cf_1"
        assert bible.list_payoff_beats(pid)[0].beat_id == "pb_1"
        bible.replace_conflicts(pid, [Conflict.model_validate(_conflict(conflict_id="cf_2"))])
        assert [c.conflict_id for c in bible.list_conflicts(pid)] == ["cf_2"]
        assert {"R0", "R1", "R2", "R3", "R4"} <= bible.round_complete(pid)

        planning.create_chapter(pid, ChapterOutline.model_validate(OUTLINE), order_index=1)
        assert bible.round_complete(pid) == {"R0", "R1", "R2", "R3", "R4", "R5"}


def test_bible_repo_alias_cycle_and_self_map_rejected(engine) -> None:
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        bible = BibleRepo(session)
        pid = planning.create_project("异名").id

        bible.upsert_alias(pid, IdentityAlias(canonical_character_id="ch_su", alias="苏说书的"))
        assert [a.alias for a in bible.list_aliases(pid)] == ["苏说书的"]

        with pytest.raises(ValueError, match="canonical"):
            bible.upsert_alias(pid, IdentityAlias(canonical_character_id="ch_su", alias="ch_su"))

        bible.upsert_alias(pid, IdentityAlias(canonical_character_id="ch_su", alias="晚生"))
        with pytest.raises(ValueError, match="cycle"):
            bible.upsert_alias(pid, IdentityAlias(canonical_character_id="晚生", alias="ch_su"))

        bible.delete_alias(pid, "晚生")
        assert [a.alias for a in bible.list_aliases(pid)] == ["苏说书的"]


def test_store_brief_writes_project_columns_not_channel_profile(engine) -> None:
    from novel_agent.cli.main import _store_brief

    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        pid = repo.create_project("列存储").id
        _store_brief(repo, pid, "说书人发现故事会成真")
        project = repo.get_project(pid)
        assert project.brief == "说书人发现故事会成真"
        assert project.spark == "说书人发现故事会成真"
        assert "brief" not in (project.channel_profile or {})


def test_resolve_brief_migrates_channel_profile_fallback(engine) -> None:
    from novel_agent.cli.main import _resolve_brief

    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        pid = repo.create_project("回退").id
        project = repo.get_project(pid)
        project.channel_profile = {"brief": "旧渠道简报"}
        repo.s.add(project)
        resolved = _resolve_brief(repo, pid, "")
        assert resolved == "旧渠道简报"
        project = repo.get_project(pid)
        assert project.brief == "旧渠道简报"
        assert project.spark == "旧渠道简报"
