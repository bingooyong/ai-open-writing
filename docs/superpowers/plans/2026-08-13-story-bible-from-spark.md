# Story Bible from a Spark — Implementation Plan

> For agentic workers: implement task-by-task. Do not skip ahead. After each task: `uv run pytest -q && uv run ruff check . && uv run mypy src` must stay green. Spec: `docs/superpowers/specs/2026-08-13-story-bible-from-spark-design.md`.

**Goal:** From a user spark, a multi-round conversation persists a confirmed Story Bible (kernel, structure map, characters, relationship graph projection, conflicts, 爽点, rolling 5 chapter outlines) that the existing chapter factory can consume with no translator.

**Out of this plan:** million-word production, Stage 1 G6 UI, analyzer extract-from-text pipeline, M3.3 chapter loop (separate PR), copying analyzer source files.

**Stack:** Python 3.11+, uv, SQLModel, Alembic, Typer, existing `ModelGateway` + mock provider, Pydantic v2. Cognitive turns remain bounded tool-free single-shots.

**Lock these decisions (do not reopen):**

- Canon-native: graph is a projection of `relationship_state` + `CanonDelta.relationship_changes`, never a second extracted graph.
- Conversation memory = last confirmed artifacts, not chat logs.
- R0→R5 order is mandatory (Spark, Kernel, Structure, People, Engine, Spine).
- Stop stuffing brief into `channel_profile`. Use `project.spark` and `project.brief` columns (not a `bible_meta` JSON blob).
- Conflict `kind` enum: `interest | value | emotion | identity | time`.
- Analyzer is inspiration only. New files, new DTO, no copied JSX/Python.

## File map (create unless noted)

```
src/novel_agent/domain/schemas/structure.py   # StructureMap, Conflict, PayoffBeat, IdentityAlias, StoryBrief
src/novel_agent/domain/repos/bible.py         # BibleRepo
src/novel_agent/planning/conversation.py      # R0–R5 orchestrator
src/novel_agent/lint/bible.py                 # 黄金三章 + 爽点 spacing + orphan conflicts
src/novel_agent/graph/__init__.py             # package marker
src/novel_agent/graph/projector.py            # canon → Graph DTO
src/novel_agent/graph/export.py               # json | mermaid
prompts/structure_planner.md
prompts/conflict_planner.md
prompts/payoff_planner.md
alembic/versions/<rev>_story_bible.py         # down_revision = af5362846a20
tests/contract/test_story_bible.py
tests/contract/test_graph_projector.py
```

Modify: `tables.py`, `models/__init__.py`, `schemas/__init__.py`, `repos/__init__.py`, `planning.py` (PlanningRepo list helpers already exist), `cli/main.py`, `runtime/agents.py` (add three `run_*` planners at module level — no new inline imports), `planning/mock_fixtures.py`, `planning/chain.py` only if conversation needs a thin hook — do not turn it into a god object. `outline.py` (additive citation lists). `HANDOFF.md`.

Keep callable: `run_planning_chain` and `novel plan` (M3.2 tests). `novel init` switches to conversation in Task 7; `novel bible` resumes it.

---

## Task 1: Schema + migration

**Files:**

- Create: `src/novel_agent/domain/schemas/structure.py`
- Create: `tests/contract/test_story_bible.py` (schema tests only this task)
- Create: `alembic/versions/<rev>_story_bible.py`
- Modify: `src/novel_agent/domain/models/tables.py`
- Modify: `src/novel_agent/domain/models/__init__.py`
- Modify: `src/novel_agent/domain/schemas/__init__.py`

Pydantic schema tests do not need a database. Write those tests first. Tables + Alembic follow so `create_all` (tests) and production migrations stay in sync. Head revision today: `af5362846a20`.

### Steps

1. **Failing tests first** in `tests/contract/test_story_bible.py`:
   - `test_conflict_rejects_unknown_kind`: `kind="time-pressure"` raises `ValidationError`.
   - `test_conflict_accepts_time_kind`: `kind="time"` round-trips.
   - `test_payoff_beat_requires_chapter_or_unit`: both `chapter_key` and `unit_id` omitted raises `ValidationError`.
   - `test_payoff_beat_whitespace_pressure_is_invalid`: `pressure_before="   "` raises `ValidationError` (schema strips / min_length after strip — do not wait for lint).
   - `test_structure_map_golden_three_must_be_length_3`: 2 or 4 `GoldenThreeChapter` rows raises `ValidationError`.
   - Valid fixtures for `StoryBrief`, `StructureMap` (six beats + exactly three golden_three), `Conflict` (parties min 2), `PayoffBeat` with only `chapter_key`, `IdentityAlias`.

   Run (expect collection/import failure, then assertion failure until models exist):

   ```bash
   uv run pytest -q tests/contract/test_story_bible.py -k schema
   ```

