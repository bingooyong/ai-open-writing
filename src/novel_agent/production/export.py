"""渠道导出模板(起点 / 番茄 / generic / EPUB3)。

默认只导出 CANON_LOCKED(及已 EXPORTED)章;--include-drafts 含未锁定稿。
模板不是官方投稿 API,也不登录或抓取平台。

渠道差异(番茄相对起点):
- 起点: `第N章 标题` 后空一行再接正文;有卷名或多卷时输出 `第X卷 卷名`。
- 番茄: 同形章标题,标题后直接接正文(无空行);不输出书名页或卷名页。
- generic: 书名 + `第N章 标题`(与起点/番茄同一 `chapter_heading`),并清洗工程污染。
- epub: 简易 EPUB3,一章一个 xhtml,nav + 书名/火花元数据。
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Literal, assert_never
from xml.sax.saxutils import escape as xml_escape

from sqlmodel import Session

from novel_agent.domain.models import ProjectRecord
from novel_agent.domain.repos import PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus
from novel_agent.production.heading import chapter_heading
from novel_agent.production.loop import draft_from_record

ExportFormat = Literal["txt", "md", "epub"]
ExportChannel = Literal["generic", "qidian", "fanqie", "epub"]

CHANNELS: frozenset[str] = frozenset({"generic", "qidian", "fanqie", "epub"})
FORMATS: frozenset[str] = frozenset({"txt", "md", "epub"})

_LOCKED = frozenset({ChapterStatus.CANON_LOCKED, ChapterStatus.EXPORTED})
_EXPORTABLE = frozenset(
    {
        ChapterStatus.HUMAN_REVIEW,
        ChapterStatus.APPROVED,
        ChapterStatus.CANON_LOCKED,
        ChapterStatus.EXPORTED,
        ChapterStatus.NEEDS_REVISION,
        ChapterStatus.ADVERSARIAL_REVIEW,
        ChapterStatus.JUDGING,
        ChapterStatus.DRAFTING,
    }
)

_LEAK_LINE = re.compile(
    r"```json|<<<(?:SCENE|END|META)|系统提示词|输出\s*Schema|schema_version|"
    r"你是一名|作为(?:一个)?AI|作为语言模型|我无法|抱歉[,,]我不能|"
    r"issue_id|reviewer_role|violated_rule|revision_scope"
)
_VOLUME_NUM = re.compile(r"v(\d+)", re.IGNORECASE)


class ExportSpecError(ValueError):
    """channel / format 组合不合法。"""


@dataclass(frozen=True)
class ExportArtifact:
    filename: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class _ChapterOut:
    number: int
    title: str
    body: str
    chapter_key: str
    volume_id: str
    volume_title: str
    volume_number: int


def resolve_channel_format(channel: str, fmt: str) -> tuple[ExportChannel, ExportFormat]:
    if fmt not in FORMATS:
        raise ExportSpecError("format 必须是 txt、md 或 epub")
    if channel not in CHANNELS:
        raise ExportSpecError("channel 必须是 generic、qidian、fanqie 或 epub")
    if fmt == "epub" or channel == "epub":
        return "epub", "epub"
    return channel, fmt  # type: ignore[return-value]


def clean_export_body(text: str) -> str:
    kept = [line for line in text.splitlines() if not _LEAK_LINE.search(line)]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    return cleaned.strip()


def _media_type(fmt: ExportFormat) -> str:
    if fmt == "md":
        return "text/markdown; charset=utf-8"
    if fmt == "txt":
        return "text/plain; charset=utf-8"
    if fmt == "epub":
        return "application/epub+zip"
    assert_never(fmt)


def _volume_number(volume_id: str) -> int:
    match = _VOLUME_NUM.search(volume_id)
    return int(match.group(1)) if match else 1


def _chapter_heading(chapter: _ChapterOut) -> str:
    return chapter_heading(chapter.number, chapter.title)


def _collect_chapters(
    session: Session, project_id: int, include_drafts: bool
) -> tuple[ProjectRecord, list[_ChapterOut]]:
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    project = planning.get_project(project_id)
    volumes = {row.volume_id: row for row in planning.list_volumes(project_id)}
    allowed = _EXPORTABLE if include_drafts else _LOCKED
    collected: list[_ChapterOut] = []
    for chapter in planning.list_chapters(project_id):
        if chapter.status not in allowed:
            continue
        draft = production.latest_chapter_draft(project_id, chapter.chapter_key)
        if draft is None:
            continue
        body = clean_export_body(draft_from_record(draft).full_text())
        if not body:
            continue
        volume = volumes.get(chapter.volume_id)
        collected.append(
            _ChapterOut(
                number=chapter.order_index if chapter.order_index >= 1 else len(collected) + 1,
                title=chapter.title,
                body=body,
                chapter_key=chapter.chapter_key,
                volume_id=chapter.volume_id,
                volume_title=(volume.title if volume is not None else "").strip(),
                volume_number=_volume_number(chapter.volume_id),
            )
        )
    return project, collected


def _generic_block(fmt: Literal["txt", "md"], chapter: _ChapterOut) -> str:
    heading = _chapter_heading(chapter)
    if fmt == "md":
        return f"## {heading}\n\n{chapter.body}\n"
    if fmt == "txt":
        return f"{heading}\n{chapter.body}\n"
    assert_never(fmt)


def _render_generic(title: str, chapters: list[_ChapterOut], fmt: Literal["txt", "md"]) -> str:
    chunks: list[str] = []
    if fmt == "md":
        chunks.append(f"# {title}\n")
    elif fmt == "txt":
        chunks.append(f"{title}\n")
    else:
        assert_never(fmt)
    for chapter in chapters:
        chunks.append(_generic_block(fmt, chapter))
    return "\n".join(chunks).rstrip() + "\n"


def _render_qidian(chapters: list[_ChapterOut]) -> str:
    volume_ids = {chapter.volume_id for chapter in chapters}
    wrap_volumes = len(volume_ids) > 1 or any(chapter.volume_title for chapter in chapters)
    chunks: list[str] = []
    last_volume = ""
    for chapter in chapters:
        if wrap_volumes and chapter.volume_id != last_volume:
            label = chapter.volume_title or chapter.volume_id
            chunks.append(f"第{chapter.volume_number}卷 {label}")
            last_volume = chapter.volume_id
        chunks.append(f"{_chapter_heading(chapter)}\n\n{chapter.body}")
    return "\n\n".join(chunks).rstrip() + "\n"


def _render_fanqie(chapters: list[_ChapterOut]) -> str:
    parts = [f"{_chapter_heading(chapter)}\n{chapter.body}" for chapter in chapters]
    return "\n\n\n".join(parts).rstrip() + "\n"


def _xhtml_paragraphs(body: str) -> str:
    blocks = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    if not blocks:
        return "<p></p>"
    return "\n".join(f"<p>{escape(block).replace(chr(10), '<br />')}</p>" for block in blocks)


def _chapter_xhtml(chapter: _ChapterOut) -> str:
    heading = _chapter_heading(chapter)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">\n'
        f"<head><title>{escape(heading)}</title></head>\n"
        "<body>\n"
        f"<h1>{escape(heading)}</h1>\n"
        f"{_xhtml_paragraphs(chapter.body)}\n"
        "</body>\n"
        "</html>\n"
    )


def _nav_xhtml(title: str, chapters: list[_ChapterOut]) -> str:
    items = []
    for index, chapter in enumerate(chapters, start=1):
        href = f"chapter-{index:03d}.xhtml"
        items.append(f'<li><a href="{href}">{escape(_chapter_heading(chapter))}</a></li>')
    listing = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        'xml:lang="zh-CN" lang="zh-CN">\n'
        f"<head><title>{escape(title)}</title></head>\n"
        "<body>\n"
        f'<nav epub:type="toc"><h1>{escape(title)}</h1>\n'
        f"<ol>\n{listing}\n</ol>\n"
        "</nav>\n"
        "</body>\n"
        "</html>\n"
    )


def _content_opf(title: str, spark: str, book_id: str, chapters: list[_ChapterOut]) -> str:
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    ]
    spine = []
    for index, _chapter in enumerate(chapters, start=1):
        item_id = f"chap{index:03d}"
        href = f"chapter-{index:03d}.xhtml"
        manifest.append(
            f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{item_id}"/>')
    description = f"<dc:description>{xml_escape(spark)}</dc:description>\n    " if spark else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" '
        'version="3.0" xml:lang="zh-CN">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">{xml_escape(book_id)}</dc:identifier>\n'
        f"    <dc:title>{xml_escape(title)}</dc:title>\n"
        "    <dc:language>zh-CN</dc:language>\n"
        f"    {description}"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        "</metadata>\n"
        "<manifest>\n    "
        + "\n    ".join(manifest)
        + "\n</manifest>\n"
        "<spine>\n    "
        + "\n    ".join(spine)
        + "\n</spine>\n"
        "</package>\n"
    )


def _container_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )


def _render_epub(title: str, spark: str, project_id: int, chapters: list[_ChapterOut]) -> bytes:
    book_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"novel-agent:{project_id}:{title}"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _container_xml())
        archive.writestr("OEBPS/content.opf", _content_opf(title, spark, book_id, chapters))
        archive.writestr("OEBPS/nav.xhtml", _nav_xhtml(title, chapters))
        for index, chapter in enumerate(chapters, start=1):
            archive.writestr(f"OEBPS/chapter-{index:03d}.xhtml", _chapter_xhtml(chapter))
    return buf.getvalue()


def _filename(project_id: int, channel: ExportChannel, fmt: ExportFormat) -> str:
    return f"project-{project_id}-{channel}.{fmt}"


def build_export(
    session: Session,
    project_id: int,
    fmt: str,
    *,
    channel: str = "generic",
    include_drafts: bool = False,
) -> ExportArtifact:
    resolved_channel, resolved_fmt = resolve_channel_format(channel, fmt)
    project, chapters = _collect_chapters(session, project_id, include_drafts)
    if resolved_channel == "epub":
        data = _render_epub(project.title, (project.spark or "").strip(), project_id, chapters)
        return ExportArtifact(_filename(project_id, "epub", "epub"), _media_type("epub"), data)
    if resolved_channel == "generic":
        if resolved_fmt not in {"txt", "md"}:
            raise ExportSpecError("generic 渠道只支持 txt 或 md")
        text = _render_generic(project.title, chapters, resolved_fmt)
    elif resolved_channel == "qidian":
        text = _render_qidian(chapters)
    elif resolved_channel == "fanqie":
        text = _render_fanqie(chapters)
    else:
        assert_never(resolved_channel)
    return ExportArtifact(
        _filename(project_id, resolved_channel, resolved_fmt),
        _media_type(resolved_fmt),
        text.encode("utf-8"),
    )


def render_export(
    session: Session,
    project_id: int,
    fmt: ExportFormat,
    *,
    channel: str = "generic",
    include_drafts: bool = False,
) -> str:
    artifact = build_export(
        session, project_id, fmt, channel=channel, include_drafts=include_drafts
    )
    if artifact.media_type.startswith("application/epub"):
        raise ExportSpecError("epub 请写入文件,不能按文本渲染")
    return artifact.content.decode("utf-8")


def export_project(
    session: Session,
    project_id: int,
    fmt: ExportFormat,
    out: Path | None = None,
    *,
    channel: str = "generic",
    include_drafts: bool = False,
) -> Path | str | bytes:
    artifact = build_export(
        session, project_id, fmt, channel=channel, include_drafts=include_drafts
    )
    if out is None:
        if artifact.media_type.startswith("text/"):
            return artifact.content.decode("utf-8")
        return artifact.content
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(artifact.content)
    return out
