from novel_agent.annals.span import parse_story_year
from novel_agent.domain.schemas.annals import AnnalsSlice, MethodLibraryCard, TitleRelease
from novel_agent.domain.schemas.outline import ChapterOutline


def title_fence(
    methods: list[MethodLibraryCard],
    story_year: int,
    title_releases: list[TitleRelease] | None = None,
) -> list[str]:
    fenced: list[str] = []
    for card in methods:
        year = card.speak_as_existing_from_year or card.release_year
        if year > story_year and card.film_title not in fenced:
            fenced.append(card.film_title)
    for item in title_releases or []:
        if item.release_year > story_year and item.film_title not in fenced:
            fenced.append(item.film_title)
    return fenced


def annals_slice_for_chapter(annals, project_id: int, outline: ChapterOutline) -> AnnalsSlice:
    got = annals.get_cover(project_id)
    if got is None:
        return AnnalsSlice(applicable=False)
    cover, status = got
    if not cover.applicable or status != "confirmed":
        return AnnalsSlice(applicable=False)
    year = parse_story_year(outline.time_location)
    if year is None:
        raise ValueError("无法构建上下文: 章纲缺少故事年")
    got_year = annals.get_year(project_id, year)
    if got_year is None or got_year[1] != "confirmed":
        raise ValueError("无法构建上下文: 年代志年卡缺失或未确认")
    year_card, _st = got_year
    methods = annals.list_methods(project_id)
    notes = [
        f"{card.festival_id}: {card.typical_calendar}"
        for card in annals.list_taxonomy(project_id)
    ]
    debts = [
        item.issue
        for item in annals.list_debts(project_id)
        if item.chapter_key == outline.chapter_key
    ]
    return AnnalsSlice(
        applicable=True,
        story_year=year,
        year_card=year_card,
        festival_notes=notes,
        method_library=methods,
        title_fence=title_fence(methods, year, year_card.title_releases),
        timeline_debts=debts,
    )
