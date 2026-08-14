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


@pytest.fixture()
def cli_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from novel_agent.config import reset_settings_cache

    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    yield db_path
    reset_settings_cache()


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


def _large_payoff(beat_id: str, pressure: str, order: int) -> PayoffBeat:
    return PayoffBeat.model_validate(
        _payoff(
            beat_id=beat_id,
            scale="large",
            pressure_before=pressure,
            chapter_key=f"v1c{order:03d}",
            order_index=order,
        )
    )


def test_bible_lint_golden_three_rejects_lore_only_chapter_one() -> None:
    from novel_agent.lint.bible import lint_bible

    lore = dict(
        promise="世界观与历史沿革介绍",
        escalation="地理志与设定介绍",
        payoff_or_hook="传说考据未完",
    )
    bad = StructureMap.model_validate(_structure_map(golden_three=[lore, _GOLDEN, _GOLDEN]))
    report = lint_bible(structure=bad)
    assert not report.passed
    assert any(f.code == "golden_three" for f in report.findings)
    assert not lint_bible(structure=bad, live_names=["林暮"]).passed

    good = StructureMap.model_validate(_structure_map())
    assert lint_bible(structure=good).passed


def test_bible_lint_golden_three_accepts_named_protagonist() -> None:
    """真实 MiniMax 余烬回声:第1章用姓名+封口/停电,没有「主角」字面。"""
    from novel_agent.lint.bible import lint_bible

    named = dict(
        promise="林暮封口失败、全城停电",
        escalation="失声潮吞没街区",
        payoff_or_hook="天亮前必须找出改脸的人",
    )
    smap = StructureMap.model_validate(_structure_map(golden_three=[named, _GOLDEN, _GOLDEN]))
    assert not lint_bible(structure=smap).passed
    assert lint_bible(structure=smap, live_names=["林暮"]).passed


def test_live_names_from_kernel_reads_leadins_not_hardcoded() -> None:
    from novel_agent.lint.bible import live_names_from_kernel

    makeup = StoryKernel.model_validate(
        {
            **KERNEL,
            "logline": "化妆师林暮在停电夜必须完成封口",
            "premise": "如果封口失败会让死者重新开口",
        }
    )
    assert "林暮" in live_names_from_kernel(makeup)

    called = StoryKernel.model_validate(
        {
            **KERNEL,
            "logline": "名叫苏晚生的说书人要救妹妹",
            "premise": "如果故事会成真",
        }
    )
    called_names = live_names_from_kernel(called)
    assert "苏晚生" in called_names
    assert "林暮" not in called_names

    titled = StoryKernel.model_validate(
        {
            **KERNEL,
            "logline": "名为霍执事的人上门逼签",
            "premise": "如果命运被写成纸墨",
        }
    )
    assert "霍执事" in live_names_from_kernel(titled)
    assert "林暮" not in live_names_from_kernel(StoryKernel.model_validate(KERNEL))


def test_bible_lint_payoff_spacing_treats_whitespace_pressure_as_empty() -> None:
    from novel_agent.lint.bible import lint_bible

    beats = [
        _large_payoff("a", "   ", 1),
        _large_payoff("b", "\n\t", 2),
        _large_payoff("c", "", 3),
    ]
    report = lint_bible(payoff_beats=beats)
    assert not report.passed
    assert any(f.code == "payoff_spacing" for f in report.findings)

    ok = [
        _large_payoff("a", "被当众点名", 1),
        _large_payoff("b", "妹妹被扣", 2),
        _large_payoff("c", "卖身契压顶", 3),
    ]
    assert lint_bible(payoff_beats=ok).passed


def test_bible_lint_orphan_conflict_at_r5() -> None:
    from novel_agent.lint.bible import lint_bible

    missing = Conflict.model_validate(_conflict(payoff_chapter_key=""))
    outside = Conflict.model_validate(_conflict(conflict_id="cf_x", payoff_chapter_key="v1c099"))
    rolling = [f"v1c{i:03d}" for i in range(1, 6)]
    report = lint_bible(conflicts=[missing, outside], rolling_keys=rolling)
    assert not report.passed
    assert sum(1 for f in report.findings if f.code == "orphan_conflict") == 2

    ok = Conflict.model_validate(_conflict())
    assert lint_bible(conflicts=[ok], rolling_keys=rolling).passed