2. Add VersionedSchema models in `structure.py` (`extra=forbid` via base). Imports at module top.

   - `StoryBrief(genre, audience, do_not_write: list[str], spark: str)`
   - `StructureBeat(summary, volume_id: str | None = None, chapter_key: str | None = None)`
   - `GoldenThreeChapter(promise, escalation, payoff_or_hook)`
   - `StructureMap(template: Literal["three_act"] = "three_act", inciting_incident, commitment, midpoint, all_is_lost, climax, resolution: StructureBeat, golden_three: list[GoldenThreeChapter]` with `Field(min_length=3, max_length=3)`)
   - `Conflict(conflict_id, kind: Literal["interest", "value", "emotion", "identity", "time"], parties: list[str]` min 2, `stake, temperature: Literal["setup", "rising", "peak", "paid"], must_affect: Literal["plot", "relationship", "both"], payoff_chapter_key: str | None = None)`
   - `PayoffBeat(beat_id, scale: Literal["micro", "small", "large"], kind: str, pressure_before: str, hit: str, chapter_key: str | None = None, unit_id: str | None = None, order_index: int)` — `field_validator` strips `pressure_before`/`hit` and requires min length 1; `model_validator` requires at least one of `chapter_key`/`unit_id`
   - `IdentityAlias(canonical_character_id, alias)`

3. Tables (additive; existing M3.2 rows stay valid):

   - `ProjectRecord`: `spark: str = ""`, `brief: str = ""` (plain columns, not JSON).
   - `structure_map`: `project_id` unique-with-version like `story_kernel`; `version: int`; `payload` JSON (`StructureMap`).
   - `conflict`: `project_id`, `conflict_id`, unique `(project_id, conflict_id)`, `payload` JSON.
   - `payoff_beat`: `project_id`, `beat_id`, unique `(project_id, beat_id)`, `order_index`, `payload` JSON.
   - `identity_alias`: unique `(project_id, alias)`; columns `canonical_character_id`, `alias`.

   Export new records from `models/__init__.py`. Export new schemas from `schemas/__init__.py`.

4. Alembic revision `Revises: af5362846a20`: add the four tables + two project columns (`server_default=""` so existing DBs upgrade). Downgrade drops them.

5. Re-run schema tests; then full gate:

   ```bash
   uv run pytest -q tests/contract/test_story_bible.py -k schema
   uv run pytest -q && uv run ruff check . && uv run mypy src
   ```

6. Commit: `feat(bible): StoryBrief/StructureMap/Conflict/PayoffBeat schemas and migration`

---

## Task 2: BibleRepo

**Files:**

- Create: `src/novel_agent/domain/repos/bible.py`
- Modify: `src/novel_agent/domain/repos/__init__.py`
- Modify: `tests/contract/test_story_bible.py`

Use tmp sqlite + `create_all` like `tests/contract/test_planning_chain.py`. `BibleRepo` is the SQL boundary for the new tables; do not query them from conversation/CLI directly.

### Steps

1. **Failing tests first** (same contract file, `-k repo` or un-filtered bible tests):
   - `save_brief` / `get_brief` round-trip `StoryBrief`; also sets `project.spark` / `project.brief`.
   - `save_structure_map` versions; `get_structure_map` returns latest.
   - `replace_conflicts` / `list_conflicts`; `replace_payoff_beats` / `list_payoff_beats` (replace = delete+insert for that project).
   - `upsert_alias` / `list_aliases` / `delete_alias`.
   - `test_alias_cycle_rejected`: alias equal to canonical, or A→B when B already aliases to A, raises `ValueError`.
   - `round_complete(project_id) -> set[str]`:
     - R0 if brief/spark stored
     - R1 if `PlanningRepo.get_approved_kernel` is not None
     - R2 if a structure_map row exists
     - R3 if `PlanningRepo.list_characters` length ≥ 1
     - R4 if ≥1 conflict **and** ≥1 payoff beat
     - R5 if `PlanningRepo.list_chapters` length ≥ 1
   Empty project → empty set.

   ```bash
   uv run pytest -q tests/contract/test_story_bible.py
   ```

