from novel_agent.annals.span import (
    derive_story_span,
    extract_years,
    parse_story_year,
    plot_hit_years,
    widen_span,
)


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