def test_bible_lint_relationship_without_evidence_fails() -> None:
    from novel_agent.domain.schemas import RelationshipProposal
    from novel_agent.lint.bible import lint_bible

    empty = RelationshipProposal(parties=["ch_su", "ch_shuju"], state="胁迫", evidence="  ")
    report = lint_bible(relationship_proposals=[empty])
    assert not report.passed
    assert any(f.code == "relationship_evidence" for f in report.findings)

    ok = RelationshipProposal(
        parties=["ch_su", "ch_shuju"],
        state="胁迫",
        evidence="书局执事以纵火案上门",
    )
    assert lint_bible(
        relationship_proposals=[ok]
    ).passed


def _bible_deps(session, mock=None):
    from novel_agent.config import Settings
    from novel_agent.gateway import MockProvider, ModelGateway
    from novel_agent.planning.mock_fixtures import register_planning_defaults
    from novel_agent.runtime.agents import AgentDeps

    mock = mock or MockProvider()
    register_planning_defaults(mock)
    return AgentDeps(
        gateway=ModelGateway(Settings(_env_file=None), session, {"mock": mock}),
        project_id=None,
    ), mock


def test_structure_conflict_payoff_prompts_have_frontmatter() -> None:
    from novel_agent.runtime.prompts import load_prompt

    structure = load_prompt("structure_planner")
    conflict = load_prompt("conflict_planner")
    payoff = load_prompt("payoff_planner")
    assert structure.output_schema == "StructureMap"
    assert conflict.output_schema == "ConflictList"
    assert payoff.output_schema == "PayoffBeatList"
    assert structure.slot == "creative"
    structure_body = structure.render(schema="{}", chapter_keys="v1c001,v1c002,v1c003")
    assert "v1c001,v1c002,v1c003" in structure_body
    assert "禁止发明" in structure_body or "窗口外" in structure_body


async def test_structure_conflict_payoff_planners_return_valid_schemas(engine) -> None:
    from sqlmodel import Session

    from novel_agent.config import Settings
    from novel_agent.domain.schemas import ConflictKind
    from novel_agent.gateway import MockProvider, ModelGateway
    from novel_agent.lint.bible import lint_bible
    from novel_agent.planning.mock_fixtures import (
        PLANNING_CONFLICTS,
        PLANNING_PAYOFFS,
        register_planning_defaults,
    )
    from novel_agent.runtime.agents import (
        AgentDeps,
        run_conflict_planner,
        run_payoff_planner,
        run_structure_planner,
    )

    mock = MockProvider()
    register_planning_defaults(mock)
    with Session(engine) as session:
        deps = AgentDeps(
            gateway=ModelGateway(Settings(_env_file=None), session, {"mock": mock}),
            project_id=1,
        )
        smap = await run_structure_planner(deps, "kernel", "brief")
        keys = [f"v1c{i:03d}" for i in range(1, 6)]
        conflicts = await run_conflict_planner(deps, "kernel", "chars", keys)
        beats = await run_payoff_planner(deps, "kernel", "conflicts", keys)

    assert len(smap.golden_three) == 3
    expected_ids = {item["conflict_id"] for item in PLANNING_CONFLICTS}
    assert {c.conflict_id for c in conflicts} == expected_ids
    assert all(c.kind in ConflictKind for c in conflicts)
    expected_beats = {item["beat_id"] for item in PLANNING_PAYOFFS}
    assert {b.beat_id for b in beats} == expected_beats
    report = lint_bible(
        structure=smap,
        conflicts=conflicts,
        payoff_beats=beats,
        rolling_keys=keys,
    )
    assert report.passed


