# Story Bible from a Spark — Design Spec

- Date: 2026-08-13
- Status: approved 2026-08-13
- Repo: `bingooyong/ai-open-writing`
- Upstream: `docs/AI_Novel_Agent_PRD_Architecture.md` (V2.2), `.omc/autopilot/spec.md` v1.0, `.omc/plans/autopilot-impl.md` v1.0
- External reference (ideas only, MIT, do not copy files): [ops120/ai-novel-screenplay-analyzer](https://github.com/ops120/ai-novel-screenplay-analyzer)

## 1. North star

The user gives a spark (a sentence, a genre, a scene, a "what if"). After several rounds of conversation with the agent, the system must produce a **confirmed Story Bible** that a later production loop can write from — eventually at million-word scale.

A confirmed Story Bible always contains:

1. Novel outline at three levels (book / volume / chapter)
2. Character summaries (not just names)
3. Character relationship graph (current state + how it changes)
4. Conflict system (who wants what, who blocks whom, what it costs)
5. Payoff cadence (爽点: when the reader gets a hit, after what pressure)
6. Structure map (three-act on the book; 黄金三章 on the opening)

Million-word autonomous generation is the **destination**, not this spec's implementation. This spec defines the Story Bible that makes that destination possible without a second source of truth.

## 2. Why this is a sub-project, not the whole product

The existing Stage 0 plan already builds a production factory:

| Layer | Already in repo | Gap vs north star |
|---|---|---|
| Kernel, characters, volumes, units, rolling 5 chapter outlines | M0–M3.2 | Single-round CLI, not a conversation |
| Relationship / entity / thread tables | M1 | No graph, no 爽点 object, no explicit three-act map |
| Chapter loop N1→N9 | M3.3 in flight | Writes one chapter from an outline, does not invent the bible |
| Batch / human gate / export | M3.4–M3.5 planned | Needed later for volume-scale writing |
| Web writing desk | Stage 1 in PRD | Needed for graph + conversation UI |

Independent pieces, build order:

1. **This spec — Story Bible from a spark** (conversation + artifacts + graph projection)
2. **Chapter factory** (existing M3.3→M3.5; keep going, do not replace)
3. **Volume factory** (rolling outlines, spoiler visibility, resume across hundreds of chapters)
4. **Stage 1 workbench UI** (conversation, graph, inspector, timeline)

This spec is only (1), with interfaces that (2)–(4) can consume. Do not merge the analyzer's "paste a finished novel and extract a graph" pipeline into the writing agent. That is a different product (analysis of existing text). We write the book; the graph is a view of **our** canon.

## 3. Approaches considered

### A. Canon-native Story Bible (chosen)

Conversation writes the same tables the production loop already trusts: kernel, characters, `relationship_state`, plot units, chapter outlines. Graph / timeline / inspector are **projections**. Analyzer contributes UX patterns (G6 graph, chapter-range filter, alias merge, evidence-or-explicit-gap), not a second database.

- Quality: one truth, no drift between "the graph" and "what the writer used"
- Million-word: later chapters query canon, they do not re-extract the book from prose

### B. Sidecar extractor (rejected)

Run the analyzer on generated chapters to build a graph. Two truths. Graph will disagree with `relationship_state` within a dozen chapters.

### C. Copy the analyzer app wholesale (rejected)

Mature UI, wrong job. It analyzes finished text; we need a bible that **constrains** text that does not exist yet. Also Stage 0 is CLI-first; a bolted-on second FastAPI app splits the product.

## 4. Craft rules this bible must encode

Absorbed as executable constraints, not as essays in prompts:

**Three-level outline (网文工程化 / 防烂尾)**

- Book spine: one core contradiction + protagonist growth + promised ending
- Volume: 3–5 万字-scale arc with a stage goal and a climax
- Chapter: one reason to exist — goal, obstacle, end-state change, exit hook

Map onto existing objects: `StoryKernel` = book spine, `VolumeRecord` + `PlotUnitCard` = volume/unit, `ChapterOutline` = chapter. Do not invent a parallel outline tree.

**Three-act on the book**

- Act I Setup (~25%): status quo, inciting incident, commitment
- Act II Confrontation (~50%): midpoint reversal, all-is-lost
- Act III Resolution (~25%): climax pays the opening promise

Store as a `StructureMap` attached to the kernel, with each beat pointing at a volume_id or chapter_key. Volumes are the act containers at million-word scale (a million-word book is many volumes; each volume still has its own three-act miniature).

**黄金三章 (opening contract)**

Chapter 1: protagonist + genre promise + live problem (not lore dump)
Chapter 2: pressure/cost escalates; long-term 爽点 direction visible
Chapter 3: small closed loop (win/loss/reversal) + a new question

The Stage 0 "three coherent chapters" exit condition is this contract, made checkable.

**Conflict system**

Conflicts are typed and reusable: interest, value, emotion, identity, time (time-pressure). A conflict that does not change a relationship or the main plot is rejected at bible confirmation. Each conflict names parties, stake, current temperature, and the chapter/unit where it must escalate or pay off.

**爽点 cadence**

A 爽点 is a planned reader hit with a required preceding pressure (压抑). Defaults:

- every chapter: at least one micro-payoff or hook (may be information, not punching)
- every 3–5 chapters: a named small 爽点
- volume open and close: a large 爽点
- never stack 爽点 without a pressure beat (lint, not a suggestion)

Store as `PayoffBeat` rows linked to chapter_key or unit_id. Chapter outlines must reference the beat they serve.

**Snowflake / conversation**

The user conversation is the snowflake, in the same order as §6: sentence → kernel candidates → structure map → characters and relations → conflicts and 爽点 → rolling chapter cards. Each round **writes durable objects** and asks for confirmation. Chat logs are not the bible.

**Evidence discipline (from the analyzer)**

Graph edges and inspector claims that lack `evidence` render as "暂无可追溯证据". They cannot become Judge blockers. Never invent a relationship because the layout looks sparse.

**Identity / 异名同人 (from the analyzer)**

Long-form models invent extra names. Alias → canonical `character_id` is a first-class canon rule. The graph shows alias nodes as dashed links; merged edges add occurrence and keep both labels. Deleting a mapping does not rewrite history; it changes projection.

## 5. Architecture

```
                    ┌─────────────────────────────┐
  user spark        │ Conversational Planner      │
  + confirmations   │ (multi-round, tool-free     │
                    │  LLM turns + explicit gates)│
                    └─────────────┬───────────────┘
                                  │ writes via PlanningRepo
                                  │ + CanonWriter (identity/relations)
                    ┌─────────────▼───────────────┐
                    │ Story Bible (SQLite)        │
                    │ kernel, characters,         │
                    │ structure_map, conflicts,   │
                    │ payoff_beats, aliases,      │
                    │ relationship_state,         │
                    │ volumes/units/outlines      │
                    └─────────────┬───────────────┘
           ┌──────────────────────┼──────────────────────┐
           ▼                      ▼                      ▼
   GraphProjector          Chapter factory           Stage 1 UI
   (nodes/edges/tracks     (existing FSM N1–N9,      (G6 + inspector
    from canon only)        consumes bible)           + timeline + chat)
```

Rules:

- SQLite remains the only workflow source of truth.
- Repositories remain the only SQL boundary.
- Cognitive turns stay bounded, tool-free, single-shot through `ModelGateway` (same as today). The "conversation" is **our** loop: show artifact → user edits or says "next" → another single-shot call. Do not put the bible inside an unbounded chat context.
- Canon writes still go only through `CanonWriter`. The planner may **propose** relationship changes; confirmation commits them.
- Stage 0 ships CLI conversation (`novel init` becomes multi-round, plus `novel bible` to resume). Stage 1 ships the same loop over HTTP. One orchestrator, two fronts.

### 5.1 New modules (small, one job each)

| Unit | Does | Used via | Depends on |
|---|---|---|---|
| `planning/conversation.py` | Session of rounds, each round = generate-or-revise one artifact class | CLI / later API | `planning/chain.py`, gates |
| `domain/schemas/structure.py` | `StructureMap`, `Conflict`, `PayoffBeat`, `IdentityAlias` | planners, projector, lint | existing VersionedSchema |
| `domain/repos/bible.py` | CRUD for the new tables | conversation, projector | SQLModel session |
| `graph/projector.py` | Canon → nodes/edges/tracks/insights | CLI export, tests, later UI | PlanningRepo, CanonRepo, aliases |
| `graph/export.py` | JSON + mermaid + optional GraphML | `novel graph` | projector |
| `lint/bible.py` | 黄金三章, 爽点 spacing, orphan conflicts, missing evidence | confirmation gate | bible repo |

Do not grow `planning/chain.py` into a god object. Today's chain becomes the **first pass generator** that conversation can call per stage.

### 5.2 Data additions

All additive. Existing M3.2 rows stay valid.

**`structure_map`** (1 per project, versioned)

- `template`: `three_act` (required) plus optional `golden_three`
- beats: `inciting_incident`, `commitment`, `midpoint`, `all_is_lost`, `climax`, `resolution` each with `{summary, volume_id?, chapter_key?}`
- `golden_three`: chapters 1–3 each with `{promise, escalation, payoff_or_hook}`

**`conflict`**

- `conflict_id`, `kind` (interest/value/emotion/identity/time), `parties[]`, `stake`, `temperature` (setup/rising/peak/paid), `must_affect` (plot|relationship|both), `payoff_chapter_key?`

**`payoff_beat`**

- `beat_id`, `scale` (micro/small/large), `kind` (face-slap, reveal, bond, power, reversal, …), `pressure_before` (required text), `hit` (required text), `chapter_key` or `unit_id`, `order_index`

**`identity_alias`**

- `canonical_character_id`, `alias`, unique per project. Projection-only; raw planner output is stored untouched.

**`relationship_state`** (already exists)

- Graph edges = current rows
- Timeline tracks = `CanonDelta.relationship_changes` history
- `provisional` flag (D15) must render as a dashed/amber edge, never mixed silently with committed canon

Factions: if a character `identity` or entity_state has a sect/force, projector emits a faction node. Do not add a faction table until a real force has state beyond a label.

Brief storage: stop stuffing the spark into `channel_profile`. Add `project.spark` / `project.brief` columns (or a `bible_meta` JSON column). This is a bugfix included in this spec.

## 6. Conversation protocol

Turns are numbered. The agent never skips a gate.

| Round | Agent produces | User can | Exit |
|---|---|---|---|
| R0 Spark | normalize spark into genre, audience, hard no-gos | edit | `StoryBrief` |
| R1 Kernel | 3 kernel candidates (existing planner) | pick 1 or "again" | approved kernel |
| R2 Structure | StructureMap + 黄金三章 | edit beats | confirmed map |
| R3 People | character cards + initial relationship_state proposals | edit / merge names | committed people + relations |
| R4 Engine | Conflict[] + PayoffBeat[] assigned to planned chapter_key / unit_id slots (not yet persisted) | drop weak conflicts | confirmed engine |
| R5 Spine | volume + units + rolling 5 chapter outlines that **cite** those conflicts and 爽点 | edit | same as today's M3.2 persist |

Resume: `novel bible --project-id N` starts at the first incomplete round. `--yes` auto-accepts (CI). Non-TTY without `--yes` exits 2 (same as M3.2).

Conversation memory for the model is **the last confirmed artifacts**, not the chat transcript. That is how this survives million-word scale.

## 7. Relationship graph (what we absorb)

From the analyzer, reimplement against our schemas:

- AntV G6 panorama: character nodes, faction nodes, relationship edges labeled with `state`
- Filters: chapter range (edges whose `source_chapter` in range), occurrence / temperature, "preview vs all"
- Hot edges: temperature peak, or multiple `relationship_changes`
- Alias nodes: gray, dashed, merge edges
- Character inspector: degree, turning-point count from `relationship_changes`, evidence quotes from canon, otherwise "暂无可追溯证据"
- Relationship tracks: one track per unordered pair `(party_a, party_b)` across chapter_key

Stage 0 delivery of the graph:

- `novel graph --project-id N --format json|mermaid` prints the projection
- JSON is the contract the Stage 1 G6 view must consume unchanged

Stage 1 (out of this spec's code, in scope for the contract): React G6 view reading that JSON. Do not copy `GraphView.jsx`; reimplement to our DTO.

Graph DTO (stable):

```json
{
  "project_id": 1,
  "canon_version": "…",
  "nodes": [{"id": "ch_su", "label": "苏某", "kind": "character|faction|alias", "alias_of": null}],
  "edges": [{"source": "ch_su", "target": "ch_li", "label": "师徒", "state": "strained", "evidence": "…", "source_chapter": "v1c003", "provisional": false, "occurrence": 2}],
  "tracks": [{"parties": ["ch_su", "ch_li"], "beats": [{"chapter_key": "v1c001", "from_state": "strangers", "to_state": "allies", "evidence": "…"}]}]
}
```

Empty graph after R1 is valid. Graph becomes interesting after R3. Tests must cover both.

## 8. Error handling

- Planner structured-output failure: existing gateway repair-once, then fail the round, keep prior confirmed artifacts.
- User rejects a round: abort that round only (`PlanningAborted` already exists).
- Lint failure at R5: do not persist outlines. Print the violated rules (missing 黄金三章 hit, three consecutive large 爽点 with empty `pressure_before`, conflict with no payoff chapter, relationship change without evidence).
- Alias cycle (A→B→A): reject the mapping.
- Graph projection never calls an LLM.

## 9. Testing (merge gate)

Mock only. No paid APIs.

1. Conversation `--yes` from a spark persists kernel, structure map, characters, conflicts, payoff beats, 5 outlines; each outline cites at least one conflict or 爽点.
2. 黄金三章 lint: a bible whose chapter 1 is lore-only fails; a bible that follows the contract passes.
3. 爽点 spacing lint: three consecutive large beats with empty `pressure_before` fails.
4. Graph projector: fixture canon → nodes/edges; alias merge; provisional edges marked; missing evidence labeled, not dropped.
5. Resume: kill after R3, `novel bible --yes` skips R0–R3, continues R4.
6. Existing M3.2 tests still pass (chain remains callable).

Real-model conversational smoke is optional, same gates as `smoke-m26` (explicit confirm + USD cap). Not CI.

## 10. What this spec will not do

- Paste-in existing novels and extract a graph (analyzer's job)
- Adaptation cost estimation
- A second task engine (we already have FSM + node leases)
- Million-word production in this milestone (that is volume factory + M3.5 batch)
- Replacing Judge / reviewers / CanonWriter
- Unbounded chat that keeps the whole book in context

## 11. Success criteria (this sub-project)

A user can type a spark, confirm a few rounds (or `--yes` in CI), and get:

- a three-level outline
- character summaries
- a relationship graph JSON that matches `relationship_state`
- a conflict list that all pay off somewhere in the rolling 5
- a 爽点 list with pressure-before-hit
- a three-act map plus 黄金三章 notes

and the existing chapter factory can consume that bible without a translator.

## 12. Implementation notes for the next plan

- Python 3.11+, uv, ruff, pytest, mypy as today
- Additive Alembic migration for new tables + `project.brief`
- Reuse `run_kernel_planner` / `run_character_planner` / `run_outline_planner`
- Add planners only for StructureMap, Conflict, PayoffBeat
- Prompts live under `prompts/` with YAML frontmatter and schema refs
- Analyzer is inspiration; new files, new DTO, no copied JSX/Python
