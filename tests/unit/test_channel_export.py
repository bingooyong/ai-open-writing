"""渠道导出模板:起点 / 番茄 / generic / EPUB;默认只出 CANON_LOCKED。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from sqlmodel import Session
from test_schemas import OUTLINE
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import reset_settings_cache
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.repos import PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterOutline, ChapterStatus
from novel_agent.production.export import export_project, render_export

LOCKED_1 = "茶楼里灯火通明，苏晚生一拍醒木，满堂皆静。"
LOCKED_2 = "霍执事在后巷等他，只问下一句还讲不讲。"
DRAFT_BODY = "这是尚未锁定的草稿正文，不该出现在默认导出里。"
LEAK_LINE = "你是一名作家，请按输出 Schema 继续写。"


def _outline(chapter_key: str, title: str, volume_id: str = "v1") -> ChapterOutline:
    return ChapterOutline.model_validate(
        {
            **OUTLINE,
            "chapter_key": chapter_key,
            "title": title,
            "volume_id": volume_id,
            "core_event": f"{title}的核心事件",
        }
    )


def _add_chapter(
    planning: PlanningRepo,
    production: ProductionRepo,
    project_id: int,
    *,
    chapter_key: str,
    title: str,
    body: str,
    status: ChapterStatus,
    order_index: int,
    volume_id: str = "v1",
    extra: str = "",
) -> None:
    planning.create_chapter(project_id, _outline(chapter_key, title, volume_id), order_index)
    planning.set_status(project_id, chapter_key, status)
    production.create_draft(
        project_id,
        chapter_key,
        "candidate_1",
        f"lin-{chapter_key}",
        body,
        {
            "scenes": [
                {
                    "schema_version": "1.0",
                    "scene_id": f"{chapter_key}_s1",
                    "content": f"{body}\n{extra}".rstrip(),
                }
            ],
            "chapter_summary": "摘要不得泄漏",
            "deviation_notes": "偏离说明不得泄漏",
        },
        "w1",
        1,
    )


def _fixture_project(tmp_path: Path) -> tuple[Session, int]:
    engine = build_engine(tmp_path / "export.db")
    create_all(engine)
    session = Session(engine)
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    project = planning.create_project("说书人传奇", genre="奇幻")
    assert project.id is not None
    project.spark = "说书人发现故事会成真"
    session.add(project)
    planning.save_volume(project.id, "v1", {"goal": "入局"}, title="入局")
    _add_chapter(
        planning,
        production,
        project.id,
        chapter_key="v1c001",
        title="醒木",
        body=LOCKED_1,
        status=ChapterStatus.CANON_LOCKED,
        order_index=1,
        extra=LEAK_LINE,
    )
    _add_chapter(
        planning,
        production,
        project.id,
        chapter_key="v1c002",
        title="后巷",
        body=LOCKED_2,
        status=ChapterStatus.CANON_LOCKED,
        order_index=2,
    )
    _add_chapter(
        planning,
        production,
        project.id,
        chapter_key="v1c003",
        title="未锁定",
        body=DRAFT_BODY,
        status=ChapterStatus.HUMAN_REVIEW,
        order_index=3,
    )
    session.commit()
    return session, project.id


def test_qidian_txt_headers_body_and_no_leak(tmp_path: Path) -> None:
    session, project_id = _fixture_project(tmp_path)
    try:
        text = render_export(session, project_id, "txt", channel="qidian")
        assert "第1章 醒木" in text
        assert "第2章 后巷" in text
        assert LOCKED_1 in text
        assert LOCKED_2 in text
        assert "第1卷 入局" in text
        assert DRAFT_BODY not in text
        assert "第3章" not in text
        assert LEAK_LINE not in text
        assert "你是一名" not in text
        assert "输出 Schema" not in text
        assert "摘要不得泄漏" not in text
        assert "<<<SCENE" not in text
        assert "v1c001" not in text
        header_at = text.index("第1章 醒木")
        body_at = text.index(LOCKED_1)
        between = text[header_at + len("第1章 醒木") : body_at]
        assert between.startswith("\n\n")
    finally:
        session.close()


def test_fanqie_headers_differ_from_qidian(tmp_path: Path) -> None:
    session, project_id = _fixture_project(tmp_path)
    try:
        qidian = render_export(session, project_id, "txt", channel="qidian")
        fanqie = render_export(session, project_id, "txt", channel="fanqie")
        assert "第1章 醒木" in fanqie
        assert "第2章 后巷" in fanqie
        assert LOCKED_1 in fanqie
        assert "第1卷" not in fanqie
        assert "说书人传奇" not in fanqie.split("第1章", 1)[0]
        q_gap = qidian[qidian.index("第1章 醒木") + len("第1章 醒木") : qidian.index(LOCKED_1)]
        f_gap = fanqie[fanqie.index("第1章 醒木") + len("第1章 醒木") : fanqie.index(LOCKED_1)]
        assert q_gap.startswith("\n\n")
        assert f_gap == "\n"
        assert fanqie != qidian
    finally:
        session.close()


def test_generic_txt_md_stay_cleaned(tmp_path: Path) -> None:
    session, project_id = _fixture_project(tmp_path)
    try:
        txt = render_export(session, project_id, "txt")
        md = render_export(session, project_id, "md")
        assert txt.startswith("说书人传奇\n")
        assert "v1c001 醒木" in txt
        assert md.startswith("# 说书人传奇\n")
        assert "## v1c001 醒木" in md
        assert LOCKED_1 in txt and LOCKED_1 in md
        assert LEAK_LINE not in txt and LEAK_LINE not in md
        assert DRAFT_BODY not in txt
    finally:
        session.close()


def test_include_drafts_vs_default(tmp_path: Path) -> None:
    session, project_id = _fixture_project(tmp_path)
    try:
        default = render_export(session, project_id, "txt", channel="qidian")
        preview = render_export(
            session, project_id, "txt", channel="qidian", include_drafts=True
        )
        assert DRAFT_BODY not in default
        assert "第3章 未锁定" not in default
        assert DRAFT_BODY in preview
        assert "第3章 未锁定" in preview
    finally:
        session.close()


def test_epub_is_zip_with_mimetype_and_chapter_xhtml(tmp_path: Path) -> None:
    session, project_id = _fixture_project(tmp_path)
    try:
        out = tmp_path / "book.epub"
        result = export_project(session, project_id, "epub", out, channel="epub")
        assert result == out
        assert out.is_file()
        with zipfile.ZipFile(out) as zf:
            assert zf.namelist()[0] == "mimetype"
            info = zf.getinfo("mimetype")
            assert info.compress_type == zipfile.ZIP_STORED
            assert zf.read("mimetype") == b"application/epub+zip"
            names = zf.namelist()
            assert "META-INF/container.xml" in names
            xhtml = [name for name in names if name.endswith(".xhtml")]
            assert any("chapter" in name for name in xhtml)
            joined = b"".join(zf.read(name) for name in xhtml)
            assert "第1章".encode() in joined or LOCKED_1.encode("utf-8") in joined
            assert DRAFT_BODY.encode("utf-8") not in joined
            opf = next(name for name in names if name.endswith(".opf"))
            meta = zf.read(opf).decode("utf-8")
            assert "说书人传奇" in meta
            assert "说书人发现故事会成真" in meta
    finally:
        session.close()


@pytest.fixture()
def cli_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    engine = build_engine(db_path)
    create_all(engine)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        production = ProductionRepo(session)
        project = planning.create_project("说书人传奇")
        assert project.id == 1
        project.spark = "说书人发现故事会成真"
        session.add(project)
        planning.save_volume(1, "v1", {}, title="入局")
        _add_chapter(
            planning,
            production,
            1,
            chapter_key="v1c001",
            title="醒木",
            body=LOCKED_1,
            status=ChapterStatus.CANON_LOCKED,
            order_index=1,
        )
        session.commit()
    yield db_path
    reset_settings_cache()


def test_cli_channel_and_format_epub_implies_channel(cli_db: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_txt = tmp_path / "qidian.txt"
    qidian = runner.invoke(
        app,
        [
            "export",
            "--project-id",
            "1",
            "--channel",
            "qidian",
            "--format",
            "txt",
            "--out",
            str(out_txt),
        ],
    )
    assert qidian.exit_code == 0, qidian.output
    assert "第1章 醒木" in out_txt.read_text(encoding="utf-8")

    out_epub = tmp_path / "book.epub"
    epub = runner.invoke(
        app,
        ["export", "--project-id", "1", "--format", "epub", "--out", str(out_epub)],
    )
    assert epub.exit_code == 0, epub.output
    with zipfile.ZipFile(out_epub) as zf:
        assert zf.read("mimetype") == b"application/epub+zip"

    bad = runner.invoke(app, ["export", "--project-id", "1", "--channel", "wechat"])
    assert bad.exit_code == 2
