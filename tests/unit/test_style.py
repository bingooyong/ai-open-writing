"""项目级风格包:校验、编译、内置 fixture、仓储合并。"""

from __future__ import annotations

from pydantic import ValidationError

from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import PlanningRepo
from novel_agent.style import (
    StylePack,
    compile_style_rules,
    load_builtin_pack,
    style_rules_from_settings,
)

BANNED_THIRD_PARTY = ("叶默", "刘亦非", "封于修")


def test_builtin_oral_short_beat_pack_validates_and_compiles() -> None:
    pack = load_builtin_pack("oral_short_beat")
    assert pack.id == "oral_short_beat"
    compiled = compile_style_rules(pack)
    assert "默认一句一段" in compiled
    assert "节奏样例（只学句长、空行、叙述距离，不学情节）" in compiled
    assert "林朔" in compiled
    assert "老郑" in compiled
    for banned in BANNED_THIRD_PARTY:
        assert banned not in compiled
        assert banned not in pack.rules
        assert all(banned not in sample for sample in pack.samples)


def test_unknown_or_invalid_style_settings_yield_empty_rules() -> None:
    assert style_rules_from_settings({}) == ""
    assert style_rules_from_settings({"style": None}) == ""
    assert style_rules_from_settings({"style": "not-a-pack"}) == ""
    assert style_rules_from_settings({"style": {"id": "broken"}}) == ""


def test_style_pack_rejects_empty_id() -> None:
    pack = load_builtin_pack("oral_short_beat").model_dump()
    pack["id"] = ""
    try:
        StylePack.model_validate(pack)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_update_project_preserves_style_when_patching_writer_b(tmp_path) -> None:
    engine = build_engine(tmp_path / "style.db")
    create_all(engine)
    pack = load_builtin_pack("oral_short_beat").model_dump()
    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("风格项目")
        repo.update_project_style(project.id, pack)
        repo.update_project(project.id, enable_writer_b=False)
        stored = repo.get_project(project.id)
        assert stored.settings["style"]["id"] == "oral_short_beat"
        assert stored.settings["style"]["rules"]
        assert stored.settings["enable_writer_b"] is False
        assert stored.settings.get("enable_reader_advocate", True) is True
