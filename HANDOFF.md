# Project Handoff

## 2026-08-13 - Stage 1 slice 1: local writing desk MVP

### Current target

Stage 1 slice 1 of the local-first AI long-form novel agent: a FastAPI + React
writing desk on the **same SQLite** and **same orchestrators** as the CLI.
Stage 0 (Story Bible, chapter loop, batch/export, M4 mock regression) stays on
main and is not rewritten.

Out of this slice: Concept Judge, five-level outline tree editor, Writer B,
channel export templates, `timeline_event` / `source_record` tables, copying
ops120 analyzer source.

### Resume here

```bash
cd "$(git rev-parse --show-toplevel)"
sed -n '1,80p' HANDOFF.md
git status --short
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
cd apps/web && npm install && npm test
uv run novel doctor
uv run novel serve
# 另一个终端:
cd apps/web && npm run dev
```

API: `http://127.0.0.1:8765` (CORS localhost only). Vite: `http://localhost:5173`.

### Stable architecture and decisions

- Python 3.12 via uv; `agentscope==2.0.5`; SQLModel + Alembic; Typer CLI.
- SQLite is the workflow/business source of truth. Repository classes are the SQL boundary.
- A table-driven FSM owns workflow control, retries, budgets, idempotency, and recovery.
- Cognitive tasks are bounded, tool-free, single-shot calls through `ModelGateway`.
- Stage 0 intentionally uses `asyncio.gather` for parallel reviewers. AgentScope's public
  `Agent` is a ReAct loop and is not used for strict one-shot review/judgment tasks. The
  rationale and future integration boundary are in `docs/verification-report.md`.
- Canon writes go only through `CanonWriter`; agents can propose but cannot commit canon.
- **Planning-time relationships are an exception:** R3 writes `relationship_state` with
  `provisional=True` and `source_chapter="planning"` directly via `CanonRepo`. No chapter
  exists yet, so CanonWriter is not called. Later chapter loop still uses CanonWriter
  for committed deltas.
- The relationship graph is a **projection** of `relationship_state` +
  `CanonDelta.relationship_changes`. Never a second extracted graph.
- Conversation memory is last confirmed artifacts, not chat logs. R0→R5 order is mandatory.
- Spark/brief live on `project.spark` / `project.brief`. One-release read fallback from
  `channel_profile["brief"]` then migrate into `brief`. Stop writing `channel_profile`.
- D15 is confirmed: batch chapters may read provisional canon; rejecting an earlier chapter
  must mark dependent later chapters `STALE` and invalidate their provisional deltas.
- D16 is confirmed: Writer/Reviser use scene plaintext blocks plus separate JSON metadata.
- Judge and creative slots must use different model families.
- Stage 0 planning is single-round generate + human confirm. No planning adversarial /
  Concept Judge (that is Stage 1 remainder, not this slice).
- Evidence-less issues are down-ranked in code, still sent to Judge, and stripped as
  blockers after the verdict (`sanitize_verdict`). Two `REVISE_LOCAL` rounds max; a
  further hard-gate / revise verdict upgrades to `HUMAN_REVIEW`. `REPLAN_*` stops at
  `NEEDS_REPLAN` (no auto-replan agent in Stage 0).
- **One truth, two fronts:** FastAPI in `src/novel_agent/api/` reuses conversation /
  rounds, projector, chapter loop, batch, export. Web app in `apps/web/` consumes
  Graph DTO via AntV G6 (reimplemented; not a copy of analyzer GraphView).
- API `POST /projects` with `auto_bible=true` uses `PlanningGates.auto()` (CLI `--yes`).
  Interactive UI uses pending round JSON on `project.bible_pending` plus
  `POST /projects/{id}/bible/rounds/{n}/confirm`.
- CORS allowlist is localhost / 127.0.0.1 / ::1 only. `novel serve` binds 127.0.0.1:8765.

### Completed work

- M0: repository baseline, uv project, config, AgentScope/license/Python verification.
- M1: Pydantic schemas, 19 SQLModel tables, Alembic migrations, repositories, FSM,
  node-level idempotency/resume, budget gate, and transactional `CanonWriter`.
- M2: model gateway, mock/real providers, structured and two-part output, cognitive
  runtime contracts, five-reviewer concurrency, blind/anonymized judging, deterministic
  lint, versioned prompts, and bounded M2.6 real-model smoke (12/12 roles).
- M3.1-equivalent: `ContextBuilder` assembles `ChapterContextPackage` with PRD §12.2
  ordering and budget trimming (landed in the M2.6 close-out commit).
