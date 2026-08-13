# Story Bible from a Spark — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Spark (or `--yes`) yields a confirmed Story Bible: kernel, structure map, characters, graph JSON matching `relationship_state`, conflicts that pay off in the rolling 5, 爽点 with pressure-before-hit, three-act + 黄金三章. Existing chapter factory consumes outlines without a translator.

**Architecture:** Canon-native. Conversation writes the same tables the production loop trusts. Graph is a projection of `relationship_state` + `CanonDelta.relationship_changes`, never a second extracted graph. Conversation memory is last confirmed artifacts, not chat logs. Do not grow `planning/chain.py` into a god object; M3.2 chain remains a subroutine.

**Tech stack:** Python 3.11+, uv, SQLModel, Alembic, Pydantic, Typer, pytest/ruff/mypy. Cognitive turns go through existing `ModelGateway` + mock fixtures; no paid APIs in tests.

**Spec:** `docs/superpowers/specs/2026-08-13-story-bible-from-spark-design.md` (approved 2026-08-13)

## Locked decisions

- R0→R5 order is mandatory. Skip completed rounds on resume.
- Persist spark/brief on `project.spark` and `project.brief`. One-release read fallback from `channel_profile["brief"]` then migrate into `brief`. Stop writing `channel_profile`.
- Conflict `kind`: `interest | value | emotion | identity | time`.
- R3 relationships: persist as `relationship_state` rows with `provisional=True` (empty or `planning` `source_chapter`). Do **not** call CanonWriter at planning time.
- After every task: `uv run pytest -q && uv run ruff check . && uv run mypy src` green.

## File map

Create:

```
src/novel_agent/domain/schemas/structure.py
src/novel_agent/domain/repos/bible.py
src/novel_agent/planning/conversation.py
src/novel_agent/lint/bible.py
src/novel_agent/graph/projector.py
src/novel_agent/graph/export.py
prompts/structure_planner.md
prompts/conflict_planner.md
prompts/payoff_planner.md
alembic/versions/<rev>_story_bible.py
tests/contract/test_story_bible.py
tests/contract/test_graph_projector.py
```

Modify: `tables.py`, `schemas/__init__.py`, `repos/__init__.py`, `cli/main.py`, `runtime/agents.py`, `planning/mock_fixtures.py`, `ChapterOutline` (additive `cited_conflict_ids` / `cited_beat_ids`), `HANDOFF.md`.

---

### Task 1: Schema + migration

**Files:**
- Create: `src/novel_agent/domain/schemas/structure.py`
- Create: `alembic/versions/<rev>_story_bible.py`
- Modify: `src/novel_agent/domain/schemas/outline.py` (additive citation lists)
- Modify: `src/novel_agent/domain/schemas/__init__.py`
- Modify: `src/novel_agent/domain/models/tables.py`
- Modify: `src/novel_agent/domain/models/__init__.py`
- Test: `tests/contract/test_story_bible.py` (schema cases)

**Step 1: Write failing schema tests**

Cover:
- `StoryBrief`, `StructureBeat`, `StructureMap`, `GoldenThreeChapter` (exactly 3), `Conflict`, `PayoffBeat` (at least one of `chapter_key`/`unit_id`), `IdentityAlias`.
- Invalid conflict `kind` rejected.
- `PayoffBeat` missing both keys rejected.
- `golden_three` length != 3 rejected.

**Step 2: Run tests — expect FAIL** (imports / validation missing)

**Step 3: Implement schemas + tables + Alembic**

Tables: `structure_map`, `conflict`, `payoff_beat`, `identity_alias` unique `(project_id, alias)`. Project columns `spark`, `brief`.

**Step 4: Run `uv run pytest -q && uv run ruff check . && uv run mypy src` — expect PASS**

**Step 5: Commit**

```bash
git add src/novel_agent/domain/schemas/structure.py src/novel_agent/domain/schemas/outline.py src/novel_agent/domain/schemas/__init__.py src/novel_agent/domain/models/tables.py src/novel_agent/domain/models/__init__.py alembic/versions/*_story_bible.py tests/contract/test_story_bible.py
git commit -m "feat(bible): StoryBrief/StructureMap/Conflict/PayoffBeat schemas and migration"
```

---

### Task 2: BibleRepo

**Files:**
- Create: `src/novel_agent/domain/repos/bible.py`
- Modify: `src/novel_agent/domain/repos/__init__.py`
- Test: `tests/contract/test_story_bible.py`

**Step 1: Write failing CRUD tests**

- save/get brief, structure map, replace/list conflicts and payoff beats, upsert/delete/list aliases
- `round_complete(project_id) -> set` of finished rounds R0–R5
- Alias cycle / alias==canonical raises `ValueError`

**Step 2: Run tests — expect FAIL**

**Step 3: Implement BibleRepo**

