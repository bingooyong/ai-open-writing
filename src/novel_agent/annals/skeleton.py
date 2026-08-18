from __future__ import annotations

from pydantic import Field

from novel_agent.annals.research import NullResearchPort, ResearchPort
from novel_agent.annals.span import derive_story_span, parse_story_year, plot_hit_years, widen_span
from novel_agent.annals.taxonomy import FESTIVAL_TAXONOMY, METHOD_LIBRARY_EXAMPLES
from novel_agent.domain.schemas.annals import (
    AnnalsCover,
    FestivalTaxonomyCard,
    MethodLibraryCard,
    TimelineAlignDebt,
    YearCard,
)
from novel_agent.domain.schemas.base import VersionedSchema

CANONICAL_TITLE_RULE = (
    "真实片名可写，但故事年尚未上映的作品禁止作为已存在作品说出；未上映片名只存在于年代志方法库。"
)
_EARLY = ("年初", "1月", "2月", "3月")


class AnnalsSkeleton(VersionedSchema):
    cover: AnnalsCover
    year_cards: list[YearCard] = Field(default_factory=list)
    taxonomy: list[FestivalTaxonomyCard] = Field(default_factory=list)
    methods: list[MethodLibraryCard] = Field(default_factory=list)
    debts: list[TimelineAlignDebt] = Field(default_factory=list)


def patch_kernel_title_rule(do_not_write: list[str]) -> list[str]:
    out = [
        item
        for item in do_not_write
        if "真实片名" not in item and "严禁搬运真实片名" not in item
    ]
    if CANONICAL_TITLE_RULE not in out:
        out.append(CANONICAL_TITLE_RULE)
    return out


def _debts(locked_drafts: list[tuple[str, str]]) -> list[TimelineAlignDebt]:
    found: list[TimelineAlignDebt] = []
    for key, text in locked_drafts:
        blob = text or ""
        if "柏林一种关注" in blob:
            found.append(
                TimelineAlignDebt(chapter_key=key, issue="v uses 柏林一种关注", action="flag_only")
            )
        if "戛纳" in blob and any(token in blob for token in _EARLY):
            found.append(
                TimelineAlignDebt(
                    chapter_key=key, issue="Cannes placed in 年初", action="flag_only"
                )
            )
        if "金鸡" in blob and "2006" in blob:
            found.append(
                TimelineAlignDebt(
                    chapter_key=key, issue="2006 金鸡 may be a biennial gap", action="flag_only"
                )
            )
    return found


def build_skeleton(
    *,
    kernel_texts: list[str],
    time_locations: list[str],
    volume_texts: list[str],
    locked_drafts: list[tuple[str, str]],
    span_start: int | None = None,
    span_end: int | None = None,
) -> AnnalsSkeleton:
    parsed = derive_story_span(
        kernel_texts=kernel_texts, time_locations=time_locations, volume_texts=volume_texts
    )
    if parsed is None:
        return AnnalsSkeleton(
            cover=AnnalsCover(applicable=False),
            taxonomy=list(FESTIVAL_TAXONOMY),
        )
    start, end = parsed
    if span_start is not None and span_end is not None:
        start, end = widen_span(parsed, span_start, span_end)
    hits = plot_hit_years(time_locations)
    years = [
        YearCard(year=year, density="thick" if year in hits else "thin", climate="")
        for year in range(start, end + 1)
    ]
    return AnnalsSkeleton(
        cover=AnnalsCover(
            applicable=True,
            span_start=start,
            span_end=end,
            plot_hit_years=sorted(hits),
        ),
        year_cards=years,
        taxonomy=list(FESTIVAL_TAXONOMY),
        methods=list(METHOD_LIBRARY_EXAMPLES),
        debts=_debts(locked_drafts),
    )


def fill_skeleton(skeleton: AnnalsSkeleton, port: ResearchPort) -> AnnalsSkeleton:
    years: list[YearCard] = []
    for card in skeleton.year_cards:
        awards = [row for row in card.awards if row.sources]
        sources = list(card.sources) or list(port.lookup(f"{card.year} film industry"))
        years.append(card.model_copy(update={"awards": awards, "sources": sources}))
    methods: list[MethodLibraryCard] = []
    for card in skeleton.methods:
        sources = list(card.sources) or list(port.lookup(card.film_title))
        speak = card.speak_as_existing_from_year or card.release_year
        methods.append(
            card.model_copy(update={"sources": sources, "speak_as_existing_from_year": speak})
        )
    return skeleton.model_copy(update={"year_cards": years, "methods": methods})


def confirm_errors(skeleton: AnnalsSkeleton) -> list[str]:
    if not skeleton.cover.applicable:
        return []
    errors: list[str] = []
    start, end = skeleton.cover.span_start, skeleton.cover.span_end
    have = {card.year: card for card in skeleton.year_cards}
    if start is None or end is None:
        return ["missing span"]
    for year in range(start, end + 1):
        if year not in have:
            errors.append(f"missing year {year}")
            continue
        if len(have[year].sources) < 1:
            errors.append(f"unsourced year {year}")
    for card in skeleton.methods:
        if len(card.sources) < 1 or card.release_year <= 0:
            errors.append(f"unsourced method {card.film_title}")
    return errors

