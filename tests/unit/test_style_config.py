"""Project-level writing style configuration."""

from __future__ import annotations

import json

from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT
from typer.testing import CliRunner

from novel_agent.cli.main import app as cli_app
from novel_agent.config import reset_settings_cache
from novel_agent.context import ContextBuilder
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import CanonRepo, PlanningRepo
from novel_agent.domain.schemas import (
    ChapterOutline,
    CharacterCard,
    PlotUnitCard,
    SceneCard,
    StoryKernel,
)
from novel_agent.runtime.agents import _ctx_text
from novel_agent.style import (
    ALIASES,
    PACKS_DIR,
    compile_style_rules,
    list_frozen_pack_ids,
    load_frozen_pack,
    parse_style_pack,
)


def _prepared(tmp_path):
    engine = build_engine(tmp_path / "style.db")
    create_all(engine)
    session = session_scope(engine)
    s = session.__enter__()
    planning = PlanningRepo(s)
    project = planning.create_project("风格测试", boundaries=["项目边界"])
    planning.save_kernel(project.id, StoryKernel.model_validate(KERNEL))
    planning.approve_kernel(project.id, 1)
    planning.upsert_character(project.id, CharacterCard.model_validate(CHARACTER))
    planning.save_volume(project.id, "v1", {"summary": "第一卷摘要"})
    planning.save_unit(project.id, "v1", PlotUnitCard.model_validate(UNIT))
    planning.create_chapter(project.id, ChapterOutline.model_validate(OUTLINE), order_index=1)
    planning.save_scene_cards(project.id, "v1c001", [SceneCard.model_validate(SCENE)])
    return session, planning, CanonRepo(s), project.id


def test_frozen_pack_is_original_and_compiles() -> None:
    pack = load_frozen_pack("oral_short_beat")
    assert pack is not None
    assert pack.id == "oral_short_beat"
    assert pack.mid_style == "镜头短句"
    text = (PACKS_DIR / "oral_short_beat.json").read_text(encoding="utf-8")
    assert "叶默" not in text
    assert "刘亦非" not in text
    compiled = compile_style_rules(pack)
    assert "叙述服从本规则" in compiled
    assert "节奏样例（只学句长、空行、叙述距离，不学情节）：" in compiled
    assert "棚门没关严。" in compiled
    assert "她把磁带放下。" in compiled




CATALOG = {
    "oral_short_beat": "镜头短句",
    "craft_baimiao": "职业白描",
    "dialogue_scene": "对话场",
    "dual_cut": "双线切开",
    "close_interior": "心理密距",
}
BANNED_PACK_NAMES = ("叶默", "刘亦非", "封于修")
SAMPLE_SNIPPETS = {
    "oral_short_beat": "棚门没关严。",
    "craft_baimiao": "红塔山烧到一半。",
    "dialogue_scene": "第二句尾音不能压在推拉里。",
    "dual_cut": "与此同时。棚外。",
    "close_interior": "这场会废。",
}


def test_frozen_catalog_loads_compiles_and_aliases() -> None:
    assert set(list_frozen_pack_ids()) == set(CATALOG)
    assert {alias: pack_id for pack_id, alias in CATALOG.items()} == ALIASES
    for pack_id, alias in CATALOG.items():
        pack = load_frozen_pack(pack_id)
        assert pack is not None
        assert pack.id == pack_id
        assert pack.mid_style == alias
        assert pack.label
        aliased = load_frozen_pack(alias)
        assert aliased is not None
        assert aliased.id == pack_id
        compiled = compile_style_rules(pack)
        assert "叙述服从本规则" in compiled
        assert "节奏样例（只学句长、空行、叙述距离，不学情节）：" in compiled
        assert SAMPLE_SNIPPETS[pack_id] in compiled
        raw = (PACKS_DIR / f"{pack_id}.json").read_text(encoding="utf-8")
        for name in BANNED_PACK_NAMES:
            assert name not in raw
            assert name not in compiled
            assert name not in pack.rules
            for sample in pack.samples:
                assert name not in sample


def test_cli_style_list() -> None:
    runner = CliRunner()
    listed = runner.invoke(cli_app, ["style", "list"])
    assert listed.exit_code == 0, listed.output
    for pack_id, alias in CATALOG.items():
        assert pack_id in listed.output
        assert alias in listed.output