**Step 4: Full verify — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(bible): BibleRepo CRUD and round-complete detection"
```

---

### Task 3: brief storage

**Files:**
- Modify: `src/novel_agent/cli/main.py`
- Test: existing `novel init --yes` tests still pass; add fallback/migrate coverage in `tests/contract/test_story_bible.py`

**Step 1: Write failing tests** for column persist + `channel_profile["brief"]` fallback then migrate; never write `channel_profile`.

**Step 2: Run tests — expect FAIL**

**Step 3: Change `_store_brief` / `_resolve_brief` to use `project.spark` / `project.brief`.

**Step 4: Full verify — expect PASS**

**Step 5: Commit**

```bash
git commit -m "fix(planning): persist spark/brief on project, not channel_profile"
```

---

### Task 4: bible lint

**Files:**
- Create: `src/novel_agent/lint/bible.py`
- Test: `tests/contract/test_story_bible.py`

**Step 1: Write failing lint tests**

- 黄金三章: lore-only chapter 1 fails
- 爽点: three consecutive large beats with whitespace-only `pressure_before` fails (treat whitespace as empty)
- Orphan conflict: missing `payoff_chapter_key` or not in rolling 5 fails at R5
- Relationship proposal without evidence fails

**Step 2: Run tests — expect FAIL**

**Step 3: Implement lint**

**Step 4: Full verify — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(bible): golden-three, payoff-spacing, and orphan-conflict lint"
```

---

### Task 5: planners mock-first

**Files:**
- Create: `prompts/structure_planner.md`, `prompts/conflict_planner.md`, `prompts/payoff_planner.md`
- Modify: `src/novel_agent/runtime/agents.py`
- Modify: `src/novel_agent/planning/mock_fixtures.py`
- Test: `tests/contract/test_story_bible.py`

**Step 1: Write failing tests** that `run_structure_planner` / `run_conflict_planner` / `run_payoff_planner` return valid schemas from mock fixtures. Prompts have YAML frontmatter + schema refs.

**Step 2: Run tests — expect FAIL**

**Step 3: Implement planners + fixtures**

**Step 4: Full verify — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(bible): structure/conflict/payoff planners with mock fixtures"
```

---

### Task 6: conversation R0–R5

**Files:**
- Create: `src/novel_agent/planning/conversation.py`
- Modify: `src/novel_agent/planning/__init__.py` (export, do not bloat `chain.py`)
- Test: `tests/contract/test_story_bible.py`

**Step 1: Write failing orchestrator tests**

- `--yes` / `PlanningGates.auto` full persist
- Abort R3 keeps kernel
- Resume after R3 skips R0–R3
- R0 deterministic `StoryBrief` from spark (genre/audience may be empty; `do_not_write` from `project.boundaries`)
- R3 provisional `relationship_state`, not CanonWriter
- R4 conflicts/payoffs reference planned `v1c001..N` keys; no chapters yet
- R5 lint; on fail do not persist outlines; each outline cites ≥1 conflict or beat
- `PlanningAborted` keeps earlier rounds

**Step 2: Run tests — expect FAIL**

**Step 3: Implement `run_bible_conversation(...)`. Reuse `PlanningGates`. Skip completed rounds.

**Step 4: Full verify — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(bible): R0–R5 conversation orchestrator"
```

---

### Task 7: CLI

**Files:**
- Modify: `src/novel_agent/cli/main.py`
- Test: `tests/contract/test_story_bible.py`

**Step 1: Write failing CLI tests**

- `novel init` creates project then `run_bible_conversation`
- `novel bible --project-id` resumes
- Non-TTY without `--yes` exits 2
- Existing `novel init --yes` tests still pass

**Step 2: Run tests — expect FAIL**

**Step 3: Wire CLI entrypoints**

**Step 4: Full verify — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(cli): novel init/bible conversation entrypoints"
```

---

### Task 8: graph projector + export

**Files:**
- Create: `src/novel_agent/graph/projector.py`
- Create: `src/novel_agent/graph/export.py`
- Create: `src/novel_agent/graph/__init__.py`
- Modify: `src/novel_agent/cli/main.py`
- Test: `tests/contract/test_graph_projector.py`

**Step 1: Write failing tests** (DTO per spec §7, no LLM)

- Empty after R1; populated after R3
- Nodes: characters, aliases, faction labels from identity/entity_state
- Edges from `relationship_state`; provisional flag; missing evidence kept (labeled, not dropped)
- Alias merge
- Tracks from `CanonDelta.relationship_changes`
- `json | mermaid` export; `novel graph --project-id --format json|mermaid`

**Step 2: Run tests — expect FAIL**

**Step 3: Implement projector + export + CLI**

**Step 4: Full verify — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(graph): canon projector and novel graph export"
```

---

### Task 9: HANDOFF + full verify

**Files:**
- Modify: `HANDOFF.md`

**Step 1:** Update HANDOFF: Story Bible conversation is the planning entry; M3.2 chain is a subroutine.

**Step 2:** Full `uv run pytest -q && uv run ruff check . && uv run mypy src`

**Step 3: Commit**

```bash
git commit -m "docs: HANDOFF for Story Bible conversation"
```

---

## DoD

A user can type a spark, confirm a few rounds (or `--yes` in CI), and get:

- three-level outline
- character summaries
- relationship graph JSON matching `relationship_state`
- conflict list that all pay off in the rolling 5
- 爽点 list with pressure-before-hit
- three-act map plus 黄金三章

Existing chapter factory can consume that bible without a translator.