def list_locked_draft_texts(session, project_id: int) -> list[tuple[str, str]]:
    from novel_agent.domain.repos.planning import PlanningRepo
    from novel_agent.domain.repos.production import ProductionRepo
    from novel_agent.domain.schemas.base import ChapterStatus

    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    found: list[tuple[str, str]] = []
    for chapter in planning.list_chapters(project_id):
        if chapter.status != ChapterStatus.CANON_LOCKED:
            continue
        draft = production.latest_chapter_draft(project_id, chapter.chapter_key)
        if draft is None:
            continue
        found.append((chapter.chapter_key, draft.content_text or ""))
    return found


def _span_texts(planning, project_id: int) -> tuple[list[str], list[str], list[str]]:
    kernel = planning.get_approved_kernel(project_id)
    kernel_texts = []
    if kernel is not None:
        kernel_texts = [
            kernel.premise,
            kernel.logline,
            kernel.reader_promise,
            *kernel.do_not_write,
        ]
    outlines = [
        planning.get_outline(project_id, ch.chapter_key)
        for ch in planning.list_chapters(project_id)
    ]
    time_locations = [item.time_location for item in outlines]
    volume_texts: list[str] = []
    for volume in planning.list_volumes(project_id):
        volume_texts.append(volume.title or "")
        volume_texts.append(str(volume.payload or ""))
    return kernel_texts, time_locations, volume_texts


def persist_annals_skeleton(planning, annals, project_id: int, skeleton: AnnalsSkeleton) -> None:
    errors = confirm_errors(skeleton)
    if errors:
        from novel_agent.planning.chain import PlanningError

        raise PlanningError("年代志未通过确认: " + "; ".join(errors))
    status = "confirmed"
    annals.upsert_cover(project_id, skeleton.cover, status=status)
    for card in skeleton.year_cards:
        annals.upsert_year(project_id, card, status=status)
    annals.replace_taxonomy(project_id, list(skeleton.taxonomy), status=status)
    annals.replace_methods(project_id, list(skeleton.methods), status=status)
    annals.replace_debts(project_id, list(skeleton.debts), status=status)
    if skeleton.cover.applicable:
        kernel = planning.get_approved_kernel(project_id)
        if kernel is not None:
            patched = kernel.model_copy(
                update={"do_not_write": patch_kernel_title_rule(list(kernel.do_not_write))}
            )
            rec = planning.save_kernel(project_id, patched)
            planning.approve_kernel(project_id, rec.version)


def ensure_annals_cover(
    planning,
    annals,
    project_id: int,
    *,
    research: ResearchPort | None = None,
    auto_not_applicable_only: bool = True,
) -> AnnalsCover | None:
    got = annals.get_cover(project_id)
    if annals.r6_complete(project_id) and got is not None:
        return got[0]
    kernel_texts, time_locations, volume_texts = _span_texts(planning, project_id)
    skeleton = build_skeleton(
        kernel_texts=kernel_texts,
        time_locations=time_locations,
        volume_texts=volume_texts,
        locked_drafts=[],
    )
    if not skeleton.cover.applicable:
        persist_annals_skeleton(planning, annals, project_id, skeleton)
        return skeleton.cover
    if auto_not_applicable_only:
        return got[0] if got else None
    filled = fill_skeleton(skeleton, research or NullResearchPort())
    persist_annals_skeleton(planning, annals, project_id, filled)
    return filled.cover


def chapter_needs_annals(planning, annals, project_id: int, chapter_key: str) -> bool:
    got = annals.get_cover(project_id)
    if got is None:
        return True
    cover, status = got
    if status != "confirmed":
        return True
    if not cover.applicable:
        return False
    outline = planning.get_outline(project_id, chapter_key)
    year = parse_story_year(outline.time_location)
    if year is None:
        return True
    got_year = annals.get_year(project_id, year)
    return got_year is None or got_year[1] != "confirmed"


def extend_annals_for_outlines(planning, annals, project_id: int) -> None:
    got = annals.get_cover(project_id)
    kernel_texts, time_locations, volume_texts = _span_texts(planning, project_id)
    parsed = derive_story_span(
        kernel_texts=kernel_texts, time_locations=time_locations, volume_texts=volume_texts
    )
    if parsed is None or got is None:
        return
    cover, status = got
    if not cover.applicable:
        return
    start, end = parsed
    if cover.span_start is not None and cover.span_end is not None:
        start, end = widen_span((cover.span_start, cover.span_end), start, end)
    hits = sorted(plot_hit_years(time_locations))
    have = {card.year for card, _st in annals.list_years(project_id)}
    for year in range(start, end + 1):
        if year not in have:
            density = "thick" if year in hits else "thin"
            annals.upsert_year(
                project_id, YearCard(year=year, density=density, climate=""), status="pending"
            )
    annals.upsert_cover(
        project_id,
        cover.model_copy(update={"span_start": start, "span_end": end, "plot_hit_years": hits}),
        status=status,
    )
