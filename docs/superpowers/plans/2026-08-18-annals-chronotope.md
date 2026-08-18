# 年代志 (Annals / Chronotope) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Factory will not write an era chapter until a confirmed 年代志 cover exists, injects an `AnnalsSlice` for that story year, and refuses to lock drafts that speak unreleased titles or wrong festival sections.

**Architecture:** Pure span parser and festival seeds first (no LLM). Persist cards in `annals_card` via `AnnalsRepo`. R6 after R5: no years → auto-confirm `applicable=False`; years → skeleton + `ResearchPort` fill, human confirm, kernel title-rule patch. `ChapterContextPackage.annals` is required content. `LockGates` gains title/section/Cannes-calendar detectors. `volume_run` / `run_chapter_loop` fail with `NEEDS_ANNALS` before n2 when the chapter year is unconfirmed. Writer/Judge prompts stay untouched.

**Tech Stack:** Python 3.12, uv, pytest, SQLModel, Alembic, pydantic `VersionedSchema`, existing `LockGates` / `ContextBuilder` / bible rounds. `httpx` already in `pyproject.toml` for `WebResearchPort` (CI mocks HTTP).

**Spec:** `docs/superpowers/specs/2026-08-18-annals-chronotope-design.md`

## Global Constraints

- Do not rewrite Writer, Judge, or retrieval prompts.
- Ports stay `8765` / `18765`. No Redis. No second runner.
- Leave draft PR #24 alone. Do not reopen outline-sanitizer or lock-gates-from-audit detectors except to extend `LockGates` with the three annals fields below.
- Do not add fields to `ChapterOutline` (`time_location` stays a string).
- Do not rewrite locked vol.1 prose. Timeline debts are `flag_only`.
- Do not dump filled 《穿回去当导演》 year cards onto this public repo.
- Do not default a span to 2005. Do not emit Palme-d'Or-from-1946 cards.
- Do not ask an LLM to fill award winners. Awards without `SourceRef` are dropped, never invented.
- Factory never auto-widens span to 2025. Human may widen `span_start`/`span_end` on the pending artifact (union with parsed years, still `1900–2100`).
- Kernel title-rule patch runs only when `applicable=True`. Canonical item: `真实片名可写，但故事年尚未上映的作品禁止作为已存在作品说出；未上映片名只存在于年代志方法库。`
- Do not change Judge-calibration sample IDs `R1`–`R6` in `tests/regression/test_samples.py`. Those are sample IDs, not bible rounds.
- No paid APIs / live web in pytest. Command prefix: `UV_PYTHON_PREFERENCE=managed uv run pytest -q`
- After every task: that pytest slice green, then `uv run ruff check` on files the task touched.
- Commit per task. Ship as one PR after Task 8.

## File map

Create:

- `src/novel_agent/annals/__init__.py` — public helpers
- `src/novel_agent/annals/span.py` — year parse + span + plot-hit + widen
- `src/novel_agent/annals/taxonomy.py` — `factory_seed` festival taxonomy + method examples + forbidden phrases
- `src/novel_agent/annals/research.py` — `ResearchPort`, `NullResearchPort`, `WebResearchPort`
- `src/novel_agent/annals/skeleton.py` — build skeleton, fill from port, confirm eligibility, kernel patch, debt scan
- `src/novel_agent/annals/slice.py` — `annals_slice_for_chapter`
- `src/novel_agent/domain/schemas/annals.py` — card schemas + `AnnalsSlice` + `AnnalsCover`
- `src/novel_agent/domain/repos/annals.py` — `AnnalsRepo`
- `alembic/versions/f8b2d4e6a103_annals_card.py`
- `tests/unit/test_annals_span.py`
- `tests/unit/test_annals_research.py`
- `tests/unit/test_annals_context.py`
- `tests/unit/test_annals_repo.py`
- `tests/workflow/test_annals_volume.py`

Modify:

- `src/novel_agent/domain/schemas/context_package.py` — required `annals: AnnalsSlice`
- `src/novel_agent/domain/schemas/__init__.py` — export new types
- `src/novel_agent/domain/models/tables.py` — `AnnalsCardRecord`
- `src/novel_agent/domain/models/__init__.py` — export record
- `src/novel_agent/domain/repos/__init__.py` — export `AnnalsRepo`
- `src/novel_agent/domain/repos/bible.py` — `round_complete` adds `R6` via `AnnalsRepo`
- `src/novel_agent/planning/rounds.py` — `ROUND_KINDS` + R6 generate/confirm/persist
- `src/novel_agent/planning/conversation.py` — `_ensure_r6` after R5
- `src/novel_agent/planning/chain.py` — after planning, `ensure_annals_cover` so 临安 fixtures auto-complete `not_applicable`
- `src/novel_agent/planning/volume.py` — after `plan_more` outlines, extend unconfirmed year cards
- `src/novel_agent/context/context_builder.py` — inject slice; missing applicable year raises
- `src/novel_agent/production/factory.py` — `LockGates` three fields + detectors
- `src/novel_agent/production/loop.py` — `LockGates` from `package.annals`; refuse `NEEDS_ANNALS` before n2
- `src/novel_agent/production/volume_run.py` — `VolumeStopReason.NEEDS_ANNALS`
- `src/novel_agent/verification/m26_smoke.py` — default slice (or rely on Field default)
- `tests/unit/test_factory_gates.py` — title/section/Cannes fixtures
- `tests/contract/test_story_bible.py` — R5 exact set still excludes R6 until cover; new cover cases

Do not modify: Writer/Judge prompt modules, PR #24, locked vol.1, `tests/regression/test_samples.py` sample IDs.

---

### Task 1: Year parser and span

**Files:**
- Create: `src/novel_agent/annals/__init__.py`
- Create: `src/novel_agent/annals/span.py`
- Test: `tests/unit/test_annals_span.py`

**Interfaces:**
- Consumes: kernel/outline/volume text strings (no DB)
- Produces:
  - `YEAR_MIN = 1900`
  - `YEAR_MAX = 2100`
  - `extract_years(*texts: str) -> set[int]`
  - `parse_story_year(time_location: str) -> int | None` (first in-range year, else None)
  - `derive_story_span(*, kernel_texts: list[str], time_locations: list[str], volume_texts: list[str] | None = None) -> tuple[int, int] | None` (None = not applicable)
  - `plot_hit_years(time_locations: list[str]) -> set[int]`
  - `widen_span(parsed: tuple[int, int], span_start: int, span_end: int) -> tuple[int, int]` (union with parsed; clamp to 1900–2100; never shrink below parsed)

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_span.py -v`

Expected: FAIL with `ModuleNotFoundError` or `cannot import name`

- [ ] **Step 3: Write minimal implementation**

`src/novel_agent/annals/span.py`:

```python
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
    years = extract_years(time_location)
    if not years:
        return None
    first = _YEAR_RE.search(time_location or "")
    if first is None:
        return None
    year = int(first.group(1))
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
    start = min(parsed[0], span_start, parsed[1], span_end)
    end = max(parsed[0], span_start, parsed[1], span_end)
    start = max(YEAR_MIN, start)
    end = min(YEAR_MAX, end)
    if start > end:
        start, end = parsed
    return min(start, parsed[0]), max(end, parsed[1])
```

`src/novel_agent/annals/__init__.py`:

```python
from novel_agent.annals.span import (
    YEAR_MAX,
    YEAR_MIN,
    derive_story_span,
    extract_years,
    parse_story_year,
    plot_hit_years,
    widen_span,
)