2. Implement `BibleRepo(session)` with exactly: `save_brief`, `get_brief`, `save_structure_map`, `get_structure_map`, `replace_conflicts`, `list_conflicts`, `replace_payoff_beats`, `list_payoff_beats`, `upsert_alias`, `delete_alias`, `list_aliases`, `round_complete`. Inject or construct `PlanningRepo(session)` inside `round_complete` — do not duplicate kernel/character/chapter SQL.

3. Alias cycle: if `alias == canonical_character_id`, reject. If adding `alias=X canonical=Y` would close a cycle through existing rows (follow canonical pointers), reject. Deleting a mapping does not rewrite history (delete row only).

4. Full gate, then commit: `feat(bible): BibleRepo CRUD and round-complete detection`

---

## Task 3: Stop stuffing brief into channel_profile

**Files:**

- Modify: `src/novel_agent/cli/main.py` (`_store_brief` / `_resolve_brief`)
- Modify: `src/novel_agent/domain/repos/planning.py` only if a tiny `set_project_brief` helper is cleaner than CLI mutating `ProjectRecord` fields (CLI already uses `PlanningRepo.get_project`; prefer adding `PlanningRepo.set_spark_brief(project_id, spark, brief)` so CLI stays SQL-free).
- Modify M3.2 tests only if they assumed `channel_profile["brief"]` (today they do not assert that key).

### Steps

1. **Failing test first** in `tests/contract/test_planning_chain.py` or `test_story_bible.py`:
   - After `novel init TITLE --brief TEXT --yes` (still the old chain this task), `ProjectRecord.brief == TEXT` and `ProjectRecord.spark == TEXT`.
   - `channel_profile` is not written with `"brief"`.
   - `_resolve_brief`: if columns empty but `channel_profile["brief"]` exists, return that string **and persist into `project.brief`** (one-release read fallback). Do not write `channel_profile` on the way out.

   ```bash
   uv run pytest -q tests/contract/test_planning_chain.py tests/contract/test_story_bible.py
   ```

2. `_store_brief`: write `project.spark` and `project.brief` to the new columns. Stop assigning `channel_profile["brief"]`.
3. `_resolve_brief`: prefer CLI `--brief` if non-empty; else `project.brief`; else `project.spark`; else fallback `channel_profile["brief"]` then persist into `brief`.
4. Existing `novel init --yes` / `novel plan --yes` / non-TTY exit 2 tests still pass.
5. Full gate, then commit: `fix(planning): persist spark/brief on project, not channel_profile`

---

## Task 4: Bible lint

**Files:**

- Create: `src/novel_agent/lint/bible.py`
- Modify: `tests/contract/test_story_bible.py`

Follow the existing `LintFinding` / `LintReport` shape in `src/novel_agent/lint/__init__.py` (new codes, same dataclass). Raise/return a structured list of violations. Callers (Task 6/9) do not persist outlines when `not report.passed`.

### Steps

1. **Failing tests first** — each rule a pass/fail pair:
   1. **黄金三章:** chapter 1 outline whose `core_event` / `entry_point` is lore-only (no live problem) fails. Fixture fail: `core_event="世界观年表与门派谱系"`, `entry_point="旁白铺陈三百年历史"`. Fixture pass: existing M3.2 chapter-1 mock (live incident + 茶楼现场). Heuristic: fail if chapter 1 text has no protagonist-present problem (no 成真/冲突/危机/失火/上门/代价/人质 style concrete incident **and** reads as 设定/世界观/背景 dump). Do not call an LLM.
   2. **爽点 spacing:** three consecutive `scale=large` beats with empty/whitespace `pressure_before` fails. Schema already blocks `""` / `"   "`; this lint still fails if three consecutive larges have no distinct pressure text (whitespace-only counted empty). Pass: larges interleaved with non-empty `pressure_before`, or not three consecutive larges.
   3. **Orphan conflict:** `payoff_chapter_key` missing, or not in the rolling 5 keys, fails at R5. Pass: every conflict’s `payoff_chapter_key` is in `{"v1c001", …}`.
   4. **Relationship proposal without evidence:** a `RelationshipChange` / relationship_state row with empty or whitespace `evidence` fails (same discipline as `ReviewIssue` evidence required). Pass: non-empty evidence string.

   ```bash
   uv run pytest -q tests/contract/test_story_bible.py -k lint
   ```