- M3.2: planning-chain CLI and orchestration (`novel plan` still calls it).
- Story Bible: R0–R5 conversation, bible schemas/tables/repo, lint, structure/conflict/payoff
  planners, graph projector/export.
- M3.3: single-chapter N1→N9 loop wired to the existing FSM.
- M3.3b: `novel edit-outline` YAML 导出/导入, bump `outline_ver`, 旧谱系作废, 回 N1。
- M3.4: `novel review-batch` / `novel approve` 人工门禁;批准走 CanonWriter。
- M3.5: `novel write-batch` (D15 overlay + STALE 级联) / `resume` / `export`。
- M4.1: `tests/regression/samples/` R1–R6 微型项目走现有 loop/lint/judge（mock）。
- M4.2: `novel smoke-stage0 --confirm-real-models --budget-usd N`（非默认 CI）。
- M4.3: R5 无证据不阻断、R6 不误杀、Judge 输入匿名化断言。
- M4.4: README + verification-report mock 证据。
- Stage 1 slice 1: FastAPI 写作台 API + React/Vite 墨案 UI + G6 关系全景。

Relevant commits, newest first:

```text
267183d feat(M3.3): 单章循环 N1→N9 接 FSM (#4)
dc465d6 feat: Story Bible from a Spark (R0–R5 conversation + canon graph) (#5)
4c2368d feat(M3.2): 规划链 CLI (init/plan) 与 mock 入库契约 (#2)
36cbc81 feat(M2.6): context 构建器、真实模型 smoke 收尾与 M2 验证证据归档
```

### Story Bible command split

- `novel init TITLE --brief TEXT [--yes] [--select N]`: create a project, persist
  spark/brief on project columns, run R0–R5 conversation.
- `novel bible --project-id ID [--brief TEXT] [--yes] [--select N]`: resume conversation.
  Completed rounds (R0–R5) are skipped.
- `novel plan --project-id ID`: M3.2 chain subroutine (kernel → characters → rolling outlines).
- `novel graph --project-id ID --format json|mermaid`: canon-native graph projection. No LLM.
- Human gates: interactive kernel selection + confirm per round. `--yes` auto-selects
  candidate `--select` (1-based, default 1) and confirms every later stage. Non-TTY
  without `--yes` exits 2 so CI cannot hang on prompts.
- Conversation: `src/novel_agent/planning/conversation.py`. M3.2 chain stays in
  `src/novel_agent/planning/chain.py` and is not a god object.
- R3 relationships: provisional `relationship_state` rows, not CanonWriter.
- Graph: `src/novel_agent/graph/projector.py` reads canon only.

### M3.3 chapter loop

- Programmatic entry: `run_chapter_loop` in `src/novel_agent/production/loop.py`.
  Advances chapter status via `transition()`, executes nodes via `run_node` /
  `run_node_async`, and calls existing `ContextBuilder`, runtime agents, lint,
  and `CanonWriter`.
- Node map: N1 outline guard → N2 context → N3 Writer A (D16 two-part) → N4 lint
  → N5 parallel reviewers (per-reviewer NodeRun snapshots; Continuity/RedTeam
  required) → N6 Judge (blinded + anonymized + down-rank sanitize) → N7 Reviser
  (max 2 rounds, then back to N4) → N8 human gate (PASS only) → N9 Canon Curator
  + `CanonWriter.finalize`.
- CLI: `novel write-chapter --project-id ID --chapter-key KEY [--yes]`.
  `--yes` auto-approves a PASS verdict and commits canon. Without `--yes`, the
  automated N1–N7 path still runs; N8 waits (`HUMAN_REVIEW`) so non-TTY CI
  does not hang.
- Paid smoke: `novel smoke-chapter --confirm-real-models --budget-usd N`.
  Default refuses (same spirit as `smoke-m26`). Not part of the default pytest
  suite; do not run it unless you intend to spend. Mock merge gate is the four
  integration paths in `tests/workflow/test_chapter_loop.py`.

### M3.3b edit-outline

- `novel edit-outline <chapter> --project-id ID` (or `--chapter-key`).
- `--out path.yaml` exports chapter outline + scene cards (non-TTY OK).
- `--from-file path.yaml --yes` imports after human edit, validates
  ChapterOutline/SceneCard, bumps `outline_ver`, voids old draft lineage,
  resets `revision_round`, returns the chapter to `PLANNED` (N1).
- Non-TTY without `--from-file`/`--out`/`--yes` exits 2.
- After a `REPLAN_*` verdict (`NEEDS_REPLAN`), edit-outline then
  `write-chapter` continues from N1 on a new lineage.