__all__ = [
    "YEAR_MAX",
    "YEAR_MIN",
    "derive_story_span",
    "extract_years",
    "parse_story_year",
    "plot_hit_years",
    "widen_span",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_span.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/annals/__init__.py src/novel_agent/annals/span.py tests/unit/test_annals_span.py
git commit -m "feat: parse story years and derive 年代志 span"
```

---

### Task 2: Annals schemas and factory-seed taxonomy

**Files:**
- Create: `src/novel_agent/domain/schemas/annals.py`
- Create: `src/novel_agent/annals/taxonomy.py`
- Modify: `src/novel_agent/domain/schemas/__init__.py`
- Modify: `src/novel_agent/domain/schemas/context_package.py`
- Test: `tests/unit/test_annals_span.py` (append schema/taxonomy tests)

**Interfaces:**
- Consumes: `VersionedSchema`
- Produces: `SourceRef`, `FestivalBeat`, `AwardBeat`, `TitleRelease`, `YearCard`, `FestivalTaxonomyCard`, `MethodLibraryCard`, `TimelineAlignDebt`, `AnnalsCover`, `AnnalsSlice`; `FESTIVAL_TAXONOMY`, `METHOD_LIBRARY_EXAMPLES`, `FORBIDDEN_SECTION_PHRASES`, `seed_source(key: str) -> SourceRef`; `ChapterContextPackage.annals` default `AnnalsSlice(applicable=False)`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_annals_span.py`:

```python
from novel_agent.annals.taxonomy import (
    FORBIDDEN_SECTION_PHRASES,
    FESTIVAL_TAXONOMY,
    METHOD_LIBRARY_EXAMPLES,
)
from novel_agent.domain.schemas import AnnalsSlice, ChapterContextPackage
from novel_agent.domain.schemas.annals import MethodLibraryCard, YearCard


def test_berlin_must_not_be_un_certain_regard() -> None:
    berlin = next(card for card in FESTIVAL_TAXONOMY if card.festival_id == "berlin")
    cannes = next(card for card in FESTIVAL_TAXONOMY if card.festival_id == "cannes")
    assert "一种关注" in berlin.not_section_names
    assert "一种关注" in cannes.section_names
    assert "柏林一种关注" in FORBIDDEN_SECTION_PHRASES
    assert "戛纳年初" in FORBIDDEN_SECTION_PHRASES
    assert "mid-May" in cannes.typical_calendar or "5月" in cannes.typical_calendar


def test_method_examples_have_release_years() -> None:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_span.py -v`

Expected: FAIL import of taxonomy/schemas

- [ ] **Step 3: Write minimal implementation**

`src/novel_agent/domain/schemas/annals.py` — full file:

```python
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
```

In `MethodLibraryCard`, if `speak_as_existing_from_year` is 0, treat it as `release_year` at persist time in Task 5 (`card.speak_as_existing_from_year or card.release_year`).

`src/novel_agent/annals/taxonomy.py`:

```python
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
        craft="single location, prop ceiling, phone as second space, do not cut to the other end of the call",
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
```

`context_package.py`: add import and field:

```python
from novel_agent.domain.schemas.annals import AnnalsSlice
```

Inside `ChapterContextPackage`:

```python
    annals: AnnalsSlice = Field(default_factory=lambda: AnnalsSlice(applicable=False))
```

Export from `schemas/__init__.py`: `AnnalsCover`, `AnnalsSlice`, `AwardBeat`, `FestivalTaxonomyCard`, `MethodLibraryCard`, `SourceRef`, `TimelineAlignDebt`, `TitleRelease`, `YearCard`.

- [ ] **Step 4: Run tests**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_span.py -v`

Expected: PASS. Also run a quick import of existing context tests if any fail on extra=forbid — default_factory keeps old constructors valid.

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/verification/test_m26_smoke.py tests/eval -q --maxfail=1` only if those modules import `ChapterContextPackage` without the new field; they should pass because of the default.

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/domain/schemas/annals.py src/novel_agent/domain/schemas/__init__.py src/novel_agent/domain/schemas/context_package.py src/novel_agent/annals/taxonomy.py tests/unit/test_annals_span.py
git commit -m "feat: 年代志 schemas and factory-seed festival taxonomy"
```

---

### Task 3: LockGates for future titles, wrong sections, Cannes calendar

**Files:**
- Modify: `src/novel_agent/production/factory.py` (`LockGates` at line 88, `is_lockable_draft` at line 320)
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: existing `is_lockable_draft`, `_long_prose`
- Produces: `LockGates.annals_year: int | None = None`, `LockGates.forbidden_titles: list[str] | None = None`, `LockGates.forbidden_section_phrases: list[str] | None = None`; `_annals_blocks(text, gates) -> bool`; title aliases map `入殓师` → also `入检师`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_factory_gates.py`:

```python
def _annals_gates(year: int, titles: list[str], phrases: list[str] | None = None) -> LockGates:
    return LockGates(
        required_names=["林朔"],
        pov="林朔",
        annals_year=year,
        forbidden_titles=titles,
        forbidden_section_phrases=phrases or ["柏林一种关注", "戛纳年初"],
    )


def test_future_title_活埋_not_lockable_in_2005() -> None:
    gates = _annals_gates(2005, ["活埋", "小偷家族", "海边的曼彻斯特", "调音师", "入殓师"])
    prose = _long_prose() + "林朔盯着监视器。他想起《活埋》。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is False


def test_future_title_thief_family_and_manchester() -> None:
    gates = _annals_gates(2005, ["活埋", "小偷家族", "海边的曼彻斯特", "调音师", "入殓师"])
    assert is_lockable_draft(_long_prose() + "林朔说《小偷家族》已经拿了金棕榈。", [], ["林朔"], gates) is False
    assert is_lockable_draft(_long_prose() + "林朔说《海边的曼彻斯特》拿了剧本奖。", [], ["林朔"], gates) is False
    assert is_lockable_draft(_long_prose() + "林朔说《调音师》那种听音的办法。", [], ["林朔"], gates) is False


def test_departures_typo_is_fenced() -> None:
    gates = _annals_gates(2005, ["入殓师"])
    assert is_lockable_draft(_long_prose() + "林朔提了入殓师。", [], ["林朔"], gates) is False
    assert is_lockable_draft(_long_prose() + "林朔提了入检师。", [], ["林朔"], gates) is False


def test_1997_event_horizon_not_fenced() -> None:
    gates = _annals_gates(2005, ["活埋"])
    prose = _long_prose() + "林朔说《黑洞》那种1997年的封闭空间。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True


def test_lin_shuo_original_title_not_blocked() -> None:
    gates = _annals_gates(2005, ["活埋"])
    prose = _long_prose() + "林朔把《场记板》这个自己的名字写在通告上。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True


def test_berlin_un_certain_regard_not_lockable() -> None:
    gates = _annals_gates(2007, ["活埋"], ["柏林一种关注", "戛纳年初"])
    prose = _long_prose() + "林朔站在柏林一种关注放映厅门口。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is False


def test_cannes_plus_early_year_not_lockable_but_cannes_alone_ok() -> None:
    gates = _annals_gates(2008, ["活埋"], ["柏林一种关注", "戛纳年初"])
    assert is_lockable_draft(_long_prose() + "林朔去戛纳，年初机票就订了。", [], ["林朔"], gates) is False
    assert is_lockable_draft(_long_prose() + "林朔去戛纳，5月的阳光很白。", [], ["林朔"], gates) is True


def test_clean_2005_prose_still_lockable() -> None:
    gates = _annals_gates(2005, ["活埋", "小偷家族"])
    prose = _long_prose() + "手贴上去的时候没有犹豫。林朔盯着监视器。"
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True


def test_annals_gate_skipped_when_gates_omitted() -> None:
    prose = _long_prose() + "他想起《活埋》。林朔盯着监视器。"
    assert is_lockable_draft(prose, [], ["林朔"]) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_factory_gates.py::test_future_title_活埋_not_lockable_in_2005 -v`

Expected: FAIL (`LockGates` unexpected keyword `annals_year` or test assertion True is not False)

- [ ] **Step 3: Write minimal implementation**

In `factory.py` extend `LockGates`:

```python
@dataclass(frozen=True)
class LockGates:
    required_names: list[str] | None = None
    pov: str = ""
    pov_person: str | None = None
    chapter_index: int | None = None
    card_names: list[str] | None = None
    schedule: list[tuple[int, str]] | None = None
    reveal_forbidden: list[str] | None = None
    annals_year: int | None = None
    forbidden_titles: list[str] | None = None
    forbidden_section_phrases: list[str] | None = None
```

Add:

```python
_TITLE_ALIASES = {"入殓师": ("入殓师", "入检师")}
_CANNES_EARLY = ("年初", "1月", "2月", "3月")


def _title_aliases(title: str) -> tuple[str, ...]:
    return _TITLE_ALIASES.get(title, (title,))


def _annals_blocks(text: str, gates: LockGates | None) -> bool:
    if gates is None:
        return False
    blob = text or ""
    for title in gates.forbidden_titles or []:
        for alias in _title_aliases(title):
            if alias and alias in blob:
                return True
    phrases = list(gates.forbidden_section_phrases or [])
    if "戛纳年初" in phrases and "戛纳" in blob and any(token in blob for token in _CANNES_EARLY):
        return True
    for phrase in phrases:
        if phrase and phrase != "戛纳年初" and phrase in blob:
            return True
    return False
```

In `is_lockable_draft`, after `_unscheduled_character_blocks`:

```python
    if _annals_blocks(text, gates):
        return False
```

Do not add `活埋` to `_HARD_GATE_LEAK_RE`. Annals fencing is gates-only so 临安 tests without gates still pass.

- [ ] **Step 4: Run tests**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_factory_gates.py -v`

Expected: PASS (existing POV/徐姐/mechanism tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/production/factory.py tests/unit/test_factory_gates.py
git commit -m "feat: lock-gate future titles and wrong festival sections"
```

---

### Task 4: `annals_card` table and `AnnalsRepo`

**Files:**
- Modify: `src/novel_agent/domain/models/tables.py`
- Modify: `src/novel_agent/domain/models/__init__.py`
- Create: `src/novel_agent/domain/repos/annals.py`
- Modify: `src/novel_agent/domain/repos/__init__.py`
- Create: `alembic/versions/f8b2d4e6a103_annals_card.py`
- Test: `tests/unit/test_annals_repo.py`

**Interfaces:**
- Consumes: `AnnalsCover`, `YearCard`, `FestivalTaxonomyCard`, `MethodLibraryCard`, `TimelineAlignDebt`
- Produces:
  - `class AnnalsCardRecord` table `annals_card`, UniqueConstraint `(project_id, kind, card_key)`
  - `AnnalsRepo.upsert_cover(project_id, cover: AnnalsCover, *, status: str) -> None`
  - `AnnalsRepo.get_cover(project_id) -> tuple[AnnalsCover, str] | None` (schema, status)
  - `AnnalsRepo.upsert_year(project_id, card: YearCard, *, status: str) -> None`
  - `AnnalsRepo.get_year(project_id, year: int) -> tuple[YearCard, str] | None`
  - `AnnalsRepo.list_years(project_id) -> list[tuple[YearCard, str]]`
  - `AnnalsRepo.replace_taxonomy(project_id, cards: list[FestivalTaxonomyCard], *, status: str) -> None`
  - `AnnalsRepo.list_taxonomy(project_id) -> list[FestivalTaxonomyCard]`
  - `AnnalsRepo.replace_methods(project_id, cards: list[MethodLibraryCard], *, status: str) -> None`
  - `AnnalsRepo.list_methods(project_id) -> list[MethodLibraryCard]`
  - `AnnalsRepo.replace_debts(project_id, cards: list[TimelineAlignDebt], *, status: str) -> None`
  - `AnnalsRepo.list_debts(project_id) -> list[TimelineAlignDebt]`
  - `AnnalsRepo.r6_complete(project_id) -> bool`
  - kinds: `cover` / `year` / `festival_taxonomy` / `method` / `timeline_debt`
  - cover `card_key` is always `"cover"`; year `card_key` is `str(year)`

`r6_complete`: cover exists and status is `confirmed`, and either `applicable is False`, or every year in `[span_start, span_end]` has a row and every year in `cover.plot_hit_years` has status `confirmed`.

- [ ] **Step 1: Write the failing test**

```python
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import AnnalsRepo, PlanningRepo
from novel_agent.domain.schemas.annals import AnnalsCover, YearCard
from novel_agent.annals.taxonomy import seed_source


def test_cover_and_year_roundtrip_and_r6_complete(tmp_path) -> None:
    engine = build_engine(tmp_path / "annals.db")
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("年代志").id
        repo = AnnalsRepo(session)
        assert repo.get_cover(pid) is None
        assert repo.r6_complete(pid) is False
        repo.upsert_cover(
            pid,
            AnnalsCover(applicable=False),
            status="confirmed",
        )
        cover, status = repo.get_cover(pid)
        assert cover.applicable is False
        assert status == "confirmed"
        assert repo.r6_complete(pid) is True


def test_applicable_cover_requires_plot_hit_years(tmp_path) -> None:
    engine = build_engine(tmp_path / "annals2.db")
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("导演").id
        repo = AnnalsRepo(session)
        repo.upsert_cover(
            pid,
            AnnalsCover(applicable=True, span_start=2005, span_end=2006, plot_hit_years=[2005]),
            status="confirmed",
        )
        assert repo.r6_complete(pid) is False
        repo.upsert_year(
            pid,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("x")]),
            status="pending",
        )
        repo.upsert_year(
            pid,
            YearCard(year=2006, density="thin", climate="c", sources=[seed_source("y")]),
            status="confirmed",
        )
        assert repo.r6_complete(pid) is False
        repo.upsert_year(
            pid,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("x")]),
            status="confirmed",
        )
        assert repo.r6_complete(pid) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_repo.py -v`

Expected: FAIL import `AnnalsRepo`

- [ ] **Step 3: Write minimal implementation**

`AnnalsCardRecord` in `tables.py` (after `PayoffBeatRecord` is fine):

```python
class AnnalsCardRecord(SQLModel, table=True):
    __tablename__ = "annals_card"
    __table_args__ = (UniqueConstraint("project_id", "kind", "card_key"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str = Field(index=True)
    card_key: str = Field(index=True)
    year: int | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    payload: dict = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
```

Export in `models/__init__.py`.

Alembic file `alembic/versions/f8b2d4e6a103_annals_card.py`:

```python
"""annals_card table for 年代志 R6

Revision ID: f8b2d4e6a103
Revises: e7a1c3d5f902
Create Date: 2026-08-18 05:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8b2d4e6a103"
down_revision: str | Sequence[str] | None = "e7a1c3d5f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annals_card",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("card_key", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "kind", "card_key"),
    )
    op.create_index("ix_annals_card_project_id", "annals_card", ["project_id"])
    op.create_index("ix_annals_card_kind", "annals_card", ["kind"])
    op.create_index("ix_annals_card_card_key", "annals_card", ["card_key"])
    op.create_index("ix_annals_card_year", "annals_card", ["year"])
    op.create_index("ix_annals_card_status", "annals_card", ["status"])


def downgrade() -> None:
    op.drop_index("ix_annals_card_status", table_name="annals_card")
    op.drop_index("ix_annals_card_year", table_name="annals_card")
    op.drop_index("ix_annals_card_card_key", table_name="annals_card")
    op.drop_index("ix_annals_card_kind", table_name="annals_card")
    op.drop_index("ix_annals_card_project_id", table_name="annals_card")
    op.drop_table("annals_card")
```

`AnnalsRepo` implements upsert via select-by unique key then overwrite payload/status/year/updated_at. `r6_complete` as specified.

`create_all` picks up the table once the model is imported (models `__init__` is imported by repos). Import `AnnalsCardRecord` from `novel_agent.domain.models` inside `annals.py` repo.

- [ ] **Step 4: Run tests**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_repo.py tests/contract/test_story_bible.py::test_bible_repo_crud_and_round_complete -v`

Expected: PASS (round_complete still R0–R5 only; R6 wiring is Task 6)

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/domain/models/tables.py src/novel_agent/domain/models/__init__.py src/novel_agent/domain/repos/annals.py src/novel_agent/domain/repos/__init__.py alembic/versions/f8b2d4e6a103_annals_card.py tests/unit/test_annals_repo.py
git commit -m "feat: persist 年代志 cards in annals_card"
```

---

### Task 5: ResearchPort, skeleton, confirm rules, kernel title patch

**Files:**
- Create: `src/novel_agent/annals/research.py`
- Create: `src/novel_agent/annals/skeleton.py`
- Modify: `src/novel_agent/annals/__init__.py`
- Test: `tests/unit/test_annals_research.py`

**Interfaces:**
- Consumes: span helpers, taxonomy seeds, `StoryKernel.do_not_write`, outline `time_location`s, locked draft texts
- Produces:
  - `class ResearchPort(Protocol): def lookup(self, query: str) -> list[SourceRef]: ...`
  - `class NullResearchPort: def lookup(self, query: str) -> list[SourceRef]: return []`
  - `class WebResearchPort: def __init__(self, client: httpx.Client | None = None) -> None` / `lookup` — if `query` starts with `http://` or `https://`, GET it and wrap `SourceRef(url=query, excerpt=text[:240])`; else GET Wikipedia opensearch and wrap first hit; empty HTTP → `[]`. Never fabricate a winner name.
  - `class AnnalsSkeleton(VersionedSchema)` with fields `cover: AnnalsCover`, `year_cards: list[YearCard]`, `taxonomy: list[FestivalTaxonomyCard]`, `methods: list[MethodLibraryCard]`, `debts: list[TimelineAlignDebt]`
  - `build_skeleton(*, kernel_texts, time_locations, volume_texts, locked_drafts: list[tuple[str, str]], span_start: int | None = None, span_end: int | None = None) -> AnnalsSkeleton`
  - `fill_skeleton(skeleton: AnnalsSkeleton, port: ResearchPort) -> AnnalsSkeleton`
  - `confirm_errors(skeleton: AnnalsSkeleton) -> list[str]` (empty means confirmable)
  - `patch_kernel_title_rule(do_not_write: list[str]) -> list[str]`
  - `CANONICAL_TITLE_RULE = "真实片名可写，但故事年尚未上映的作品禁止作为已存在作品说出；未上映片名只存在于年代志方法库。"`

Skeleton rules:
- `derive_story_span` None → cover `applicable=False`, empty year_cards, taxonomy still seeded, methods empty, debts empty.
- Else parsed span, optional widen via `span_start`/`span_end`, one `YearCard` per year: `density="thick"` iff year in `plot_hit_years`, else `"thin"`. Climate placeholder `""`. sources `[]`.
- Taxonomy always copied from `FESTIVAL_TAXONOMY`.
- Methods: copy `METHOD_LIBRARY_EXAMPLES` only when applicable (era). Not-applicable gets no methods.
- Debts: for each `(chapter_key, text)` if `"柏林一种关注" in text` or (`"戛纳" in text` and any of 年初/1月/2月/3月) or (`"金鸡" in text` and `"2006" in text` and chapter is locked scan input), append `TimelineAlignDebt(chapter_key, issue=..., action="flag_only")`. Do not rewrite text.

`fill_skeleton`: for each year card with empty sources, `sources = port.lookup(f"{year} film industry")`. Do not add `awards` rows. If a year card already has awards without sources, drop those award rows (never LLM-backfill). Methods with empty sources get `port.lookup(film_title)`; still empty stays empty.

`confirm_errors`:
- applicable False → `[]`
- missing year in span → error
- plot-hit year with `len(sources) < 1` → error
- thin year with `len(sources) < 1` → error
- method with `len(sources) < 1` or `release_year <= 0` → error

`patch_kernel_title_rule`: drop any item containing `真实片名` or `严禁搬运真实片名`; append `CANONICAL_TITLE_RULE` if absent.

- [ ] **Step 1: Write the failing test**

```python
from novel_agent.annals.research import NullResearchPort, WebResearchPort
from novel_agent.annals.skeleton import (
    CANONICAL_TITLE_RULE,
    build_skeleton,
    confirm_errors,
    fill_skeleton,
    patch_kernel_title_rule,
)
from novel_agent.domain.schemas.annals import SourceRef


def test_not_applicable_skeleton_is_confirmable() -> None:
    sk = build_skeleton(kernel_texts=["说书人"], time_locations=["临安城"], volume_texts=[], locked_drafts=[])
    assert sk.cover.applicable is False
    assert sk.year_cards == []
    assert confirm_errors(sk) == []


def test_null_port_leaves_plot_hit_unconfirmable() -> None:
    sk = build_skeleton(
        kernel_texts=["2005穿回去"],
        time_locations=["2005秋 北影厂", "2006夏"],
        volume_texts=[],
        locked_drafts=[("v1c012", "柏林一种关注放映前夜")],
    )
    assert sk.cover.applicable is True
    assert sk.cover.span_start == 2005
    assert {card.year for card in sk.year_cards} == {2005, 2006}
    thick = {card.year for card in sk.year_cards if card.density == "thick"}
    assert thick == {2005, 2006}
    assert any("柏林一种关注" in d.issue for d in sk.debts)
    filled = fill_skeleton(sk, NullResearchPort())
    errors = confirm_errors(filled)
    assert errors  # plot-hit unsourced
    assert all(card.awards == [] for card in filled.year_cards)


def test_sourced_fill_confirms_and_human_widen() -> None:
    class FakePort:
        def lookup(self, query: str) -> list[SourceRef]:
            return [SourceRef(url="https://example.invalid/x", excerpt=query, accessed="2026-08-18")]

    sk = build_skeleton(
        kernel_texts=["2005"],
        time_locations=["2005秋"],
        volume_texts=[],
        locked_drafts=[],
        span_start=2005,
        span_end=2025,
    )
    assert sk.cover.span_end == 2025
    thin = [card for card in sk.year_cards if card.density == "thin"]
    assert 2025 in {card.year for card in thin}
    filled = fill_skeleton(sk, FakePort())
    assert confirm_errors(filled) == []


def test_no_auto_widen_to_2025() -> None:
    sk = build_skeleton(kernel_texts=["2005"], time_locations=["2005秋", "2008初"], volume_texts=[], locked_drafts=[])
    assert sk.cover.span_end == 2008


def test_patch_title_rule() -> None:
    out = patch_kernel_title_rule(["禁无代价全能", "严禁搬运真实片名", "真实片名不要写"])
    assert "严禁搬运真实片名" not in out
    assert all("真实片名" not in item or item == CANONICAL_TITLE_RULE for item in out)
    assert CANONICAL_TITLE_RULE in out
    assert "禁无代价全能" in out


def test_web_port_empty_http_returns_empty(monkeypatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    assert WebResearchPort(client).lookup("2006 金鸡 影后") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_research.py -v`

Expected: FAIL import

- [ ] **Step 3: Write minimal implementation**

`src/novel_agent/annals/research.py`:

```python
from __future__ import annotations

from typing import Protocol

import httpx

from novel_agent.domain.schemas.annals import SourceRef


class ResearchPort(Protocol):
    def lookup(self, query: str) -> list[SourceRef]: ...


class NullResearchPort:
    def lookup(self, query: str) -> list[SourceRef]:
        return []


class WebResearchPort:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)

    def lookup(self, query: str) -> list[SourceRef]:
        q = (query or "").strip()
        if not q:
            return []
        try:
            if q.startswith("http://") or q.startswith("https://"):
                response = self._client.get(q)
                response.raise_for_status()
                excerpt = (response.text or "")[:240]
                if not excerpt:
                    return []
                return [SourceRef(url=q, excerpt=excerpt)]
            response = self._client.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": q, "limit": 1, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        if not isinstance(payload, list) or len(payload) < 4:
            return []
        titles, snippets, urls = payload[1], payload[2], payload[3]
        if not titles or not urls:
            return []
        excerpt = snippets[0] if snippets else ""
        if not urls[0]:
            return []
        return [SourceRef(url=str(urls[0]), excerpt=str(excerpt or titles[0])[:240])]
```

`src/novel_agent/annals/skeleton.py` (core of this task; `ensure_annals_cover` / `extend_annals_for_outlines` land in Tasks 6 and 8 in this same file):

```python
from __future__ import annotations

from pydantic import Field

from novel_agent.annals.span import derive_story_span, plot_hit_years, widen_span
from novel_agent.annals.taxonomy import FESTIVAL_TAXONOMY, METHOD_LIBRARY_EXAMPLES
from novel_agent.domain.schemas.annals import (
    AnnalsCover,
    AnnalsSlice,  # noqa: F401
    MethodLibraryCard,
    SourceRef,
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
    taxonomy: list = Field(default_factory=list)
    methods: list[MethodLibraryCard] = Field(default_factory=list)
    debts: list[TimelineAlignDebt] = Field(default_factory=list)


def patch_kernel_title_rule(do_not_write: list[str]) -> list[str]:
    out = [item for item in do_not_write if "真实片名" not in item and "严禁搬运真实片名" not in item]
    if CANONICAL_TITLE_RULE not in out:
        out.append(CANONICAL_TITLE_RULE)
    return out


def _debts(locked_drafts: list[tuple[str, str]]) -> list[TimelineAlignDebt]:
    found: list[TimelineAlignDebt] = []
    for key, text in locked_drafts:
        blob = text or ""
        if "柏林一种关注" in blob:
            found.append(TimelineAlignDebt(chapter_key=key, issue="v uses 柏林一种关注"))
        if "戛纳" in blob and any(token in blob for token in _EARLY):
            found.append(TimelineAlignDebt(chapter_key=key, issue="Cannes placed in 年初"))
        if "金鸡" in blob and "2006" in blob:
            found.append(TimelineAlignDebt(chapter_key=key, issue="2006 金鸡 may be a biennial gap"))
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


def fill_skeleton(skeleton: AnnalsSkeleton, port) -> AnnalsSkeleton:
    years: list[YearCard] = []
    for card in skeleton.year_cards:
        awards = [row for row in card.awards if row.sources]
        sources = list(card.sources) or list(port.lookup(f"{card.year} film industry"))
        years.append(card.model_copy(update={"awards": awards, "sources": sources}))
    methods: list[MethodLibraryCard] = []
    for card in skeleton.methods:
        sources = list(card.sources) or list(port.lookup(card.film_title))
        speak = card.speak_as_existing_from_year or card.release_year
        methods.append(card.model_copy(update={"sources": sources, "speak_as_existing_from_year": speak}))
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
```

Do not add award winners in `build_skeleton` or `fill_skeleton`.

- [ ] **Step 4: Run tests**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_research.py tests/unit/test_annals_span.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/annals/research.py src/novel_agent/annals/skeleton.py src/novel_agent/annals/__init__.py tests/unit/test_annals_research.py
git commit -m "feat: 年代志 skeleton, sourced fill, title-rule patch"
```

---

### Task 6: R6 bible round and `ensure_annals_cover`

**Files:**
- Modify: `src/novel_agent/planning/rounds.py` (`ROUND_KINDS` line 48, `confirm_round` bound line 157, `_generate_artifact`, `_persist_artifact`)
- Modify: `src/novel_agent/domain/repos/bible.py` `round_complete` (line 191)
- Modify: `src/novel_agent/planning/conversation.py` (after `_ensure_r5`)
- Modify: `src/novel_agent/planning/chain.py` (end of `run_planning_chain`)
- Modify: `tests/contract/test_story_bible.py` (R6 assertions)
- Test: `tests/unit/test_annals_repo.py` (append round_complete cases) and/or `tests/contract/test_story_bible.py`

**Interfaces:**
- Consumes: `build_skeleton`, `fill_skeleton`, `confirm_errors`, `patch_kernel_title_rule`, `AnnalsRepo`, `NullResearchPort` in tests / `WebResearchPort` in generate when deps have http
- Produces:
  - `ROUND_KINDS = ("R0", "R1", "R2", "R3", "R4", "R5", "R6")`
  - `ROUND_PROMPTS[6] = "确认写入年代志(故事年跨度的年卡 + 出处)?"`
  - `confirm_round` allows `0–6`
  - `ensure_annals_cover(planning, annals, project_id, *, research: ResearchPort | None = None) -> AnnalsCover` — if `r6_complete`, return cover; if span is None, persist confirmed `applicable=False` cover; if span exists and cover missing/incomplete, **do not** auto-confirm (caller must go through R6). Exception: `ensure_annals_cover(..., auto_not_applicable_only=True)` used by `run_planning_chain` / chapter-loop guard: only auto-writes the not_applicable cover; if years exist and incomplete, returns cover or None without inventing sources.
  - Concept Judge does **not** run on R6.
  - R6 generate must not regenerate outlines.
  - `bible.round_complete` adds `"R6"` iff `AnnalsRepo.r6_complete(project_id)`.

R6 generate artifact JSON: `AnnalsSkeleton.model_dump(mode="json")` after `fill_skeleton`. Use `NullResearchPort` unless `deps` exposes a research port (add optional `deps.research: ResearchPort | None = None` only if `AgentDeps` already has an extension point; **do not** change AgentDeps unless a field already exists). Default generate uses `NullResearchPort`. Human pastes sources into pending artifact before confirm.

R6 persist: if `confirm_errors(skeleton)` non-empty → `PlanningError`. Else upsert cover/years/taxonomy/methods/debts as `confirmed`. If applicable, `planning.save_kernel` replacement: load approved kernel, `do_not_write=patch_kernel_title_rule(...)`, save new version and approve it (same pattern as kernel confirm). If not applicable, do not touch kernel.

`_ensure_r6` in conversation: if `AnnalsRepo.r6_complete`, skip. Else build skeleton from live kernel/outlines/volumes/locked drafts. If not applicable, persist immediately without `gates.confirm`. If applicable, `gates.confirm(ROUND_PROMPTS[6])` then persist only when `confirm_errors` empty; else `PlanningError` listing missing sources (do not LLM-fill).

Locked drafts for debt scan: `ProductionRepo.latest_draft` for `CANON_LOCKED` chapters if production repo is in scope; conversation/rounds may pass `locked_drafts=[]` if production is not wired. Prefer wiring: `planning.list_chapters` + production latest non-voided text when available. If production is awkward from rounds.py, scan empty in R6 generate and let Task 8 volume path record debts later. **This task must still persist taxonomy seeds.** Debt scan of locked text is required by spec: from rounds.py, import ProductionRepo if that creates a cycle, put `list_locked_draft_texts(session, project_id) -> list[tuple[str,str]]` in `annals/skeleton.py` using ProductionRepo + PlanningRepo.

- [ ] **Step 1: Write the failing tests**

In `tests/contract/test_story_bible.py`, after creating a chapter the exact set is still `{R0…R5}` (no cover yet). Add:

```python
def test_round_complete_adds_r6_on_not_applicable_cover(engine) -> None:
    from novel_agent.domain.repos import AnnalsRepo
    from novel_agent.domain.schemas.annals import AnnalsCover

    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        bible = BibleRepo(session)
        pid = planning.create_project("说书人传奇", boundaries=["禁无代价全能"]).id
        bible.save_brief(pid, StoryBrief(spark="说书人发现故事会成真", do_not_write=["禁无代价全能"]))
        planning.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(pid, 1)
        bible.save_structure_map(pid, StructureMap.model_validate(_structure_map()))
        planning.upsert_character(pid, CharacterCard.model_validate(CHARACTER))
        bible.replace_conflicts(pid, [Conflict.model_validate(_conflict())])
        bible.replace_payoff_beats(pid, [PayoffBeat.model_validate(_payoff())])
        planning.create_chapter(pid, ChapterOutline.model_validate(OUTLINE), order_index=1)
        assert bible.round_complete(pid) == {"R0", "R1", "R2", "R3", "R4", "R5"}
        assert "R6" not in bible.round_complete(pid)
        AnnalsRepo(session).upsert_cover(pid, AnnalsCover(applicable=False), status="confirmed")
        assert bible.round_complete(pid) == {"R0", "R1", "R2", "R3", "R4", "R5", "R6"}
```

Do not change `test_bible_repo_crud_and_round_complete`'s final exact set (still no R6).

Add `tests/contract/test_annals_round.py`:

```python
from test_schemas import KERNEL, OUTLINE

from novel_agent.annals.skeleton import ensure_annals_cover
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import AnnalsRepo, PlanningRepo
from novel_agent.domain.schemas import ChapterOutline, StoryKernel


def test_ensure_cover_auto_not_applicable(tmp_path) -> None:
    engine = build_engine(tmp_path / "r6.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("说书人传奇").id
        planning.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(pid, 1)
        planning.create_chapter(pid, ChapterOutline.model_validate(OUTLINE), order_index=1)
        cover = ensure_annals_cover(planning, AnnalsRepo(session), pid, auto_not_applicable_only=True)
        assert cover is not None
        assert cover.applicable is False
        assert AnnalsRepo(session).r6_complete(pid) is True


def test_ensure_cover_does_not_invent_era_years(tmp_path) -> None:
    engine = build_engine(tmp_path / "r6era.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("导演").id
        kernel = dict(KERNEL)
        kernel["logline"] = KERNEL["logline"] + " 2005年"
        planning.save_kernel(pid, StoryKernel.model_validate(kernel))
        planning.approve_kernel(pid, 1)
        outline = dict(OUTLINE)
        outline["time_location"] = "2005秋,北影厂"
        planning.create_chapter(pid, ChapterOutline.model_validate(outline), order_index=1)
        cover = ensure_annals_cover(planning, AnnalsRepo(session), pid, auto_not_applicable_only=True)
        assert cover is None
        assert AnnalsRepo(session).r6_complete(pid) is False
```

Prefer putting `ensure_annals_cover` in `src/novel_agent/annals/skeleton.py` so rounds/chain/loop all import one function:

```python
def ensure_annals_cover(
    planning: PlanningRepo,
    annals: AnnalsRepo,
    project_id: int,
    *,
    research: ResearchPort | None = None,
    auto_not_applicable_only: bool = True,
) -> AnnalsCover | None:
```

When `auto_not_applicable_only=True` and span is None: persist confirmed not_applicable, return it. When span exists: return existing cover or None, never invent.

When `auto_not_applicable_only=False` (R6 persist path): persist the provided skeleton (not this helper).

Also test `confirm_round` bound: `pytest.raises(PlanningError, match="0–6")` if you pass 7. Update the error string in `rounds.py` from `0–5` to `0–6`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/contract/test_story_bible.py::test_round_complete_adds_r6_on_not_applicable_cover tests/contract/test_story_bible.py::test_bible_repo_crud_and_round_complete -v`

Expected: FAIL (`R6` never in `round_complete`)

- [ ] **Step 3: Implement**

`bible.round_complete`:

```python
        from novel_agent.domain.repos.annals import AnnalsRepo

        if AnnalsRepo(self.s).r6_complete(project_id):
            done.add("R6")
        return done
```

Keep R0–R5 logic unchanged.

Append to `src/novel_agent/annals/skeleton.py`:

```python
def _span_texts(planning, project_id: int) -> tuple[list[str], list[str], list[str]]:
    kernel = planning.get_approved_kernel(project_id)
    kernel_texts = []
    if kernel is not None:
        kernel_texts = [kernel.premise, kernel.logline, kernel.reader_promise, *kernel.do_not_write]
    outlines = [planning.get_outline(project_id, ch.chapter_key) for ch in planning.list_chapters(project_id)]
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
            patched = kernel.model_copy(update={"do_not_write": patch_kernel_title_rule(list(kernel.do_not_write))})
            rec = planning.save_kernel(project_id, patched)
            planning.approve_kernel(project_id, rec.version)


def ensure_annals_cover(planning, annals, project_id: int, *, research=None, auto_not_applicable_only: bool = True):
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
```

Import `NullResearchPort` at top of `skeleton.py`.

`rounds.py`: `ROUND_KINDS` include R6; `confirm_round` bound `0–6` (`PlanningError("轮次必须是 0–6")`); `_generate_artifact` for 6:

```python
    if round_index == 6:
        from novel_agent.annals.research import NullResearchPort
        from novel_agent.annals.skeleton import build_skeleton, fill_skeleton, _span_texts
        kernel_texts, time_locations, volume_texts = _span_texts(planning, project_id)
        skeleton = fill_skeleton(
            build_skeleton(
                kernel_texts=kernel_texts,
                time_locations=time_locations,
                volume_texts=volume_texts,
                locked_drafts=[],
            ),
            NullResearchPort(),
        )
        return skeleton.model_dump(mode="json")
```

`_persist_artifact` for 6: `persist_annals_skeleton(..., AnnalsSkeleton.model_validate(artifact))`. Pending artifact may contain human-pasted `sources` before confirm.


`conversation.py`: call `_ensure_r6` after R5, before `BibleResult`. Update docstring `R0→R5` to `R0→R6`.

`run_planning_chain`: after it creates chapters, `ensure_annals_cover(..., auto_not_applicable_only=True)` so 临安 `_planned()` fixtures get R6 not_applicable and existing chapter-loop tests keep writing.

- [ ] **Step 4: Run tests**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/contract/test_story_bible.py tests/workflow/test_chapter_loop.py tests/unit/test_annals_repo.py tests/unit/test_annals_research.py -v --maxfail=5`

Expected: PASS. Existing `_planned` chapter loops still lock because span is 临安 (no years) and `ensure_annals_cover` auto-confirmed not_applicable.

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/planning/rounds.py src/novel_agent/planning/conversation.py src/novel_agent/planning/chain.py src/novel_agent/domain/repos/bible.py src/novel_agent/annals/skeleton.py tests/contract/test_story_bible.py tests/contract/test_annals_round.py
git commit -m "feat: bible R6 年代志 round and not_applicable auto-cover"
```

---

### Task 7: Inject `AnnalsSlice` and thread gates from context

**Files:**
- Create: `src/novel_agent/annals/slice.py`
- Modify: `src/novel_agent/context/context_builder.py`
- Modify: `src/novel_agent/production/loop.py` (`LockGates(...)` around line 825; start of `run_chapter_loop`)
- Test: `tests/unit/test_annals_context.py`

**Interfaces:**
- Consumes: `AnnalsRepo`, `parse_story_year`, `METHOD_LIBRARY_EXAMPLES` fallback only from repo methods, `FORBIDDEN_SECTION_PHRASES`
- Produces:
  - `annals_slice_for_chapter(annals, outline) -> AnnalsSlice`
  - `title_fence(methods, story_year) -> list[str]` titles where `speak_as_existing_from_year or release_year > story_year`
  - `ContextBuilder.build` sets `package.annals`. If cover missing: call `ensure_annals_cover(..., auto_not_applicable_only=True)`; if still missing or applicable and year missing/unconfirmed → `ValueError("无法构建上下文: 年代志年卡缺失或未确认")` / `ValueError("无法构建上下文: 章纲缺少故事年")`
  - `_trim` does not drop `annals` (do not add it to the trim field list). `required_size` therefore keeps it.
  - `run_chapter_loop` before n2: if applicable cover and chapter needs annals → `ChapterLoopError("NEEDS_ANNALS")`
  - n6 `LockGates` adds `annals_year=package.annals.story_year`, `forbidden_titles=list(package.annals.title_fence)`, `forbidden_section_phrases=list(FORBIDDEN_SECTION_PHRASES) if package.annals.applicable else None`

`annals_slice_for_chapter`:
- no cover or not applicable → `AnnalsSlice(applicable=False)`
- applicable: `year = parse_story_year(outline.time_location)`; None → raise `ValueError`
- load confirmed year card; missing/pending → raise `ValueError`
- methods from repo; `title_fence` as above
- `festival_notes` from taxonomy `typical_calendar` + section names (short strings)
- `timeline_debts` issues whose `chapter_key == outline.chapter_key`

- [ ] **Step 1: Write the failing test**

```python
from novel_agent.annals.slice import annals_slice_for_chapter, title_fence
from novel_agent.annals.taxonomy import METHOD_LIBRARY_EXAMPLES
from novel_agent.domain.schemas.annals import MethodLibraryCard


def test_title_fence_2005_includes_buried_not_1997() -> None:
    methods = list(METHOD_LIBRARY_EXAMPLES) + [
        MethodLibraryCard(film_title="黑洞", release_year=1997, speak_as_existing_from_year=1997, craft="x"),
    ]
    fence = title_fence(methods, 2005)
    assert "活埋" in fence
    assert "小偷家族" in fence
    assert "黑洞" not in fence


def test_builder_not_applicable_allows_linan(tmp_path) -> None:
    from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

    from novel_agent.annals.skeleton import ensure_annals_cover
    from novel_agent.context import ContextBuilder
    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.repos import AnnalsRepo, CanonRepo, PlanningRepo
    from novel_agent.domain.schemas import ChapterOutline, CharacterCard, PlotUnitCard, SceneCard, StoryKernel

    engine = build_engine(tmp_path / "ctx.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("上下文测试", boundaries=["项目边界"])
        planning.save_kernel(project.id, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(project.id, 1)
        planning.upsert_character(project.id, CharacterCard.model_validate(CHARACTER))
        planning.save_volume(project.id, "v1", {"summary": "第一卷摘要"})
        planning.save_unit(project.id, "v1", PlotUnitCard.model_validate(UNIT))
        planning.create_chapter(project.id, ChapterOutline.model_validate(OUTLINE), order_index=1)
        planning.save_scene_cards(project.id, "v1c001", [SceneCard.model_validate(SCENE)])
        ensure_annals_cover(planning, AnnalsRepo(session), project.id, auto_not_applicable_only=True)
        package = ContextBuilder(planning, CanonRepo(session)).build(
            project.id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要"
        )
        assert package.annals.applicable is False


def test_builder_applicable_missing_year_card_raises(tmp_path) -> None:
    from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

    from novel_agent.annals.taxonomy import METHOD_LIBRARY_EXAMPLES, seed_source
    from novel_agent.context import ContextBuilder
    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.repos import AnnalsRepo, CanonRepo, PlanningRepo
    from novel_agent.domain.schemas import ChapterOutline, CharacterCard, PlotUnitCard, SceneCard, StoryKernel
    from novel_agent.domain.schemas.annals import AnnalsCover, YearCard

    engine = build_engine(tmp_path / "ctx2.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("导演", boundaries=["项目边界"])
        kernel = dict(KERNEL)
        kernel["logline"] = KERNEL["logline"] + " 2005年"
        planning.save_kernel(project.id, StoryKernel.model_validate(kernel))
        planning.approve_kernel(project.id, 1)
        planning.upsert_character(project.id, CharacterCard.model_validate(CHARACTER))
        planning.save_volume(project.id, "v1", {"summary": "第一卷摘要"})
        planning.save_unit(project.id, "v1", PlotUnitCard.model_validate(UNIT))
        outline = dict(OUTLINE)
        outline["time_location"] = "2005秋,北影厂"
        planning.create_chapter(project.id, ChapterOutline.model_validate(outline), order_index=1)
        planning.save_scene_cards(project.id, "v1c001", [SceneCard.model_validate(SCENE)])
        annals = AnnalsRepo(session)
        annals.upsert_cover(
            project.id,
            AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
            status="confirmed",
        )
        builder = ContextBuilder(planning, CanonRepo(session))
        try:
            builder.build(project.id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "年代志" in str(exc) or "故事年" in str(exc)
        annals.upsert_year(
            project.id,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("x")]),
            status="confirmed",
        )
        annals.replace_methods(project.id, list(METHOD_LIBRARY_EXAMPLES), status="confirmed")
        package = builder.build(
            project.id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            retrieval_facts=["a" * 40, "b" * 40],
        )
        assert package.annals.applicable is True
        assert package.annals.story_year == 2005
        assert "活埋" in package.annals.title_fence
        fence = list(package.annals.title_fence)
        required = builder.required_size(package)
        trimmed = builder.build(
            project.id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            retrieval_facts=["a" * 40, "b" * 40],
            max_chars=required + 10,
        )
        assert trimmed.annals.title_fence == fence
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_context.py -v`

Expected: FAIL

- [ ] **Step 3: Implement**

`src/novel_agent/annals/slice.py`:

```python
from novel_agent.annals.span import parse_story_year
from novel_agent.domain.schemas.annals import AnnalsSlice, MethodLibraryCard
from novel_agent.domain.schemas.outline import ChapterOutline


def title_fence(methods: list[MethodLibraryCard], story_year: int) -> list[str]:
    fenced: list[str] = []
    for card in methods:
        year = card.speak_as_existing_from_year or card.release_year
        if year > story_year and card.film_title not in fenced:
            fenced.append(card.film_title)
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
    notes = [f"{card.festival_id}: {card.typical_calendar}" for card in annals.list_taxonomy(project_id)]
    debts = [item.issue for item in annals.list_debts(project_id) if item.chapter_key == outline.chapter_key]
    return AnnalsSlice(
        applicable=True,
        story_year=year,
        year_card=year_card,
        festival_notes=notes,
        method_library=methods,
        title_fence=title_fence(methods, year),
        timeline_debts=debts,
    )
```

In `ContextBuilder.build`, after constructing `package` and before `_trim`:

```python
        from novel_agent.annals.skeleton import ensure_annals_cover
        from novel_agent.annals.slice import annals_slice_for_chapter
        from novel_agent.domain.repos.annals import AnnalsRepo

        annals = AnnalsRepo(self._planning.s)
        ensure_annals_cover(self._planning, annals, project_id, auto_not_applicable_only=True)
        package = package.model_copy(update={"annals": annals_slice_for_chapter(annals, project_id, outline)})
```

If `annals_slice_for_chapter` raises, let it propagate (same family as missing kernel).

n6 `LockGates`:

```python
        from novel_agent.annals.taxonomy import FORBIDDEN_SECTION_PHRASES

        gates = LockGates(
            required_names=names,
            pov=package.outline.pov,
            chapter_index=chapter_index_from_key(chapter_key),
            card_names=names,
            schedule=_lock_schedule(PlanningRepo(ops.s), project_id),
            reveal_forbidden=list(package.outline.reveal_forbidden),
            annals_year=package.annals.story_year,
            forbidden_titles=list(package.annals.title_fence),
            forbidden_section_phrases=list(FORBIDDEN_SECTION_PHRASES) if package.annals.applicable else None,
        )
```

At the start of `run_chapter_loop` after loading `chapter`, if status is not CANON_LOCKED/EXPORTED:

```python
        from novel_agent.annals.skeleton import chapter_needs_annals, ensure_annals_cover
        from novel_agent.domain.repos.annals import AnnalsRepo

        annals = AnnalsRepo(session)
        ensure_annals_cover(planning, annals, project_id, auto_not_applicable_only=True)
        if chapter_needs_annals(planning, annals, project_id, chapter_key):
            raise ChapterLoopError("NEEDS_ANNALS")
```

- [ ] **Step 4: Run tests**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_annals_context.py tests/unit/test_factory_gates.py tests/workflow/test_chapter_loop.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/annals/slice.py src/novel_agent/context/context_builder.py src/novel_agent/production/loop.py tests/unit/test_annals_context.py
git commit -m "feat: inject AnnalsSlice and thread title fences into lock gates"
```

---

### Task 8: `volume_run` NEEDS_ANNALS, `plan_more` span extend, workflow proof

**Files:**
- Modify: `src/novel_agent/production/volume_run.py` (`VolumeStopReason`, `run_volume` before `run_chapter_loop`)
- Modify: `src/novel_agent/planning/volume.py` (end of successful `plan_more`)
- Test: `tests/workflow/test_annals_volume.py`

**Interfaces:**
- Consumes: `AnnalsRepo.r6_complete`, `ensure_annals_cover`, `build_skeleton`, `parse_story_year`
- Produces:
  - `VolumeStopReason.NEEDS_ANNALS = "NEEDS_ANNALS"`
  - Before writing a chapter: if applicable and that chapter's year card is missing/unconfirmed → stop `NEEDS_ANNALS` **without** calling `run_chapter_loop`
  - After `plan_more` inserts outlines whose years sit outside cover span: upsert new year cards with `status="pending"`, empty sources; extend `cover.span_end`/`span_start` via `widen_span`; keep cover `confirmed` only if `r6_complete` still holds (new plot-hit pending ⇒ `r6_complete` False). Do not invent climate/winners.
  - No public-repo dump of 2005–2025 filled cards.

- [ ] **Step 1: Write the failing tests**

`tests/workflow/test_annals_volume.py`:

```python
from novel_agent.domain.schemas import ChapterStatus
from novel_agent.production.volume_run import VolumeStopReason, run_volume


async def test_era_project_without_year_card_stops_needs_annals(tmp_path) -> None:
    """R5 outlines with years cannot volume_run until R6 plot-hit cards are confirmed."""
    session, deps, mock, project_id = await _planned_era(tmp_path)
    settings = Settings(_env_file=None)
    result = await run_volume(
        session, deps, project_id, budget_usd=50.0, yes=True, settings=settings, max_chapters=1
    )
    assert result.stop_reason == VolumeStopReason.NEEDS_ANNALS
    assert result.chapters_done == 0


async def test_not_applicable_project_still_volume_runs(tmp_path) -> None:
    session, deps, mock, project_id = await _planned(tmp_path)  # 临安, from test_chapter_loop
    settings = Settings(_env_file=None)
    result = await run_volume(
        session, deps, project_id, budget_usd=50.0, yes=True, settings=settings, max_chapters=1
    )
    assert result.stop_reason != VolumeStopReason.NEEDS_ANNALS


async def test_confirmed_2005_slice_fences_buried(tmp_path) -> None:
    session, deps, mock, project_id = await _planned_era(tmp_path)
    _confirm_2005_cover(session, project_id)
    package = ContextBuilder(PlanningRepo(session), CanonRepo(session)).build(
        project_id, "v1c001", task_brief="t", volume_summary="v"
    )
    assert package.annals.applicable is True
    assert package.annals.story_year == 2005
    assert "活埋" in package.annals.title_fence
```

Helpers in the same file (copy `_planned` from `tests/workflow/test_chapter_loop.py`):

```python
from tests.workflow.test_chapter_loop import _planned  # if package layout forbids this, copy the function body verbatim into this file

from novel_agent.annals.skeleton import extend_annals_for_outlines
from novel_agent.annals.taxonomy import METHOD_LIBRARY_EXAMPLES, seed_source
from novel_agent.config import Settings
from novel_agent.context import ContextBuilder
from novel_agent.domain.repos import AnnalsRepo, CanonRepo, PlanningRepo
from novel_agent.domain.schemas.annals import AnnalsCover, YearCard


async def _planned_era(tmp_path):
    session, deps, mock, project_id = await _planned(tmp_path)
    planning = PlanningRepo(session)
    chapter = planning.get_chapter(project_id, "v1c001")
    outline = dict(chapter.outline)
    outline["time_location"] = "2005秋,北影厂"
    chapter.outline = outline
    session.add(chapter)
    kernel = planning.get_approved_kernel(project_id)
    assert kernel is not None
    patched = kernel.model_copy(update={"logline": kernel.logline + " 2005年"})
    rec = planning.save_kernel(project_id, patched)
    planning.approve_kernel(project_id, rec.version)
    annals = AnnalsRepo(session)
    existing = annals.get_cover(project_id)
    if existing is not None:
        cover, _status = existing
        if not cover.applicable:
            annals.upsert_cover(
                project_id,
                AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
                status="pending",
            )
    session.commit()
    return session, deps, mock, project_id


def _confirm_2005_cover(session, project_id: int) -> None:
    annals = AnnalsRepo(session)
    annals.upsert_cover(
        project_id,
        AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
        status="confirmed",
    )
    annals.upsert_year(
        project_id,
        YearCard(year=2005, density="thick", climate="厂里还在用胶片", sources=[seed_source("2005")]),
        status="confirmed",
    )
    annals.replace_methods(project_id, list(METHOD_LIBRARY_EXAMPLES), status="confirmed")
    session.commit()


def test_plan_more_new_year_is_pending(tmp_path) -> None:
    from test_schemas import KERNEL, OUTLINE

    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.schemas import ChapterOutline, StoryKernel

    engine = build_engine(tmp_path / "extend.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("导演").id
        kernel = dict(KERNEL)
        kernel["logline"] = KERNEL["logline"] + " 2005年"
        planning.save_kernel(pid, StoryKernel.model_validate(kernel))
        planning.approve_kernel(pid, 1)
        first = dict(OUTLINE)
        first["time_location"] = "2005秋"
        planning.create_chapter(pid, ChapterOutline.model_validate(first), order_index=1)
        later = dict(OUTLINE)
        later["chapter_key"] = "v1c002"
        later["time_location"] = "2009春"
        planning.create_chapter(pid, ChapterOutline.model_validate(later), order_index=2)
        annals = AnnalsRepo(session)
        annals.upsert_cover(
            pid,
            AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
            status="confirmed",
        )
        annals.upsert_year(
            pid,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("2005")]),
            status="confirmed",
        )
        extend_annals_for_outlines(planning, annals, pid)
        got = annals.get_year(pid, 2009)
        assert got is not None
        card, status = got
        assert card.year == 2009
        assert status == "pending"
        assert annals.r6_complete(pid) is False
```

If `from tests.workflow.test_chapter_loop import _planned` fails on pytest path, copy `_planned` / `_engine` verbatim from `tests/workflow/test_chapter_loop.py` into `tests/workflow/test_annals_volume.py` (do not import a private helper across test modules if collection forbids it).

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/workflow/test_annals_volume.py -v`

Expected: FAIL (`VolumeStopReason` has no `NEEDS_ANNALS` or era project writes)

- [ ] **Step 3: Implement**

Append to `src/novel_agent/annals/skeleton.py`:

```python
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
            annals.upsert_year(project_id, YearCard(year=year, density=density, climate=""), status="pending")
    annals.upsert_cover(
        project_id,
        cover.model_copy(update={"span_start": start, "span_end": end, "plot_hit_years": hits}),
        status=status,
    )


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
```

Call `extend_annals_for_outlines` at the end of `plan_more` after new chapters are saved.

`VolumeStopReason`:

```python
    NEEDS_ANNALS = "NEEDS_ANNALS"
```

In `run_volume`, after `_next_unfinished` and before `run_chapter_loop`:

```python
            from novel_agent.domain.repos.annals import AnnalsRepo
            from novel_agent.annals.skeleton import chapter_needs_annals

            ensure_annals_cover(planning, AnnalsRepo(session), project_id, auto_not_applicable_only=True)
            if chapter_needs_annals(planning, AnnalsRepo(session), project_id, nxt.chapter_key):
                current = nxt.chapter_key
                stop = VolumeStopReason.NEEDS_ANNALS
                break
```


- [ ] **Step 4: Run tests**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/workflow/test_annals_volume.py tests/workflow/test_chapter_loop.py tests/unit/test_annals_span.py tests/unit/test_annals_research.py tests/unit/test_annals_repo.py tests/unit/test_annals_context.py tests/unit/test_factory_gates.py tests/contract/test_story_bible.py -q`

Expected: PASS

Then: `uv run ruff check src/novel_agent/annals src/novel_agent/domain/schemas/annals.py src/novel_agent/domain/repos/annals.py src/novel_agent/production/factory.py src/novel_agent/production/loop.py src/novel_agent/production/volume_run.py src/novel_agent/context/context_builder.py src/novel_agent/planning/rounds.py`

Expected: clean

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/production/volume_run.py src/novel_agent/planning/volume.py src/novel_agent/annals/skeleton.py tests/workflow/test_annals_volume.py
git commit -m "feat: block volume_run on unconfirmed 年代志 years"
```

---

## Self-review (plan vs spec)

| Spec | Task |
|---|---|
| 5.1 R6 after R5, not_applicable vs applicable, no outline regen, no Concept Judge on R6 | 6 |
| 5.2 span parse, no default 2005, human widen, plot-hit vs thin, missing year fail-closed when applicable | 1, 5, 7 |
| 5.3 card kinds, thick/thin, celebrity names not on cards (awards = film+category; methods have no 华语明星法律名 in seed) | 2, 5 |
| 5.4 real titles year-gated; kernel patch on applicable confirm only | 5, 6 |
| 5.5 ResearchPort, NullResearchPort fail-closed, no LLM winners, confirm errors | 5 |
| 5.6 `annals_card` + `AnnalsRepo` + unique (project, kind, card_key); kind `cover` is the spec's confirmed cover | 4 |
| 5.7 AnnalsSlice inject, required, not trimmed | 2, 7 |
| 5.8 LockGates titles/sections/戛纳年初; volume_run NEEDS_ANNALS; skip locked | 3, 7, 8 |
| 5.9 factory_seed taxonomy + method examples in tests | 2 |
| 5.10 listed test files | 1, 3, 5, 7, 8 |
| 5.11 out of scope (prompts, locked vol.1 dump, outline schema, PR #24) | Global Constraints |
| plan_more new year pending | 8 |
| Private canon fill | out of this plan (spec §2 item 2) |

No TBD/TODO left in tasks. `kind=cover` is the persistence of spec 5.1 “confirmed cover”; year/taxonomy/method/debt keys match spec 5.6.