2. Implement `lint_bible(...)` taking outlines, conflicts, payoff beats, and relationship rows/proposals; return `LintReport`.
3. Full gate, then commit: `feat(bible): golden-three, payoff-spacing, and orphan-conflict lint`

---

## Task 5: New planners (mock-first)

**Files:**

- Create: `prompts/structure_planner.md`, `prompts/conflict_planner.md`, `prompts/payoff_planner.md`
- Modify: `src/novel_agent/runtime/agents.py`
- Modify: `src/novel_agent/planning/mock_fixtures.py`
- Modify: `tests/contract/test_story_bible.py` (and/or `tests/contract/test_agents.py` if that is where planner parse tests live)

Prompts: YAML frontmatter `version` / `role` / `slot: creative` / `input_schema` / `output_schema` like `prompts/kernel_planner.md`. Tool-free. `${schema}` only. Output JSON matching the new schemas.

Put any wrapper `BaseModel` list types at **module top** of `agents.py` (existing character/outline planners use inline imports — do not add more).

### Steps

1. **Failing tests first:**
   - `load_prompt("structure_planner")` / `conflict_planner` / `payoff_planner` succeed.
   - `run_structure_planner` / `run_conflict_planner` / `run_payoff_planner` against `MockProvider` + registered fixtures parse into `StructureMap` / `list[Conflict]` / `list[PayoffBeat]`.
   - Payoff fixture uses planned keys `v1c001..v1c005` and non-empty `pressure_before`.

   ```bash
   uv run pytest -q tests/contract/test_story_bible.py -k planner
   ```

2. Implement:

   - `run_structure_planner(deps, kernel_text, brief) -> StructureMap`
   - `run_conflict_planner(deps, kernel_text, characters_text, brief) -> list[Conflict]`
   - `run_payoff_planner(deps, kernel_text, conflicts_text, brief, chapters_needed=5) -> list[PayoffBeat]`

   Same `CognitiveAgent` + `ModelRequest` pattern as `run_kernel_planner`.

3. Extend `register_planning_defaults` (or add `register_bible_defaults` and call it from the existing register so `--yes` needs no network). Valid JSON only.

4. Full gate, then commit: `feat(bible): structure/conflict/payoff planners with mock fixtures`

---

## Task 6: Conversation orchestrator R0–R5

**Files:**

- Create: `src/novel_agent/planning/conversation.py`
- Modify: `src/novel_agent/domain/schemas/outline.py` — additive `cited_conflict_ids: list[str] = []`, `cited_beat_ids: list[str] = []` on `ChapterOutline` (defaults empty; existing fixtures stay valid)
- Modify: `src/novel_agent/planning/mock_fixtures.py` — each of the 5 mock outlines cites ≥1 conflict_id or beat_id
- Modify: `tests/contract/test_story_bible.py`

Do not grow `planning/chain.py`. Reuse `PlanningGates` (`select_kernel`, `confirm`). `--yes` = `PlanningGates.auto`. Reuse `run_kernel_planner` / `run_character_planner` / `run_outline_planner`.

R3 relationships: no new proposal table. On confirm, `CanonWriter.stage_provisional(delta, idempotency_key=f"bible-r3-{project_id}")` with `CanonDelta.chapter_key = f"{volume_id}c001"` (row need not exist yet), `base_canon_version` from `CanonRepo.current_canon_version`. That writes `relationship_state` with `provisional=True`. Evidence required (lint + `RelationshipChange.evidence` min_length=1). Alias merge: call `BibleRepo.upsert_alias` if the character planner emitted aliases; otherwise no-op.

R4: planners only; persist conflicts/payoffs; **do not** `create_chapter`. Payoff `chapter_key`s are planned `v1c001..v1c00N`.

R5: outline planner, then `lint_bible`; on lint fail do **not** persist outlines/units/volumes. Abort one round = `PlanningAborted(stage, project_id)` with stage in `{spark, kernel, structure, people, engine, spine}`; keep earlier rounds.

### Steps

