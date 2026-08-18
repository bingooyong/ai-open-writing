from novel_agent.annals.span import (
    derive_story_span,
    extract_years,
    parse_story_year,
    plot_hit_years,
    widen_span,
)
from novel_agent.annals.taxonomy import (
    FESTIVAL_TAXONOMY,
    FORBIDDEN_SECTION_PHRASES,
    METHOD_LIBRARY_EXAMPLES,
)
from novel_agent.domain.schemas import AnnalsSlice, ChapterContextPackage
from novel_agent.domain.schemas.annals import MethodLibraryCard, YearCard


def test_extract_years_ignores_out_of_range_and_non_years() -> None:
    assert extract_years("2005秋 北影厂", "金鸡") == {2005}
    assert extract_years("1899", "2101", "abc") == set()
    assert extract_years("2005-2008") == {2005, 2008}


def test_parse_story_year_first_in_range() -> None:
    assert parse_story_year("2005秋,北影厂") == 2005
    assert parse_story_year("2008年初 戛纳") == 2008
    assert parse_story_year("临安城,春夜茶楼") is None


def test_derive_span_none_when_no_years() -> None:
    assert (
        derive_story_span(
            kernel_texts=["落魄说书人"],
            time_locations=["临安城,v1c001"],
            volume_texts=["卷一"],
        )
        is None
    )


def test_derive_span_min_max_inclusive() -> None:
    assert derive_story_span(
        kernel_texts=["2005年穿回去"],
        time_locations=["2005秋", "2008年初"],
        volume_texts=[],
    ) == (2005, 2008)


def test_no_default_two_thousand_five() -> None:
    assert derive_story_span(kernel_texts=[], time_locations=[], volume_texts=[]) is None


def test_plot_hit_from_time_location_only() -> None:
    assert plot_hit_years(["2005秋", "临安", "2008年初"]) == {2005, 2008}


def test_widen_unions_and_does_not_shrink() -> None:
    assert widen_span((2005, 2008), 2005, 2025) == (2005, 2025)
    assert widen_span((2005, 2008), 2006, 2007) == (2005, 2008)


def test_widen_rejects_out_of_range_by_clamp() -> None:
    assert widen_span((2005, 2008), 1800, 2200) == (2005, 2100)


def test_berlin_must_not_be_un_certain_regard() -> None:
    berlin = next(card for card in FESTIVAL_TAXONOMY if card.festival_id == "berlin")
    cannes = next(card for card in FESTIVAL_TAXONOMY if card.festival_id == "cannes")
    assert "一种关注" in berlin.not_section_names
    assert "一种关注" in cannes.section_names
    assert "柏林一种关注" in FORBIDDEN_SECTION_PHRASES
    assert "戛纳年初" in FORBIDDEN_SECTION_PHRASES
    assert "mid-May" in cannes.typical_calendar or "5月" in cannes.typical_calendar


def test_method_examples_have_release_years() -> None:
    assert all(isinstance(card, MethodLibraryCard) for card in METHOD_LIBRARY_EXAMPLES)
    by_title = {card.film_title: card.release_year for card in METHOD_LIBRARY_EXAMPLES}
    assert by_title["活埋"] == 2010
    assert by_title["小偷家族"] == 2018
    assert by_title["入殓师"] == 2008
    assert by_title["海边的曼彻斯特"] == 2016
    assert "调音师" in by_title


def test_year_card_allows_empty_sources_for_skeleton() -> None:
    card = YearCard(year=2005, density="thick", climate="x", sources=[])
    assert card.sources == []


def test_context_package_defaults_not_applicable_annals() -> None:
    # Constructing without annals must not crash; default applicable=False.
    assert AnnalsSlice(applicable=False).title_fence == []
    factory = ChapterContextPackage.model_fields["annals"].default_factory
    assert factory is not None
    assert factory().applicable is False
