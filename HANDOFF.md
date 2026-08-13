# Project Handoff

## 2026-08-13 - M3.2 planning-chain CLI

### Current target

Complete Stage 0 of the local-first AI long-form novel agent described in
`.omc/autopilot/spec.md` and `.omc/plans/autopilot-impl.md`.

The repository is at **M3.2 (planning-chain CLI)**. M0, M1, M2 (including
ContextBuilder / M2.6 real-model smoke evidence), and M3.1-equivalent context
assembly are complete. M3.3 chapter production loop, M3.3b, M3.4, M3.5, and M4
have not started.

### Resume here

```bash
cd "$(git rev-parse --show-toplevel)"
sed -n '1,80p' HANDOFF.md
git status --short
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run novel init "说书人传奇" --brief "说书人发现故事会成真" --yes
```

### Stable architecture and decisions

- Python 3.12 via uv; `agentscope==2.0.5`; SQLModel + Alembic; Typer CLI.
- SQLite is the workflow/business source of truth. Repository classes are the SQL boundary.
- A table-driven FSM owns workflow control, retries, budgets, idempotency, and recovery.
- Cognitive tasks are bounded, tool-free, single-shot calls through `ModelGateway`.
- Stage 0 intentionally uses `asyncio.gather` for parallel reviewers. AgentScope's public
  `Agent` is a ReAct loop and is not used for strict one-shot review/judgment tasks. The
  rationale and future integration boundary are in `docs/verification-report.md`.
- Canon writes go only through `CanonWriter`; agents can propose but cannot commit canon.
- D15 is confirmed: batch chapters may read provisional canon; rejecting an earlier chapter
  must mark dependent later chapters `STALE` and invalidate their provisional deltas.
- D16 is confirmed: Writer/Reviser use scene plaintext blocks plus separate JSON metadata.
- Judge and creative slots must use different model families.
- Stage 0 planning is single-round generate + human confirm. No planning adversarial /
  Concept Judge (that is Stage 1).

### Completed work

- M0: repository baseline, uv project, config, AgentScope/license/Python verification.
- M1: Pydantic schemas, 19 SQLModel tables, Alembic migrations, repositories, FSM,
  node-level idempotency/resume, budget gate, and transactional `CanonWriter`.
- M2: model gateway, mock/real providers, structured and two-part output, cognitive
  runtime contracts, five-reviewer concurrency, blind/anonymized judging, deterministic
  lint, versioned prompts, and bounded M2.6 real-model smoke (12/12 roles).
- M3.1-equivalent: `ContextBuilder` assembles `ChapterContextPackage` with PRD §12.2
  ordering and budget trimming (landed in the M2.6 close-out commit).
- M3.2: planning-chain CLI and orchestration.

Relevant commits, newest first:

```text
36cbc81 feat(M2.6): context 构建器、真实模型 smoke 收尾与 M2 验证证据归档
1b31270 fix: harden M2.6 smoke evidence accounting
67a272f feat: add bounded M2.6 real-model smoke runner
a3852cc feat: add cognitive agent runtime contracts
```

### M3.2 command split

- `novel init TITLE --brief TEXT [--yes] [--select N]`: create a project, store the
  brief on `project.channel_profile`, and run the full planning chain.
- `novel plan --project-id ID [--brief TEXT] [--yes] [--select N]`: resume the chain
  on an existing project. Completed stages (approved kernel / characters / chapters)
  are skipped.
- Human gates: interactive kernel selection + confirm for characters and for the
  volume/unit/rolling-outline bundle. `--yes` auto-selects candidate `--select`
  (1-based, default 1) and confirms every later stage. Non-TTY without `--yes`
  exits 2 so CI cannot hang on prompts.
- Chain implementation: `src/novel_agent/planning/chain.py` calls existing
  `run_kernel_planner` / `run_character_planner` / `run_outline_planner`, then
  persists through `PlanningRepo` only. Mock defaults live in
  `src/novel_agent/planning/mock_fixtures.py`.
- Rolling window: default 5 chapter outlines, each with scene cards. Volume payload
  is assembled from the unit card (no extra LLM call; there is no VolumeOutline schema).

### Fresh validation evidence

Collected on 2026-08-13 (M3.2):

```text
uv run pytest -q       -> 127 passed
uv run ruff check .    -> All checks passed
uv run mypy src        -> Success: no issues found in 50 source files
```

Offline planning-chain contracts (mock only, no network): generate 3 kernels →
select/approve one → persist characters, volume, plot unit, 5 chapter outlines +
scene cards, all queryable via `PlanningRepo`. Abort-before-characters and
`--yes` CLI paths are covered.

M2.6 paid smoke remains archived (not re-run in this milestone):

- Redacted report: `artifacts/verification/g001-minimax-evidence-repair6.json`
- 12 prompt roles passed structured output; actual cost `$0.096965` under `$1.00`.

The local `.env` contains credentials and must never be printed or committed.
`data/novel.db` is local runtime data and must not be committed.

### Next implementation sequence

1. M3.3 单章循环编排: N1→N9 接 FSM(评审并行、Judge、两轮修订上限、HUMAN_REVIEW)。
   mock 下 PASS / REVISE_LOCAL 两轮 / REPLAN / 两轮失败→HUMAN_REVIEW 各一条集成测试;
   另需真实模型单章冒烟(不要求质量达标)。
2. M3.3b `novel edit-outline` YAML 导出/导入, bump outline_ver, 回 N1。
3. M3.4 `novel review-batch` / `novel approve`(canon 提交 + git 检查点)。
4. M3.5 `novel write-batch`(D15 provisional overlay) / `resume` / `export`。
5. M4 回归集、Judge 校准、三章真实模型验收。

### Important paths

- Product/architecture source: `docs/AI_Novel_Agent_PRD_Architecture.md`
- Frozen implementation spec: `.omc/autopilot/spec.md`
- Milestone plan and DoD: `.omc/plans/autopilot-impl.md`
- Prior adversarial review: `.omc/autopilot/review-findings.md`
- Dependency/API verification: `docs/verification-report.md`
- Planning chain: `src/novel_agent/planning/`
- Planning CLI: `src/novel_agent/cli/main.py` (`init` / `plan`)
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
