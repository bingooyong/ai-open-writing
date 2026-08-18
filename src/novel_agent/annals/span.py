from __future__ import annotations

import re

YEAR_MIN = 1900
YEAR_MAX = 2100
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)")


def extract_years(*texts: str) -> set[int]:
    found: set[int] = set()
    for text in texts:
        for match in _YEAR_RE.finditer(text or ""):
            year = int(match.group(1))
            if YEAR_MIN <= year <= YEAR_MAX:
                found.add(year)
    return found


def parse_story_year(time_location: str) -> int | None:
    for match in _YEAR_RE.finditer(time_location or ""):
        year = int(match.group(1))
        if YEAR_MIN <= year <= YEAR_MAX:
            return year
    return None


def derive_story_span(
    *,
    kernel_texts: list[str],
    time_locations: list[str],
    volume_texts: list[str] | None = None,
) -> tuple[int, int] | None:
    years = extract_years(*kernel_texts, *time_locations, *(volume_texts or []))
    if not years:
        return None
    return min(years), max(years)


def plot_hit_years(time_locations: list[str]) -> set[int]:
    found: set[int] = set()
    for item in time_locations:
        year = parse_story_year(item)
        if year is not None:
            found.add(year)
    return found


def widen_span(parsed: tuple[int, int], span_start: int, span_end: int) -> tuple[int, int]:
    req_start = min(span_start, span_end)
    req_end = max(span_start, span_end)
    start, end = parsed
    # Reject a start below YEAR_MIN (do not substitute 1900 — that would emit 1946-era cards).
    if req_start >= YEAR_MIN:
        start = min(start, min(req_start, YEAR_MAX))
    end = max(end, min(req_end, YEAR_MAX))
    start = max(YEAR_MIN, start)
    end = min(YEAR_MAX, end)
    if start > end:
        start, end = parsed
    return min(start, parsed[0]), max(end, parsed[1])