1. **Failing tests first:**
   - Full `--yes` from a spark persists kernel, structure map, characters, conflicts, payoff beats, 5 outlines; each outline cites ≥1 conflict or 爽点; `round_complete` includes R0–R5.
   - Abort at R3 (`confirm` False on people) raises `PlanningAborted`; approved kernel remains; no characters.
   - Resume: persist through R3, call `run_bible_conversation` again with `--yes`; R0–R3 skipped; R4–R5 run.
   - R5 lint fail (lore-only chapter 1 fixture) does not persist chapters.

   ```bash
   uv run pytest -q tests/contract/test_story_bible.py
   ```

2. Implement `async def run_bible_conversation(repo, bible, deps, spark, gates, *, volume_id="v1", chapters_needed=5) -> BibleResult`.

   Skip completed rounds via `bible.round_complete`.

   | Round | Behavior |
   |---|---|
   | R0 | Deterministic `StoryBrief`: `spark` stored; `genre`/`audience` empty-ok; `do_not_write` from `project.boundaries`. No LLM. Confirm, `save_brief`. |
   | R1 | `run_kernel_planner` + `select_kernel` + approve (same persist as chain). |
   | R2 | `run_structure_planner` + confirm + `save_structure_map`. |
   | R3 | `run_character_planner` + confirm + `upsert_character`; provisional relationships via CanonWriter as above. |
   | R4 | conflict + payoff planners; confirm; `replace_conflicts` / `replace_payoff_beats`. |
   | R5 | `run_outline_planner`; lint; persist volume/unit/outlines/scene cards only if lint passes (same PlanningRepo methods as chain). |

   Conversation memory for each LLM call = last confirmed artifacts (kernel/characters/conflicts text), not a chat transcript.

3. `BibleResult` dataclass: `project_id`, kernel/character/volume/unit/chapter fields like `PlanningResult`, plus skipped rounds.

4. Existing `tests/contract/test_planning_chain.py` still passes (`run_planning_chain` unchanged).

5. Full gate, then commit: `feat(bible): R0–R5 conversation orchestrator`

---

## Task 7: CLI

**Files:**

- Modify: `src/novel_agent/cli/main.py`
- Modify: `tests/contract/test_story_bible.py` and existing CLI tests in `test_planning_chain.py`

Do **not** add `novel graph` here (Task 8). Keep `novel plan` on `run_planning_chain`.

### Steps

1. **Failing tests first** (spec §9 items 1, 5, 6):
   1. `novel init TITLE --brief SPARK --yes` runs `run_bible_conversation` (not the old single chain). Persists kernel, structure map, characters, conflicts, payoff beats, 5 outlines; each outline cites ≥1 conflict or 爽点. Spark stored on `project.spark`.
   5. Kill after R3 (save artifacts, then `novel bible --project-id N --yes`): skips R0–R3, continues R4.
   6. Direct `run_planning_chain` tests and `novel plan --yes` still pass.
   - Non-TTY without `--yes` still exits 2 (`test_cli_init_without_yes_exits_in_non_interactive_env`).
   - `novel bible --project-id ID [--brief] [--yes]` resumes; missing project exits 2.

   ```bash
   uv run pytest -q tests/contract/test_planning_chain.py tests/contract/test_story_bible.py
   ```

2. `novel init`: create project, `_store_brief` (spark+brief from `--brief`), then `run_bible_conversation`. Keep `--yes`, `--select`, `--brief`, `--chapters`, `--volume-id`.
3. Add `novel bible --project-id ID [--brief] [--yes] [--select]`.
4. Echo enough fields that tests can assert `project_id=` (reuse `_echo_planning_result` or a thin bible echo).
5. Full gate, then commit: `feat(cli): novel init/bible conversation entrypoints`

---

## Task 8: Graph projector + export

**Files:**

- Create: `src/novel_agent/graph/__init__.py`, `projector.py`, `export.py`
- Modify: `src/novel_agent/cli/main.py`
- Create: `tests/contract/test_graph_projector.py`

DTO **exactly** as spec §7. Projector never calls an LLM. `canon_version` = `CanonRepo.current_canon_version(project_id)` (`canon_vN`).

```json
{
  "project_id": 1,
  "canon_version": "…",
  "nodes": [{"id": "ch_su", "label": "苏某", "kind": "character|faction|alias", "alias_of": null}],
  "edges": [{"source": "ch_su", "target": "ch_li", "label": "师徒", "state": "strained", "evidence": "…", "source_chapter": "v1c003", "provisional": false, "occurrence": 2}],
  "tracks": [{"parties": ["ch_su", "ch_li"], "beats": [{"chapter_key": "v1c001", "from_state": "strangers", "to_state": "allies", "evidence": "…"}]}]
}
```

