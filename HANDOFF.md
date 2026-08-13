# Project Handoff

## 2026-08-07 - Stage 0 implementation handoff

### Current target

Complete Stage 0 of the local-first AI long-form novel agent described in
`.omc/autopilot/spec.md` and `.omc/plans/autopilot-impl.md`.

The repository is currently at **M2 (gateway and cognitive-agent layer)**. M0 and M1
are complete. M2 code and offline contracts are implemented, but M2.6 is not complete
because the first paid real-model smoke failed on `character_planner` structured output.
M3 and M4 have not started.

### Resume here

```bash
cd "$(git rev-parse --show-toplevel)"
sed -n '1,260p' HANDOFF.md
git status --short
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
```

Current verified HEAD: `5d078e1` on branch `main`.

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

### Completed work

- M0: repository baseline, uv project, config, AgentScope/license/Python verification.
- M1: Pydantic schemas, 19 SQLModel tables, Alembic migrations, repositories, FSM,
  node-level idempotency/resume, budget gate, and transactional `CanonWriter`.
- M2.1-M2.5 and M2.7: model gateway, mock/real providers, structured and two-part output,
  cognitive runtime contracts, five-reviewer concurrency, blind/anonymized judging,
  deterministic lint, and strict role prompts.
- M2.6 support code: explicit paid-run confirmation, hard USD budget, per-call accounting,
  prompt/version references, redacted evidence report, and no automatic repair calls during
  the bounded smoke.

Relevant commits, newest first:

```text
5d078e1 fix: harden M2.6 smoke evidence accounting
a563cc4 feat: add bounded M2.6 real-model smoke runner
ed0e33a feat: add cognitive agent runtime contracts
6fc08c3 feat(M2.1-M2.3,M2.5,M2.7): model gateway and deterministic checks
c19d2fe feat(M1.4-M1.7): FSM, recovery, budgets, CanonWriter
```

### Fresh validation evidence

Collected on 2026-08-07:

```text
uv run pytest -q       -> 99 passed in 19.23s
uv run ruff check .    -> All checks passed
uv run mypy src        -> Success: no issues found in 44 source files
uv run novel doctor    -> four real Anthropic-compatible MiniMax slots configured locally
```

The local `.env` contains credentials and must never be printed or committed.

### Active blocker: M2.6 paid smoke

Redacted report: `artifacts/verification/g001-minimax-smoke.json` (currently untracked).

Observed facts:

- Status: `failed`; failure kind: `StructuredOutputError`.
- `kernel_planner` passed strict structured validation.
- `character_planner` returned a response but failed structured validation.
- The run stopped immediately after that failure; 11 roles remain untested.
- Two provider calls were persisted; actual cost was `$0.010144` under a `$1.00` cap.
- The report contains no raw prompt, novel text, or credential, but also lacks enough
  redacted parse/validation detail to identify the exact schema mismatch.

Do not repeatedly rerun the full paid smoke without first improving diagnosis. The smallest
safe next change is to persist a redacted `StructuredOutputError` category and Pydantic field
paths (never raw model output), add offline tests for that evidence, then run a bounded
`character_planner`-focused smoke or add resume/role selection so successful roles are not
paid for again. Keep the explicit confirmation and positive `--budget-usd` gates.

The paid command is intentionally not a routine startup command:

```bash
uv run novel smoke-m26 --confirm-real-models --budget-usd <positive-cap> \
  --report artifacts/verification/<name>.json
```

### Next implementation sequence

1. Finish M2.6 real-model role validation and record a passing redacted report.
2. Mark M2 complete only after all 12 prompt roles pass structure checks and all returned
   Chinese evidence spans locate in the generated scene text.
3. Start M3.1 `ContextBuilder` with PRD section 12.2 ordering and budget trimming tests.
4. Implement M3.2 planning CLI, then M3.3 chapter loop, M3.3b outline edit/replan,
   M3.4 human gate, and M3.5 provisional batch/resume/export.
5. Implement M4 regression/calibration suites and the three-chapter Stage 0 acceptance run.

### Important paths

- Product/architecture source: `docs/AI_Novel_Agent_PRD_Architecture.md`
- Frozen implementation spec: `.omc/autopilot/spec.md`
- Milestone plan and DoD: `.omc/plans/autopilot-impl.md`
- Prior adversarial review: `.omc/autopilot/review-findings.md`
- Dependency/API verification: `docs/verification-report.md`
- Runtime agents: `src/novel_agent/runtime/agents.py`
- Runtime boundary: `src/novel_agent/runtime/adapter.py`
- Model gateway: `src/novel_agent/gateway/`
- Paid smoke runner: `src/novel_agent/verification/m26_smoke.py`
- Smoke contracts: `tests/contract/test_m26_smoke.py`
- Prompt contracts: `prompts/`
- Local database: `data/novel.db` (ignored, local runtime data)

### Worktree and runtime files

Before this handoff, the worktree had only untracked runtime/generated paths:

```text
.omc/project-memory.json
.omc/sessions/
artifacts/
state/
```

Do not add these wholesale to Git. Preserve the redacted smoke report until M2.6 diagnosis is
complete. `HANDOFF.md` is the only intentional source-document change from this handoff task.

There is no reliable active autopilot state file to resume from. Treat the frozen plan and
this handoff as the source of execution state.