async def test_bible_conversation_persists_full_r0_to_r5(engine) -> None:
    from sqlmodel import Session

    from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
    from novel_agent.planning.chain import PlanningGates
    from novel_agent.planning.conversation import run_bible_conversation

    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("说书人传奇", boundaries=["禁无代价全能"])
        session.commit()
        deps, _mock = _bible_deps(session)
        deps.project_id = project.id
        result = await run_bible_conversation(
            planning,
            BibleRepo(session),
            CanonRepo(session),
            deps,
            spark="说书人发现故事会成真",
            gates=PlanningGates.auto(),
        )
        session.commit()

        bible = BibleRepo(session)
        brief = bible.get_brief(project.id)
        assert brief is not None
        assert brief.genre == ""
        assert brief.audience == ""
        assert brief.do_not_write == ["禁无代价全能"]
        assert bible.get_structure_map(project.id) is not None
        assert bible.list_conflicts(project.id)
        assert bible.list_payoff_beats(project.id)
        assert result.chapter_keys == [f"v1c{i:03d}" for i in range(1, 6)]
        rel = CanonRepo(session).get_relationship(project.id, "ch_su", "ch_shuju")
        assert rel is not None
        assert rel.provisional is True
        assert rel.source_chapter == "planning"
        assert rel.evidence.strip()
        for key in result.chapter_keys:
            outline = planning.get_outline(project.id, key)
            assert outline.cited_conflict_ids or outline.cited_beat_ids
        assert bible.round_complete(project.id) == {"R0", "R1", "R2", "R3", "R4", "R5"}


async def test_bible_conversation_abort_r3_keeps_kernel(engine) -> None:
    from sqlmodel import Session

    from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
    from novel_agent.planning.chain import PlanningAborted, PlanningGates
    from novel_agent.planning.conversation import run_bible_conversation

    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("中止R3", boundaries=["禁无代价全能"])
        session.commit()
        deps, _mock = _bible_deps(session)
        deps.project_id = project.id

        def confirm(prompt: str) -> bool:
            return "角色" not in prompt

        with pytest.raises(PlanningAborted, match="R3"):
            await run_bible_conversation(
                planning,
                BibleRepo(session),
                CanonRepo(session),
                deps,
                spark="火花",
                gates=PlanningGates(select_kernel=lambda _c: 0, confirm=confirm),
            )
        session.commit()
        assert planning.get_approved_kernel(project.id) is not None
        assert BibleRepo(session).get_structure_map(project.id) is not None
        assert planning.list_characters(project.id) == []
        assert planning.list_chapters(project.id) == []


async def test_bible_conversation_resume_after_r3_skips_r0_to_r3(engine) -> None:
    from sqlmodel import Session

    from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
    from novel_agent.gateway import MockProvider
    from novel_agent.planning.chain import PlanningAborted, PlanningGates
    from novel_agent.planning.conversation import run_bible_conversation
    from novel_agent.planning.mock_fixtures import register_planning_defaults

    with Session(engine) as session:
        planning = PlanningRepo(session)
        bible = BibleRepo(session)
        canon = CanonRepo(session)
        project = planning.create_project("续跑", boundaries=["禁无代价全能"])
        session.commit()
        deps, _mock = _bible_deps(session)
        deps.project_id = project.id

        def confirm(prompt: str) -> bool:
            return "冲突" not in prompt

        with pytest.raises(PlanningAborted, match="R4"):
            await run_bible_conversation(
                planning,
                bible,
                canon,
                deps,
                spark="火花",
                gates=PlanningGates(select_kernel=lambda _c: 0, confirm=confirm),
            )
        session.commit()
        assert "R3" in bible.round_complete(project.id)
        assert "R4" not in bible.round_complete(project.id)

        mock = MockProvider()
        register_planning_defaults(mock)
        deps, _ = _bible_deps(session, mock)
        deps.project_id = project.id
        result = await run_bible_conversation(
            planning,
            bible,
            canon,
            deps,
            spark="火花",
            gates=PlanningGates.auto(),
        )
        assert set(result.skipped) >= {"R0", "R1", "R2", "R3"}
        assert "R4" not in result.skipped
        assert len(planning.list_chapters(project.id)) == 5


