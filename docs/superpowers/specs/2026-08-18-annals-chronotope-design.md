# 年代志 (Annals / Chronotope) — Design Spec

- Date: 2026-08-18
- Status: draft (from locked 《穿回去当导演》 vol.1 festival/title anachronism + missing research layer)
- Repo: `bingooyong/ai-open-writing`
- Upstream: `main` `4daecae` (PR #35 unscheduled-gate phrase match)
- Evidence: factory is R0–R5 then write; `ChapterContextPackage` has no year card; kernel `do_not_write` still says 严禁搬运真实片名; locked v1c012 uses 柏林一种关注 (Cannes section, not Berlin); v1c017–020 place Cannes in 「2008年初」 (real Cannes is mid-May)

## 1. North star

An entertainment-industry novel **cannot invent era, festivals, or titles**. Before any new chapter is written, the factory holds a confirmed **年代志**: one year card per year in the story span, sourced, injected into the chapter context, and used as a lock gate.

Theory name: Bakhtin **时空体 (chronotope)**. Factory artifact name: **年代志**. Do not call it 查阅卡 (that was never a factory object).

This spec is **bible round + context + lock-gate**. It does not rewrite Writer, Judge, or retrieval prompts. Ports stay `8765` / `18765`. No Redis. No second runner. Leave draft PR #24 alone. Do not reopen outline-sanitizer or lock-gates-from-audit work except to *extend* `LockGates` with annals fields. Do not rewrite locked vol.1 prose.

Filled 《穿回去当导演》 year cards are **novel IP**. They live in the private canon DB (`bingooyong/yujin-huisheng-canon`), never as a data dump on this public repo. This public repo ships schema, round, research port, lint, tests, and structural festival seeds.

## 2. Why this is a sub-project

R0 brief → R1 kernel → R2 structure → R3 characters → R4 conflicts/payoffs → R5 volume+outlines → `ChapterContextPackage` → write. There is no era/festival/year layer. `volume_run` does not check that research exists. Writer therefore invents climate and festival taxonomy, and the current kernel forbids real film titles instead of year-gating them.

Independent pieces, build order:

1. **This spec — 年代志 R6** (span, year cards, research port, confirm, context inject, lock gates, kernel title-rule patch)
2. Fill 《穿回去当导演》 year cards in the private canon — **out of this spec** (data, after the factory lands)
3. Optional locked-vol.1 festival/calendar rewrites — **out of this spec** (user must ask; this spec only records timeline-align debts)

## 3. Approaches considered

### A. R6 年代志 + sourced cards + inject + lock-gate (chosen)

Add bible round R6 after R5. Derive the inclusive year span from kernel + outlines (not a hardcoded 2005). Emit one `YearCard` per year (thick on plot-hit years, thin on intervening years). Companion cards: festival taxonomy, method library, timeline-align debts. A `ResearchPort` must attach `source_url` (or `source=factory_seed` for structural festival facts). Unconfirmed plot-year cards **block write**. Context builder injects an `AnnalsSlice` for the chapter's story year. `is_lockable_draft` refuses spoken future titles and known-wrong section names.

- Matches the north star (research before write, fail closed)
- Stops LLM-invented Palme winners and 「柏林一种关注」
- Keeps Writer/Judge prompts untouched
- Workload is irrelevant; this is the quality path

### B. Markdown 查阅卡 in the private repo, human paste into Writer (rejected)

Would survive VM recycle, but the factory would still write without it, and lock gates would not see it. Not a factory object.

### C. Lint-only (regex future titles / wrong section names) with no year cards (rejected)

Catches a few known strings. Does not give Writer 2005/2008 climate, does not stop invented award lists, does not year-gate an open title set.

## 4. Holes this spec closes

| Hole | Live example | Current code |
|---|---|---|
| No research round | Write starts when R5 outlines exist | `ROUND_KINDS = ("R0"…"R5")`; `confirm_round` bounds `0–5` |
| Context has no year | Writer invents 2005 festival climate | `ChapterContextPackage` has outline/kernel/canon, no annals |
| Real titles banned, not year-gated | User override: keep real titles, gate by year | kernel `do_not_write` still 严禁搬运真实片名 |
| Future film spoken as already existing | 活埋 2010, 调音师 2010/2018, 小偷家族 2018, 海边的曼彻斯特 2016, 入殓师 2008 used as *already-released* in 2005 | no title-year fence |
| Wrong festival section | v1c012 柏林一种关注 | no taxonomy lint |
| Wrong calendar | v1c017–020 戛纳「2008年初」; real Cannes is mid-May | no calendar lint on new drafts |
| LLM-invented winners | any planner asked to "fill 2006 三金" | no `ResearchPort`; no source requirement |
| Locked vol.1 errors silently rewritten | — | this spec **flags** debts, does not rewrite CANON_LOCKED |

Already fixed, do not re-open: outline sanitizer, lock gates (POV, 徐姐, mechanism-naming, body-cost, unscheduled character, Judge PASS veto), unscheduled phrase match (#35).

## 5. Design

### 5.1 Artifact and round

Extend:

```python
ROUND_KINDS = ("R0", "R1", "R2", "R3", "R4", "R5", "R6")
ROUND_PROMPTS[6] = "确认写入年代志(故事年跨度的年卡 + 出处)?"
```

`confirm_round` bound becomes `0–6`. `BibleRepo.round_complete` adds `"R6"` when the project has a confirmed annals cover for the derived span (every year in `[span_start, span_end]` has a row, and every **plot-year** card is `status=confirmed`).

R6 always runs after R5, in two modes:

- **Applicable:** at least one year parses from kernel/outlines/volumes. Year cards are required. Writes are blocked until confirm.
- **Not applicable:** zero years parse (e.g. mock 临安城 fixtures). R6 auto-persists a confirmed cover with `applicable=False`, zero year cards, no kernel title-rule patch. Existing non-era tests keep writing.

Do not skip R6. Do not default a span to 2005. Retrofit: project 5 already has R0–R5; generating R6 must not regenerate outlines.

`run_bible_conversation` currently ends at R5. Extend it to R6. `plan_more` (rolling outlines) does not re-run R0–R5; if a new outline year falls outside the confirmed span, `plan_more` must extend the skeleton (new thin/thick cards, unconfirmed) and **block subsequent writes for those years** until R6 is re-confirmed. Do not silently invent the new years.

Concept Judge does not run on R6.

### 5.2 Span derivation (deterministic)

`derive_story_span(kernel, outlines, volumes) -> tuple[int, int]`:

1. Collect four-digit years with a conservative parser from `kernel` setting/logline, each `outline.time_location`, volume titles/summaries.
2. Accept years in `1900–2100`.
3. Span is `min(years)`…`max(years)` inclusive.
4. Zero years → R6 `not_applicable` (no default 2005, no error).
5. Do not add start/end year fields to `StoryKernel`. Span is the min/max of parsed years only.
6. Human may **widen** `span_start`/`span_end` on the pending artifact before confirm (union with parsed years; still `1900–2100`; still no Palme-from-1946 dump). Factory never auto-widens to 2025. For 《穿回去当导演》, the confirm recommendation is widen to 2005–2025 so interstitial years get thin cards before later volumes land. If the human confirms 2005–2008, that is the cover until `plan_more` extends it.

A year is **plot-hit** if at least one outline `time_location` (or volume beat) maps to it; otherwise **interstitial**.

`parse_story_year(time_location: str) -> int | None` is the same parser, single-year. If R6 is applicable, chapter write fails closed when that chapter has no year. If R6 is `not_applicable`, missing year is allowed and `AnnalsSlice.applicable` is False.

### 5.3 Card kinds

One table, payload JSON, discriminated by `kind`.

```python
class YearCard(VersionedSchema):
    year: int
    density: Literal["thick", "thin"]
    climate: str                    # 5–6 lines when thin; festival+三金+industry when thick
    festivals: list[FestivalBeat]   # empty on thin unless a festival actually falls that year
    awards: list[AwardBeat]         # 三金 / Oscar / etc. Only sourced rows
    title_releases: list[TitleRelease]  # films that *exist* as of this year (optional, not an encyclopedia)
    sources: list[SourceRef]        # min 1

class FestivalTaxonomyCard(VersionedSchema):
    festival_id: str                # "cannes" | "berlin" | "venice" | "golden_rooster" | "golden_horse" | ...
    section_names: list[str]        # names that are real for this festival
    not_section_names: list[str]    # e.g. Berlin must not be called 一种关注
    typical_calendar: str           # "Cannes: mid-May; not 年初"
    sources: list[SourceRef]

class MethodLibraryCard(VersionedSchema):
    film_title: str                 # real title, unmodified
    release_year: int
    craft: str                      # writer-facing method, no plot dump
    speak_as_existing_from_year: int  # == release_year
    sources: list[SourceRef]

class TimelineAlignDebt(VersionedSchema):
    chapter_key: str
    issue: str                      # e.g. "v1c012 uses 柏林一种关注"
    action: Literal["flag_only"]    # this spec never rewrites locked prose
    sources: list[SourceRef]
```

`SourceRef`: `{url: str, excerpt: str, accessed: str}` or `{source: "factory_seed", key: str}` for structural taxonomy shipped in code.

**Thick vs thin.** Plot-hit years: climate + that year's relevant festivals/awards that the outlines actually need (not every prize on earth). Interstitial years: 5–6 lines of industry climate, no award-winner lists unless a later outline cites that year.

**YAGNI.** Do not store: full Palme history, daily news, box-office tables, every 2005 release. Title releases on a year card are only those the outlines or method library care about.

**Celebrity names stay variants.** Year cards must not contain (a) any string in the factory real-name denylist or (b) the real-name side of the project's variant map. Award rows store **film title + category** (`金马最佳女主角` / `《长恨歌》`), not 华语明星法律名. Foreign / non-cast names are allowed only when they are not in (a)(b). Prose hard-gates stay as they are.

### 5.4 Film titles (user override)

People: variant names only (unchanged).

Films: **real titles, unmodified**. 林朔's own films use original titles. 黑洞 stays disambiguated (Event Horizon 1997 vs others) on the method/title card, not by renaming.

Prose may name a film as already-existing only if `release_year <= story_year`. A later film may appear on 年代志 as craft (`MethodLibraryCard`) and in Writer context as "method, do not speak as existing". It must not appear in locked prose as a released work.

On R6 confirm, patch the approved kernel's `do_not_write`:

- Drop or rewrite items that match 严禁搬运真实片名 / 真实片名 (exact current phrasing in the live kernel).
- Append one canonical item: `真实片名可写，但故事年尚未上映的作品禁止作为已存在作品说出；未上映片名只存在于年代志方法库。`

Do not silently rewrite Writer prompts. The kernel patch is the bible-level contract; lock gates enforce it.

### 5.5 ResearchPort (fail closed, no invented winners)

```python
class ResearchPort(Protocol):
    def lookup(self, query: str) -> list[SourceRef]: ...
```

R6 generate is two-phase and **must not** ask the LLM to fill award winners unaided:

1. **Skeleton** (deterministic + planner): span, plot-hit vs thin, festivals named in outlines, method titles named in kernel/outlines, timeline-debt scan of locked drafts against taxonomy seeds.
2. **Fill**: for each claim that is not `factory_seed` taxonomy, `ResearchPort.lookup`. A claim without a source stays `status=unconfirmed`.

Default test double: `NullResearchPort` returns `[]` (so unit tests prove fail-closed). Production: a web-backed port (search + fetch) that returns url+excerpt. Human may paste sources into the pending artifact before confirm.

Confirm rules:

- Every year in span has a row.
- Every plot-hit `YearCard` is `confirmed` with `len(sources) >= 1`.
- Every `MethodLibraryCard` has `release_year` and `len(sources) >= 1`.
- Thin cards: `len(sources) >= 1` (climate source is enough; no winner lists required).
- Confirm with any unconfirmed **plot-hit** card → `PlanningError`.
- Title-rule kernel patch runs only when `applicable=True`.

Festival taxonomy structural facts (一种关注 = Cannes Un Certain Regard; Berlinale = February; Venice = Aug/Sep; Cannes = mid-May) ship as `factory_seed` in this public repo. They do not go through the LLM.

### 5.6 Persistence

New table `annals_card`:

| column | notes |
|---|---|
| id | PK |
| project_id | FK project.id |
| kind | `year` / `festival_taxonomy` / `method` / `timeline_debt` |
| card_key | required str: `str(year)` / festival_id / film_title / `{chapter_key}:{debt_id}` |
| year | nullable int; required for `year` kind |
| status | `pending` / `confirmed` |
| payload | JSON (schema above) |
| created_at / updated_at | UTC |

Alembic revision after `e7a1c3d5f902`. One UniqueConstraint: `(project_id, kind, card_key)`.

Use a dedicated `AnnalsRepo` (do not grow `bible.py`). `round_complete` adds `"R6"` when that repo reports a confirmed cover: either `applicable=False`, or every year in the confirmed span exists and every plot-hit year is `confirmed`.

Private canon: after factory lands, dump confirmed cards with `novel.db` the same way locked chapters are backed up. Out of this spec.

### 5.7 Context injection

Add to `ChapterContextPackage`:

```python
annals: AnnalsSlice
```

```python
class AnnalsSlice(VersionedSchema):
    applicable: bool
    story_year: int | None = None
    year_card: YearCard | None = None
    festival_notes: list[str] = []
    method_library: list[MethodLibraryCard] = []
    title_fence: list[str] = []   # titles with release_year > story_year
    timeline_debts: list[str] = []
```

`ChapterContextPackage.annals` is required (update test fixtures). When `applicable=False`, other fields stay empty. When `applicable=True`, `ContextBuilder.build` requires a confirmed year card for `parse_story_year(outline.time_location)`; missing card or missing year → raise `ValueError` (same family as missing kernel/scene cards). `AnnalsSlice` is **required content**: `_trim` must not drop it; include it in `required_size`.

`title_fence` is the list of method-library (and year-card) titles whose `release_year > story_year`. Writer context should state they are craft-only.

`kernel_summary` / `hard_constraints` already carry `do_not_write`; after the R6 kernel patch they carry the year-gate sentence. Do not duplicate a third copy except the fence list (machine-checkable).

### 5.8 Lock gates

Extend `LockGates` (do not add fields to `ChapterOutline`):

```python
annals_year: int | None = None
forbidden_titles: list[str] | None = None          # future titles
forbidden_section_phrases: list[str] | None = None # e.g. ["柏林一种关注"]
```

New detectors, factory-only:

1. **Future title spoken as existing.** If any `forbidden_titles` string appears in the draft, block. Matching is literal title. Test fixtures must cover 活埋, 小偷家族, 海边的曼彻斯特, 调音师, 入殓师, and the typo 入检师 (same fence as 入殓师). Do not block 林朔's original titles. Do not block a title whose release_year ≤ annals_year (those are not in `forbidden_titles`).
2. **Wrong section phrase.** Literal `forbidden_section_phrases` (seed includes `柏林一种关注`). Block on new drafts only.
3. **Cannes calendar pair.** If `forbidden_section_phrases` includes `戛纳年初` (derived from Cannes taxonomy `typical_calendar` = mid-May), block a new draft that contains both `戛纳` and one of `年初` / `1月` / `2月` / `3月`. Do not block `戛纳` alone.

`volume_run` / `run_chapter_loop` **must not start** a chapter if R6 is missing, or if R6 is applicable and that chapter's year card is unconfirmed. New `VolumeStopReason` / loop error: `NEEDS_ANNALS`. Do not write then HUMAN_REVIEW; fail before n2. `not_applicable` covers do not emit `NEEDS_ANNALS`.

Locked chapters: skip as today. Timeline debts stay `flag_only`.

### 5.9 Seed taxonomy (public, structural)

Ship in code (not LLM), at least:

| fact | lint / card use |
|---|---|
| 一种关注 = Cannes Un Certain Regard | `not_section_names` for Berlin and Venice |
| Berlinale ≈ February; sections Competition / Panorama / Forum | calendar + taxonomy |
| Venice ≈ Aug/Sep; main competition 主竞赛 | calendar |
| Cannes ≈ mid-May, not 年初 | calendar lint for new drafts that place 戛纳 in 年初 of a Cannes year |
| 金鸡 in this era is not a safe annual (2005 then 2007 gap) | year-card climate; do not auto-rewrite locked 2006 金鸡提名, record as debt if outlines claim it |

Method-library *examples* for tests (release years are public facts): 活埋 2010; 调音师 French short César 2012 / Andhadhun 2018; 小偷家族 Cannes 2018 Palme; 海边的曼彻斯特 Oscars 2017; 入殓师 Montreal 2008 / Oscar 2009. Production fill for project 5 happens in private canon.

### 5.10 Testing

- `tests/unit/test_annals_span.py` — derive span from parsed years; zero years → `not_applicable`; human widen 2005–2025; no auto-widen; plot-hit vs thin.
- `tests/unit/test_annals_research.py` — NullResearchPort leaves plot-hit unconfirmed; confirm refused; sourced fill confirms; LLM path never writes `awards` without `SourceRef`.
- `tests/unit/test_annals_context.py` — applicable + missing year card raises; `not_applicable` slice allowed; slice not trimmed.
- `tests/unit/test_factory_gates.py` — extend: 2005 draft containing 活埋 / 小偷家族 / 柏林一种关注 / 戛纳+年初 is not lockable; 2005 draft naming a 1997 黑洞 is lockable if that title is not fenced; 入检师 treated as 入殓师 fence.
- `tests/workflow/` — era project (years in outlines) cannot `volume_run` until R6 confirmed; after confirm, n2 receives `annals.applicable=True`; no-year project auto-completes R6 `not_applicable` and may `volume_run`.
- Do not require live web in CI. Web port tests mock HTTP.

### 5.11 Out of scope

- Rewriting Writer/Judge/retrieval prompts
- Rewriting locked v1c001–020
- Dumping filled 2005–2025 cards onto this public repo
- Palme d'Or encyclopedia, box office, daily news
- Changing `ChapterOutline` schema (`time_location` stays a string)
- PR #24, outline sanitizer, existing lock-gate detectors
- Ports, Redis, a second runner

## 6. Data flow

```text
R5 outlines confirmed
    → derive_story_span (or not_applicable)
    → R6 skeleton (year rows + taxonomy seed + method stubs + locked-draft debts)
    → ResearchPort fill (url+excerpt or unconfirmed)
    → human confirm (plot-hit cards must be confirmed; kernel title-rule patched if applicable)
    → ChapterContextPackage.annals
    → Writer (prompts unchanged; slice is in ctx)
    → is_lockable_draft (+ future titles + wrong sections + 戛纳年初)
    → CANON_LOCKED (new chapters only)
```

## 7. Error handling

| case | behavior |
|---|---|
| Cannot derive span | R6 `not_applicable` cover, auto-confirmed |
| Applicable + chapter has no year | `ContextBuilder` / loop raises; do not write |
| Plot-hit card unconfirmed | confirm refused; `volume_run` `NEEDS_ANNALS` |
| ResearchPort returns nothing | card stays unconfirmed; never LLM-backfill winners |
| `plan_more` introduces a new year | new unconfirmed card; writes for that year blocked |
| Locked chapter fails new lint | ignored (skip locked); debt row `flag_only` |
| Kernel has 严禁搬运真实片名 | replaced on R6 confirm, not earlier |

## 8. Success criteria

1. An era project (parsed years) with R5 but no confirmed applicable R6 cannot start `volume_run`. A no-year project auto-completes R6 `not_applicable` and can.
2. A confirmed R6 injects `AnnalsSlice` for a 2005 chapter; `title_fence` includes 活埋 and 小偷家族; draft text 「他想起《活埋》」 is not lockable; 「手贴上去的时候没有犹豫」 remains lockable.
3. 「柏林一种关注」 is not lockable on a new draft.
4. No test and no generate path invents an award winner without a `SourceRef`.
5. Locked vol.1 is byte-identical after this factory change (debts recorded only).
6. Public repo contains no filled 《穿回去当导演》 year-card dump.

