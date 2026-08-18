from __future__ import annotations

from pydantic import Field

from novel_agent.annals.research import ResearchPort
from novel_agent.annals.span import derive_story_span, plot_hit_years, widen_span
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