async def test_ensure_r2_accepts_named_protagonist_from_kernel(engine) -> None:
    """R2 必须把内核里抽出的姓名交给黄金三章 lint,否则余烬回声这类结构会被丢弃。"""
    import json
    from copy import deepcopy

    from sqlmodel import Session

    from novel_agent.domain.repos import BibleRepo, PlanningRepo
    from novel_agent.domain.schemas import StoryBrief
    from novel_agent.planning.chain import PlanningGates
    from novel_agent.planning.conversation import _ensure_r2
    from novel_agent.planning.mock_fixtures import PLANNING_STRUCTURE

    kernel = StoryKernel.model_validate(
        {
            **KERNEL,
            "logline": "化妆师林暮在停电夜必须完成封口,否则失声潮吞没全城",
            "premise": "如果末世封口失败会让死者重新开口",
        }
    )
    structure = deepcopy(PLANNING_STRUCTURE)
    structure["golden_three"][0] = {
        "promise": "林暮封口失败、全城停电",
        "escalation": "失声潮吞没街区",
        "payoff_or_hook": "天亮前必须找出改脸的人",
    }

    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("余烬回声")
        session.commit()
        deps, mock = _bible_deps(session)
        deps.project_id = project.id
        mock.register(
            "structure_planner",
            lambda _req: json.dumps(structure, ensure_ascii=False),
        )
        await _ensure_r2(
            BibleRepo(session),
            deps,
            project.id,
            kernel,
            StoryBrief(spark="末世余烬回声"),
            PlanningGates.auto(),
            [],
        )
        session.commit()
        saved = BibleRepo(session).get_structure_map(project.id)
        assert saved is not None
        assert saved.golden_three[0].promise == "林暮封口失败、全城停电"


async def test_bible_conversation_r5_lint_failure_does_not_persist_outlines(engine) -> None:
    import json

    from sqlmodel import Session

    from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
    from novel_agent.gateway import MockProvider
    from novel_agent.planning.chain import PlanningError, PlanningGates
    from novel_agent.planning.conversation import run_bible_conversation
    from novel_agent.planning.mock_fixtures import planning_outline_payload

    mock = MockProvider()
    with Session(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("lint失败", boundaries=["禁无代价全能"])
        session.commit()
        deps, mock = _bible_deps(session, mock)
        deps.project_id = project.id

        def bad_outline(_req):
            payload = planning_outline_payload()
            for outline in payload["outlines"]:
                outline["cited_conflict_ids"] = []
                outline["cited_beat_ids"] = []
            return json.dumps(payload, ensure_ascii=False)

        mock.register("outline_planner", bad_outline)
        with pytest.raises(PlanningError, match="lint"):
            await run_bible_conversation(
                planning,
                BibleRepo(session),
                CanonRepo(session),
                deps,
                spark="火花",
                gates=PlanningGates.auto(),
            )
        session.commit()
        assert planning.list_chapters(project.id) == []
        assert BibleRepo(session).list_conflicts(project.id)


def test_cli_init_yes_persists_story_bible(cli_db) -> None:
    from typer.testing import CliRunner

    from novel_agent.cli.main import app
    from novel_agent.domain.db import build_engine, session_scope
    from novel_agent.domain.repos import BibleRepo, PlanningRepo

    result = CliRunner().invoke(
        app,
        ["init", "说书人传奇", "--brief", "说书人发现自己讲的故事会成真", "--yes"],
    )
    assert result.exit_code == 0, result.output
    engine = build_engine(cli_db)
    with session_scope(engine) as session:
        bible = BibleRepo(session)
        assert bible.get_brief(1) is not None
        assert bible.get_structure_map(1) is not None
        assert bible.list_conflicts(1)
        assert bible.list_payoff_beats(1)
        assert len(PlanningRepo(session).list_chapters(1)) == 5


def test_cli_bible_yes_resumes_existing_project(cli_db) -> None:
    from typer.testing import CliRunner

    from novel_agent.cli.main import app
    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.repos import BibleRepo, PlanningRepo

    engine = build_engine(cli_db)
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("已有项目").id

    result = CliRunner().invoke(
        app,
        ["bible", "--project-id", str(pid), "--brief", "说书人题材", "--yes"],
    )
    assert result.exit_code == 0, result.output
    with session_scope(engine) as session:
        bible = BibleRepo(session)
        assert bible.get_structure_map(pid) is not None
        assert len(PlanningRepo(session).list_chapters(pid)) == 5


def test_cli_bible_without_yes_exits_in_non_interactive_env(cli_db) -> None:
    from typer.testing import CliRunner

    from novel_agent.cli.main import app
    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.repos import PlanningRepo

    engine = build_engine(cli_db)
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("会挂起吗").id

    result = CliRunner().invoke(app, ["bible", "--project-id", str(pid), "--brief", "简报"])
    assert result.exit_code == 2, result.output
    assert "--yes" in result.output
