from novel_agent.domain.schemas.annals import (
    FestivalTaxonomyCard,
    MethodLibraryCard,
    SourceRef,
)


def seed_source(key: str) -> SourceRef:
    return SourceRef(source="factory_seed", key=key)


FESTIVAL_TAXONOMY: tuple[FestivalTaxonomyCard, ...] = (
    FestivalTaxonomyCard(
        festival_id="cannes",
        section_names=["一种关注", "主竞赛", "Un Certain Regard", "Competition"],
        not_section_names=[],
        typical_calendar="mid-May; not 年初",
        sources=[seed_source("cannes-calendar")],
    ),
    FestivalTaxonomyCard(
        festival_id="berlin",
        section_names=["Competition", "Panorama", "Forum", "主竞赛", "全景", "论坛"],
        not_section_names=["一种关注"],
        typical_calendar="February",
        sources=[seed_source("berlin-sections")],
    ),
    FestivalTaxonomyCard(
        festival_id="venice",
        section_names=["主竞赛", "Competition"],
        not_section_names=["一种关注"],
        typical_calendar="August-September",
        sources=[seed_source("venice-calendar")],
    ),
    FestivalTaxonomyCard(
        festival_id="golden_rooster",
        section_names=["金鸡"],
        not_section_names=[],
        typical_calendar="not a safe annual in mid-2000s (2005 then 2007)",
        sources=[seed_source("golden-rooster-biennial")],
    ),
    FestivalTaxonomyCard(
        festival_id="golden_horse",
        section_names=["金马"],
        not_section_names=[],
        typical_calendar="annual, usually Q4",
        sources=[seed_source("golden-horse")],
    ),
)

FORBIDDEN_SECTION_PHRASES: tuple[str, ...] = ("柏林一种关注", "戛纳年初")

METHOD_LIBRARY_EXAMPLES: tuple[MethodLibraryCard, ...] = (
    MethodLibraryCard(
        film_title="活埋",
        release_year=2010,
        speak_as_existing_from_year=2010,
        craft=(
            "single location, prop ceiling, phone as second space, "
            "do not cut to the other end of the call"
        ),
        sources=[seed_source("buried-2010")],
    ),
    MethodLibraryCard(
        film_title="调音师",
        release_year=2010,
        speak_as_existing_from_year=2010,
        craft="hearing as cover; French short later César 2012 / Andhadhun 2018",
        sources=[seed_source("tuner-2010")],
    ),
    MethodLibraryCard(
        film_title="小偷家族",
        release_year=2018,
        speak_as_existing_from_year=2018,
        craft="Cannes 2018 Palme method, not a 2005 existing title",
        sources=[seed_source("shoploifters-2018")],
    ),
    MethodLibraryCard(
        film_title="海边的曼彻斯特",
        release_year=2016,
        speak_as_existing_from_year=2016,
        craft="Oscar 2017 actor+screenplay grief structure",
        sources=[seed_source("manchester-2016")],
    ),
    MethodLibraryCard(
        film_title="入殓师",
        release_year=2008,
        speak_as_existing_from_year=2008,
        craft="Montreal 2008 / Oscar 2009 foreign language; 入检师 is the same fence",
        sources=[seed_source("departures-2008")],
    ),
)