### M3.4 human gate

- `novel review-batch --project-id ID [--chapter-key KEY] [--yes]`: list
  `HUMAN_REVIEW` chapters (draft + issues + verdict). `--yes` auto-approves
  PASS chapters (same spirit as `write-chapter --yes`).
- `--reject --chapter-key KEY --yes`: 退回 → `NEEDS_REPLAN` (then edit-outline);
  D15 cascade marks later STALEABLE chapters `STALE` and discards their
  provisional deltas.
- `--lock-range TEXT --chapter-key KEY --yes`: write `locked_ranges` on the
  latest draft (paragraph rewrite marks).
- `novel approve --project-id ID --chapter-key KEY --yes`: N8 approval + N9
  CanonWriter commit → `CANON_LOCKED`, canon rows, git checkpoint when
  `git_root` is provided to CanonWriter.
- Non-TTY without `--yes` exits 2. `write-chapter --yes` still auto-passes N8.

### M3.5 batch + resume + export

- `novel write-batch --project-id ID [--chapters 3] [--yes]`: 3–5 chapters
  sequential. Later chapters read provisional canon overlay (`include_provisional`).
  Without `--yes`, each PASS chapter stops at `HUMAN_REVIEW` and stages overlay
  via `CanonWriter.stage_provisional`. With `--yes`, each chapter auto-approves
  to `CANON_LOCKED`.
- Rejecting chapter k cascades: chapters k+1..n that are STALEABLE become
  `STALE`; their drafts and provisional deltas are invalidated.
- `novel resume --project-id ID [--chapter-key KEY] [--yes]`: resume from last
  SUCCESS node (FSM idempotency). Omitting `--chapter-key` resumes unfinished
  chapters in order.
- `novel export --project-id ID --format txt|md [--out path]`: Stage 0 min
  export of drafted/approved chapter text.
- Mock DoD: 3-chapter batch; interrupt/resume does not rerun N3; reject ch1 →
  ch2/ch3 STALE; export files contain chapter text.

### Fresh validation evidence

Collected on 2026-08-13 after Stage 1 slice 1 writing desk:

```text
uv run pytest -q                 -> 203 passed
uv run pytest tests/regression -q -> 17 passed
uv run ruff check .              -> All checks passed
uv run mypy src                  -> Success: no issues found in 73 source files
cd apps/web && npm test          -> 4 passed (DTO→G6 mapping)
```

M4.1 mock regression (existing loop/lint/judge, no network):

| ID | Implant | Result |
|---|---|---|
| R1 | dead character returns | Judge `REPLAN_SCENE`, rollback=`scene_card` |
| R2 | POV knows forbidden name | Judge `REPLAN_SCENE`, rollback=`scene_card` |
| R3 | result without setup | Judge `REPLAN_CHAPTER`, rollback=`chapter_outline` |
| R4 | JSON leftover in prose | N4 lint intercept; reviewers/Judge not called |
| R5 | evidenceless P0 opinion | code down-rank; Judge block stripped to PASS |
| R6 | clean sample | PASS / `CANON_LOCKED` (false-positive control) |

M4.3: Judge input (`system`+`user`) has no agent/model ids (`writer_a`,
`reviewer_role`, `mock-model`, `DEFAULT_FORBIDDEN`). R5 downweighted issues are
not accepted blockers. R6 is not false-killed.

M4.2 paid three-chapter smoke is **not** in CI. Slot missing / mock → skip with
an explicit refuse. To run deliberately:

```bash
uv run novel smoke-stage0 --confirm-real-models --budget-usd 10.00
```

Requires real four-slot config (judge family ≠ creative) and will spend money.
The report checklist is Spec §1.3 five exit conditions; quality of prose is not
the bar. Offline pytest covers the refuse path, mock-slot skip, and a redacted
checklist written via an injected provider seam (no paid APIs).

Offline Story Bible contracts (mock only, no network): spark → R0 brief → kernel →
structure map → characters + provisional relations → conflicts/爽点 on planned
`v1c001..N` → rolling 5 outlines that cite conflicts/beats. Abort R3 keeps kernel.
Resume after R3 skips R0–R3. Graph empty after R1, populated after R3; alias merge;
missing evidence labeled not dropped.

Offline chapter-loop contracts (mock only, no network): planning-chain fixture
(`run_planning_chain`) or Story Bible `novel init --yes`, then one chapter
through N1→N9.

- PASS → auto-approve → `CANON_LOCKED` (parallel 5 reviewers, downweighted
  issues still reach Judge and are not treated as blockers)
