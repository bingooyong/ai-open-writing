from typing import Literal

from pydantic import Field

from novel_agent.domain.schemas.base import VersionedSchema


class SourceRef(VersionedSchema):
    url: str = ""
    excerpt: str = ""
    accessed: str = ""
    source: str = ""
    key: str = ""


class FestivalBeat(VersionedSchema):
    festival_id: str
    note: str = ""


class AwardBeat(VersionedSchema):
    category: str
    film_title: str = ""
    sources: list[SourceRef] = Field(default_factory=list)


class TitleRelease(VersionedSchema):
    film_title: str
    release_year: int


class YearCard(VersionedSchema):
    year: int
    density: Literal["thick", "thin"]
    climate: str = ""
    festivals: list[FestivalBeat] = Field(default_factory=list)
    awards: list[AwardBeat] = Field(default_factory=list)
    title_releases: list[TitleRelease] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class FestivalTaxonomyCard(VersionedSchema):
    festival_id: str
    section_names: list[str] = Field(default_factory=list)
    not_section_names: list[str] = Field(default_factory=list)
    typical_calendar: str = ""
    sources: list[SourceRef] = Field(default_factory=list)


class MethodLibraryCard(VersionedSchema):
    film_title: str
    release_year: int
    craft: str = ""
    speak_as_existing_from_year: int = 0
    sources: list[SourceRef] = Field(default_factory=list)


class TimelineAlignDebt(VersionedSchema):
    chapter_key: str
    issue: str
    action: Literal["flag_only"] = "flag_only"
    sources: list[SourceRef] = Field(default_factory=list)


class AnnalsCover(VersionedSchema):
    applicable: bool
    span_start: int | None = None
    span_end: int | None = None
    plot_hit_years: list[int] = Field(default_factory=list)


class AnnalsSlice(VersionedSchema):
    applicable: bool
    story_year: int | None = None
    year_card: YearCard | None = None
    festival_notes: list[str] = Field(default_factory=list)
    method_library: list[MethodLibraryCard] = Field(default_factory=list)
    title_fence: list[str] = Field(default_factory=list)
    timeline_debts: list[str] = Field(default_factory=list)
