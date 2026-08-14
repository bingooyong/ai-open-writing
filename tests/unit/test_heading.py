from novel_agent.production.heading import chapter_heading
from novel_agent.runtime.prompts import DEFAULT_PROMPTS_DIR


def test_chapter_heading_uses_arabic_number() -> None:
    assert chapter_heading(1, "醒木") == "第1章 醒木"
    assert chapter_heading(12, " 后巷 ") == "第12章 后巷"
    assert chapter_heading(1, "") == "第1章"
    assert chapter_heading(0, "醒木") == "醒木"


def test_writer_and_reviser_forbid_heading_in_body() -> None:
    writer = (DEFAULT_PROMPTS_DIR / "writer.md").read_text(encoding="utf-8")
    reviser = (DEFAULT_PROMPTS_DIR / "reviser.md").read_text(encoding="utf-8")
    for body in (writer, reviser):
        assert "不要在正文开头写「第N章 标题」或「第一章 xxx」" in body
        assert "章名由系统加" in body


def test_writer_and_reviser_forbid_placeholder_scene_tag() -> None:
    writer = (DEFAULT_PROMPTS_DIR / "writer.md").read_text(encoding="utf-8")
    reviser = (DEFAULT_PROMPTS_DIR / "reviser.md").read_text(encoding="utf-8")
    for body in (writer, reviser):
        assert "SCENE 标记必须用场景卡上的 id（如 v1c001_s1），禁止写「场景id」二字。" in body