- `REVISE_LOCAL` twice then PASS (revision_round=2, two N7 nodes)
- `REPLAN_CHAPTER` → `NEEDS_REPLAN` (no reviser, no canon commit)
- two-round hard-gate / revise failure → `HUMAN_REVIEW` (no third revise, no N9)

M2.6 paid smoke remains archived (not re-run in this milestone):

- Redacted report: `artifacts/verification/g001-minimax-evidence-repair6.json`
- 12 prompt roles passed structured output; actual cost `$0.096965` under `$1.00`.

M3.3 paid single-chapter smoke is **not** in CI. To run it deliberately:

```bash
uv run novel smoke-chapter --confirm-real-models --budget-usd 1.00
```

Requires real four-slot config (judge family ≠ creative) and will spend money.
Quality is not a pass criterion; the command only needs to complete a chapter
and write a redacted report under `artifacts/verification/`.

The local `.env` contains credentials and must never be printed or committed.
`data/novel.db` is local runtime data and must not be committed.

### Next implementation sequence

1. Optional paid M4.2: `novel smoke-stage0 --confirm-real-models --budget-usd N`
   with real four-slot config; archive the redacted report.
2. Stage 1 remainder: outline tree editor, batch review UI, Concept Judge /
   planning adversarial, Writer B, channel export templates.

### Important paths

- Product/architecture source: `docs/AI_Novel_Agent_PRD_Architecture.md`
- Frozen implementation spec: `.omc/autopilot/spec.md`
- Milestone plan and DoD: `.omc/plans/autopilot-impl.md`
- Story Bible design: `docs/superpowers/specs/2026-08-13-story-bible-from-spark-design.md`
- Story Bible plan: `docs/superpowers/plans/2026-08-13-story-bible-from-spark.md`
- Prior adversarial review: `.omc/autopilot/review-findings.md`
- Dependency/API verification: `docs/verification-report.md`
- Story Bible conversation: `src/novel_agent/planning/conversation.py`
- M3.2 chain (subroutine): `src/novel_agent/planning/chain.py`
- Chapter loop: `src/novel_agent/production/loop.py`
- Outline edit: `src/novel_agent/production/outline.py`
- Human gate: `src/novel_agent/production/review.py`
- Batch / D15 cascade: `src/novel_agent/production/batch.py`
- Export: `src/novel_agent/production/export.py`
- CLI: `src/novel_agent/cli/main.py`
  (`init` / `bible` / `plan` / `graph` / `write-chapter` / `smoke-chapter` /
  `edit-outline` / `review-batch` / `approve` / `write-batch` / `resume` /
  `export` / `smoke-stage0` / `serve` / `doctor`)
- Writing desk API: `src/novel_agent/api/` (`create_app`, routes, CORS)
- Bible round generate/confirm: `src/novel_agent/planning/rounds.py`
- Web desk: `apps/web/` (Vite + React + AntV G6)
- Graph DTO→G6 map: `apps/web/src/graph/mapGraphDto.ts`
- API contracts: `tests/contract/test_writing_desk_api.py`
- Bible contracts: `tests/contract/test_story_bible.py`
- Graph contracts: `tests/contract/test_graph_projector.py`
- Chapter-loop contracts: `tests/workflow/test_chapter_loop.py`
- Edit-outline contracts: `tests/workflow/test_edit_outline.py`
- Human-gate contracts: `tests/workflow/test_human_gate.py`
- Batch/export contracts: `tests/workflow/test_batch_export.py`
- Regression samples: `tests/regression/samples/` (R1–R6)
- Regression contracts: `tests/regression/test_samples.py`
- Judge calibration: `tests/regression/test_judge_calibration.py`
- Stage 0 smoke (gated): `src/novel_agent/verification/stage0_smoke.py`
- Planning contracts: `tests/contract/test_planning_chain.py`
- Runtime agents: `src/novel_agent/runtime/agents.py`
- Runtime boundary: `src/novel_agent/runtime/adapter.py`
- Model gateway: `src/novel_agent/gateway/`
- Context builder: `src/novel_agent/context/context_builder.py`
- Prompt contracts: `prompts/`
- Local database: `data/novel.db` (ignored, local runtime data)

### Worktree and runtime files

Do not add these wholesale to Git:

```text
.omc/project-memory.json
.omc/sessions/
artifacts/   (except already-tracked redacted M2.6 evidence)
state/
data/
.env
```

There is an unrelated open Dependabot PR (`cryptography` bump); leave it alone.