def test_cli_style_set_accepts_chinese_alias(tmp_path, monkeypatch) -> None:
    db = tmp_path / "cli-style-alias.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    engine = build_engine(db)
    create_all(engine)
    with session_scope(engine) as session:
        project = PlanningRepo(session).create_project("别名风格")
        pid = project.id
    runner = CliRunner()
    setted = runner.invoke(cli_app, ["style", "set", "--project", str(pid), "--pack", "职业白描"])
    assert setted.exit_code == 0, setted.output
    assert "craft_baimiao" in setted.output
    shown = runner.invoke(cli_app, ["style", "show", "--project", str(pid)])
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output.split("\n\n", 1)[0])
    assert payload["id"] == "craft_baimiao"
    assert payload["mid_style"] == "职业白描"
    reset_settings_cache()


def test_invalid_or_missing_pack_is_empty() -> None:
    assert parse_style_pack(None) is None
    assert parse_style_pack("oral_short_beat") is None
    assert parse_style_pack({}) is None
    assert parse_style_pack({"id": "x"}) is None
    assert compile_style_rules(None) == ""
    assert compile_style_rules({"id": "bad"}) == ""
    assert load_frozen_pack("does_not_exist") is None
    assert load_frozen_pack("../oral_short_beat") is None


def test_builder_loads_style_from_settings_and_explicit_wins(tmp_path) -> None:
    session, planning, canon, project_id = _prepared(tmp_path)
    try:
        pack = load_frozen_pack("oral_short_beat")
        assert pack is not None
        planning.set_project_style(project_id, pack)

        defaulted = ContextBuilder(planning, canon).build(
            project_id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要"
        )
        compiled = compile_style_rules(pack)
        assert defaulted.style_rules == compiled
        assert defaulted.style_rules

        overridden = ContextBuilder(planning, canon).build(
            project_id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            style_rules="克制叙述",
        )
        assert overridden.style_rules == "克制叙述"

        rec = planning.get_project(project_id)
        rec.settings = {"style": {"id": "broken"}, "enable_writer_b": True}
        planning.s.add(rec)
        broken = ContextBuilder(planning, canon).build(
            project_id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要"
        )
        assert broken.style_rules == ""
    finally:
        session.__exit__(None, None, None)


def test_update_project_preserves_style(tmp_path) -> None:
    engine = build_engine(tmp_path / "flags.db")
    create_all(engine)
    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("开关")
        pack = load_frozen_pack("oral_short_beat")
        assert pack is not None
        repo.set_project_style(project.id, pack)
        repo.update_project(project.id, enable_writer_b=False, enable_reader_advocate=True)
        stored = repo.get_project(project.id).settings
        assert stored["enable_writer_b"] is False
        assert stored["enable_reader_advocate"] is True
        assert stored["style"]["id"] == "oral_short_beat"
        assert repo.get_project_style(project.id)["id"] == "oral_short_beat"


def test_writer_context_includes_style_heading_when_pack_present(tmp_path) -> None:
    session, planning, canon, project_id = _prepared(tmp_path)
    try:
        pack = load_frozen_pack("oral_short_beat")
        assert pack is not None
        planning.set_project_style(project_id, pack)
        package = ContextBuilder(planning, canon).build(
            project_id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要"
        )
        text = _ctx_text(package)
        assert "# 风格规则" in text
        assert "叙述服从本规则" in text
        assert "节奏样例" in text
    finally:
        session.__exit__(None, None, None)


def test_cli_style_set_and_show(tmp_path, monkeypatch) -> None:
    db = tmp_path / "cli-style.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    engine = build_engine(db)
    create_all(engine)
    with session_scope(engine) as session:
        project = PlanningRepo(session).create_project("CLI风格")
        pid = project.id
    runner = CliRunner()
    shown = runner.invoke(cli_app, ["style", "show", "--project", str(pid)])
    assert shown.exit_code == 0, shown.output
    assert "未配置风格" in shown.output

    setted = runner.invoke(
        cli_app, ["style", "set", "--project", str(pid), "--pack", "oral_short_beat"]
    )
    assert setted.exit_code == 0, setted.output
    assert "oral_short_beat" in setted.output

    shown2 = runner.invoke(cli_app, ["style", "show", "--project", str(pid)])
    assert shown2.exit_code == 0, shown2.output
    payload = json.loads(shown2.output.split("\n\n", 1)[0])
    assert payload["id"] == "oral_short_beat"
    assert "叙述服从本规则" in shown2.output
    reset_settings_cache()


def test_writer_and_prose_prompts_carry_style_discipline() -> None:
    from novel_agent.runtime.prompts import DEFAULT_PROMPTS_DIR

    writer = (DEFAULT_PROMPTS_DIR / "writer.md").read_text(encoding="utf-8")
    prose = (DEFAULT_PROMPTS_DIR / "prose.md").read_text(encoding="utf-8")
    assert "若上下文含风格规则，叙述口吻必须服从；场景卡只决定情节。" in writer
    assert "若风格规则非空，违反即为 P1" in prose
    assert "风格规则为空时才不做风格洁癖" in prose