Empty `evidence` on an edge: keep the edge; set `evidence` to `"暂无可追溯证据"` (do not drop). `kind` on a node is one of `character` | `faction` | `alias` (not the pipe-string).

### Steps

1. **Failing tests first:**
   - Empty after R1 (kernel only, no characters): `nodes == []`, `edges == []`, `tracks == []` is valid.
   - Populated after R3: character nodes; edges from `relationship_state`; `provisional` copied to DTO.
   - Alias: node `kind=alias`, `alias_of=canonical_id`; occurrence merged onto the canonical pair.
   - Missing evidence labeled, not dropped.
   - `export_graph(dto, "json")` / `"mermaid"` (`graph LR` with labels).

   ```bash
   uv run pytest -q tests/contract/test_graph_projector.py
   ```

2. Implement `project_graph(session, project_id) -> dict`:
   - Nodes from characters + `identity_alias` + faction labels parsed from character `identity` / `entity_state` (label only; no faction table).
   - Edges from `relationship_state` (`CanonRepo` list/get). `label` may equal `state` if no separate label column (table has `state` only — use `state` for both `label` and `state` unless payload later adds a label; do not add a column this plan).
   - Tracks from committed `CanonDelta.payload.relationship_changes` grouped by unordered pair `(party_a, party_b)`.
3. `export_graph(dto, format: Literal["json", "mermaid"]) -> str`.
4. CLI: `novel graph --project-id ID [--format json|mermaid]` prints the export. Unknown format exits 2.
5. Full gate, then commit: `feat(graph): canon projector and novel graph export`

---

## Task 9: Wire lint into R5 + HANDOFF

**Files:**

- Modify: `src/novel_agent/planning/conversation.py` only if R5 persist-on-lint-fail is not already locked
- Modify: `HANDOFF.md`
- Modify tests if spec §9.2–9.3 cases are missing

### Steps

1. Confirm R5 will not persist on lint failure (Task 6 test). Add any missing case:
   - §9.2 黄金三章 lore-only chapter 1 fails; contract-following bible passes.
   - §9.3 three consecutive large beats with empty `pressure_before` fails.
2. Update `HANDOFF.md`:
   - Planning entry is Story Bible conversation (`novel init` / `novel bible`).
   - M3.2 `run_planning_chain` / `novel plan` remains a subroutine.
   - This bible work can land before or after M3.3; next factory work is still M3.3 / M3.3b / M3.4 if those are open.
   - Point at this plan and the approved spec paths.
   - Do not claim million-word production or Stage 1 G6 as done.
3. Full gate:

   ```bash
   uv run pytest -q && uv run ruff check . && uv run mypy src
   ```

4. Commit: `docs: HANDOFF for Story Bible conversation`

---

## Definition of done

Spec §11: spark → confirmed bible with three-level outline, character summaries, graph JSON matching `relationship_state`, conflicts that pay off in the rolling 5, 爽点 with pressure-before-hit, three-act + 黄金三章. Chapter factory can consume outlines without a translator.

Merge-gate tests (mock only, spec §9):

1. Conversation `--yes` from a spark persists kernel, structure map, characters, conflicts, payoff beats, 5 outlines; each outline cites at least one conflict or 爽点.
2. 黄金三章 lint: lore-only chapter 1 fails; contract-following passes.
3. 爽点 spacing lint: three consecutive large beats with empty `pressure_before` fails.
4. Graph projector: fixture canon → nodes/edges; alias merge; provisional marked; missing evidence labeled, not dropped.
5. Resume: kill after R3, `novel bible --yes` skips R0–R3, continues R4.
6. Existing M3.2 tests still pass (chain remains callable).

---

## Self-review

- No TBD / TODO / “decide later”.
- Every task ends with a commit message.
- No task implements Stage 1 G6 UI, million-word batch, analyzer extract-from-text, or M3.3 N1–N9.
- R0→R5 order, `project.spark`/`project.brief`, conflict `kind=time`, canon-native graph DTO, and mock-only CI are locked.
- Tasks are small enough to execute without inventing a second database or a second FastAPI app.
