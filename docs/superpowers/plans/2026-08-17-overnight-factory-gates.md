# Overnight Factory Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a 20-chapter volume write, the chapter factory auto-locks a lockable on-brief draft when Judge/reviewer output is empty, schema-echo, or wrongly REPLAN, without SQL/YAML surgery.

**Architecture:** Keep Writer/Judge/retrieval prompts unchanged. Extend `factory.py` detectors and `loop.py` fallbacks already added in PRs #29–#31. Tests use overnight live strings as fixtures. No paid APIs in pytest.

**Tech Stack:** Python 3.12, uv, pytest, existing `JudgeVerdict` / `DraftCandidate` / `HardGate` schemas.

**Spec:** `docs/superpowers/specs/2026-08-17-overnight-factory-gates-design.md`

## Global Constraints

- Do not rewrite Writer, Judge, or retrieval prompts.
- Ports stay `8765` / `18765`. No Redis. No second runner.
- Leave draft PR #24 alone.
- Never add the substring `笔记` or bare `左眼` to `_HARD_GATE_LEAK_RE`.
- No paid APIs in pytest: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_factory_gates.py tests/workflow/test_chapter_loop.py`
- After every task: that pytest slice green, then `uv run ruff check src/novel_agent/production/factory.py src/novel_agent/production/loop.py tests/unit/test_factory_gates.py`

## File map

Modify:

- `src/novel_agent/production/factory.py` — markers, empty detector, leak regex, `required_names`, sole n=1
- `src/novel_agent/production/loop.py` — pass names; whitelist; n5 parse; PLANNED fails paused run
- `tests/unit/test_factory_gates.py` — overnight fixtures
- `tests/workflow/test_chapter_loop.py` — n5 + resume (only if a small hook can be tested without MiniMax)

Create: none.

---

### Task 1: Empty-packet markers + invented `source_risk`

**Files:**
- Modify: `src/novel_agent/production/factory.py:48-121`
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: existing `JudgeVerdict`
- Produces: `is_empty_packet_verdict(verdict) -> bool` true for overnight v1c012/013/020 wording even when `hard_gate_failures=['source_risk']`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_factory_gates.py`:

```python
def test_empty_packet_with_source_risk_and_overnight_wording() -> None:
    v012 = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["source_risk"],
            "reasoning_summary": "输入内容为空，未检测到任何场景候选，按 source_risk 退回人工审核。",
        }
    )
    assert is_empty_packet_verdict(v012) is True

    v013 = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["source_risk"],
            "reasoning_summary": "未提供实际场景数据进行裁决，因此按 source_risk 退回人工审核。",
        }
    )
    assert is_empty_packet_verdict(v013) is True

    v020 = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "unknown",
            "hard_gate_failures": ["source_risk"],
            "reasoning_summary": "上次输出误将JSON Schema定义本身作为输出内容，缺少必需字段verdict、selected_candidate和reasoning_summary。",
        }
    )
    assert is_empty_packet_verdict(v020) is True

    real = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["canon_conflict"],
            "reasoning_summary": "正史冲突，升级人工",
        }
    )
    assert is_empty_packet_verdict(real) is False
```

Keep `test_empty_packet_verdict_detected_without_hard_gate` as-is.

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest tests/unit/test_factory_gates.py::test_empty_packet_with_source_risk_and_overnight_wording -v`

Expected: FAIL (`v012` is False because `hard_gate_failures` short-circuits).

- [ ] **Step 3: Write minimal implementation**

In `factory.py`:

1. Append to `_EMPTY_PACKET_MARKERS`:

```python
    "输入内容为空",
    "未检测到任何场景",
    "未提供实际场景",
    "未提供实际裁决",
    "JSON Schema",
    "Schema 定义",
    "Schema定义",
    "$defs",
    "缺少必需字段",
    "缺少必需的 verdict",
```

2. Replace `is_empty_packet_verdict`:

```python
_EMPTY_PACKET_SOFT_GATES = frozenset({"source_risk", "info_violation"})


def is_empty_packet_verdict(verdict: JudgeVerdict) -> bool:
    if not is_empty_packet_reason(verdict.reasoning_summary):
        if verdict.hard_gate_failures:
            return False
        if verdict.verdict is not VerdictType.HUMAN_REVIEW:
            return False
        return not verdict.rulings or all(not item.accepted for item in verdict.rulings)
    real_gates = [g for g in verdict.hard_gate_failures if str(g) not in _EMPTY_PACKET_SOFT_GATES]
    if real_gates:
        return False
    return True
```

`str(g)` because `HardGate` is a `StrEnum`; `source_risk` may arrive as string via `model_validate`.

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest tests/unit/test_factory_gates.py -v`

Expected: PASS (including the old empty-packet test).

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/production/factory.py tests/unit/test_factory_gates.py
git commit -m "fix: treat Judge schema-echo plus source_risk as empty packet"
```

---

### Task 2: 左眼花 / 左眼薄雾 / 反噬 leak regex

**Files:**
- Modify: `src/novel_agent/production/factory.py:60-61`
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: `has_hard_gate_leak(text) -> bool`
- Produces: 左眼花 drafts are usable but not lockable

- [ ] **Step 1: Write the failing test**

```python
def test_left_eye_haze_is_usable_but_not_lockable() -> None:
    haze = _long_prose() + "左眼薄雾又压上来，监视器上的脸花成一团。"
    flower = _long_prose() + "左眼花了三回，他还是没喊 cut。"
    backlash = _long_prose() + "偷技法的反噬让他当晚不敢再借。"
    notebook = _long_prose() + "他合上笔记本，把工作笔记收进抽屉。"
    assert is_usable_draft(haze) and is_usable_draft(flower) and is_usable_draft(backlash)
    assert pick_lockable_candidate([_candidate("candidate_1", haze)], []) is None
    assert pick_lockable_candidate([_candidate("candidate_1", flower)], []) is None
    assert pick_lockable_candidate([_candidate("candidate_1", backlash)], []) is None
    assert pick_lockable_candidate([_candidate("candidate_1", notebook)], []) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON_PREFERENCE=managed uv run pytest tests/unit/test_factory_gates.py::test_left_eye_haze_is_usable_but_not_lockable -v`

Expected: FAIL (`haze` currently lockable).

- [ ] **Step 3: Write minimal implementation**

```python
_HARD_GATE_LEAK_RE = re.compile(r"穿越|耳鸣|真名|实习生|左眼花|左眼薄雾|反噬")
```

- [ ] **Step 4: Run `UV_PYTHON_PREFERENCE=managed uv run pytest tests/unit/test_factory_gates.py -v` — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/production/factory.py tests/unit/test_factory_gates.py
git commit -m "fix: treat 左眼花/左眼薄雾/反噬 as hard-gate leaks"
```

---

### Task 3: On-brief required names + sole lockable n=1

**Files:**
- Modify: `src/novel_agent/production/factory.py` (`is_lockable_draft`, `_lockable_candidates`, `pick_lockable_candidate`, `pick_sole_lockable_candidate`)
- Modify: `src/novel_agent/production/loop.py` n6 picks
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: `required_names: list[str] | None`
- Produces: 民国 draft with zero card names is not lockable; sibling with 林朔 is sole-lockable; single on-brief candidate is sole-lockable

- [ ] **Step 1: Write the failing tests**

```python
_NAMES = ["林朔", "柳奕妃", "许静蕾", "樊冰屏", "周洵", "张紫衣"]


def test_wrong_book_prose_not_lockable_when_names_required() -> None:
    republican = (
        "周意坐在窗前读书，陆怀坐在客位上，裴谈把名帖折成两折，撑伞走进雨里。" * 40
    )
    onbrief = _long_prose() + "林朔没喊 cut。柳奕妃把话筒轻轻放回去。"
    assert "林朔" not in republican
    leaked = _candidate("candidate_1", republican)
    clean = _candidate("candidate_2", onbrief)
    assert pick_lockable_candidate([leaked], [], required_names=_NAMES) is None
    picked = pick_sole_lockable_candidate([leaked, clean], [], required_names=_NAMES)
    assert picked is not None and picked.candidate_id == "candidate_2"


def test_sole_lockable_single_onbrief_candidate() -> None:
    clean = _candidate("candidate_1", _long_prose() + "林朔在监视器前坐下。")
    picked = pick_sole_lockable_candidate([clean], [], required_names=["林朔"])
    assert picked is not None and picked.candidate_id == "candidate_1"
```

Change `test_sole_lockable_none_when_both_clean_or_both_junk`: **delete** the line `assert pick_sole_lockable_candidate([clean_b], []) is None`. Keep both-clean → None and both-junk → None.

- [ ] **Step 2: Run tests — expect FAIL** (`required_names` TypeError / republican still lockable / n=1 returns None)

- [ ] **Step 3: Write minimal implementation**

```python
def is_lockable_draft(
    text: str,
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> bool:
    if not is_usable_draft(text):
        return False
    if check_boundaries(text, boundaries):
        return False
    if check_engineering_leak(text):
        return False
    if has_hard_gate_leak(text):
        return False
    names = [n for n in (required_names or []) if n]
    if names and not any(n in (text or "") for n in names):
        return False
    return True


def _lockable_candidates(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> list[DraftCandidate]:
    return [
        draft
        for draft in candidates
        if is_lockable_draft(draft.full_text(), boundaries, required_names)
    ]


def pick_lockable_candidate(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> DraftCandidate | None:
    viable = _lockable_candidates(candidates, boundaries, required_names)
    if not viable:
        return None
    return max(viable, key=lambda item: prose_char_count(item.full_text()))


def pick_sole_lockable_candidate(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> DraftCandidate | None:
    viable = _lockable_candidates(candidates, boundaries, required_names)
    if len(viable) != 1:
        return None
    return viable[0]
```

In `loop.py` `_n6` `fn()` after `package = ctx_factory()`:

```python
        names = [card.name for card in package.characters if card.name]
        ...
            picked = pick_lockable_candidate(candidates, package.boundaries, names)
        ...
            sole = pick_sole_lockable_candidate(candidates, package.boundaries, names)
```

- [ ] **Step 4: Run `UV_PYTHON_PREFERENCE=managed uv run pytest tests/unit/test_factory_gates.py -v` — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/production/factory.py src/novel_agent/production/loop.py tests/unit/test_factory_gates.py
git commit -m "fix: require a character-card name on lockable drafts; allow sole n=1"
```

---

### Task 4: Whitelist character-card names on Judge `content_boundary`

**Files:**
- Modify: `src/novel_agent/production/loop.py` `sanitize_verdict`
- Test: `tests/unit/test_factory_gates.py` (import `sanitize_verdict` from loop) **or** move a tiny helper `drop_allowed_name_boundaries` into `factory.py` and test it there (preferred: keep factory testable without loop fixtures).

**Interfaces:**
- Consumes: `allowed_names: list[str]`
- Produces: `content_boundary` whose claim is only 许静蕾 is dropped; 章子怡 is not

Chosen: add `strip_allowed_name_boundaries(verdict, issues, allowed_names) -> JudgeVerdict` in `factory.py`. `sanitize_verdict` calls it.

- [ ] **Step 1: Write the failing test**

```python
from novel_agent.domain.schemas.base import HardGate, ReviewerRole, RollbackLevel, Severity
from novel_agent.production.factory import strip_allowed_name_boundaries


def test_allowed_variant_name_is_not_content_boundary() -> None:
    issue = ReviewIssue.model_validate(
        {
            "issue_id": "i1",
            "reviewer_role": "red_team",
            "claim": "许静蕾真名",
            "evidence": [{"scene_id": "v1c009_s1", "quote": "许静蕾把杯子转了半圈"}],
            "violated_rule": "禁真名",
            "hard_gate": "content_boundary",
            "severity": "P0",
            "failure_consequence": "违禁",
            "recommended_rollback_level": "chapter",
            "confidence": 0.9,
        }
    )
    verdict = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["content_boundary"],
            "rulings": [{"issue_id": "i1", "accepted": True, "reason": "真名"}],
            "reasoning_summary": "许静蕾是真名，升级人工",
        }
    )
    cleaned = strip_allowed_name_boundaries(
        verdict, [issue], allowed_names=["许静蕾", "林朔"]
    )
    assert HardGate.CONTENT_BOUNDARY not in cleaned.hard_gate_failures

    dirty = JudgeVerdict.model_validate(
        {
            "verdict": "HUMAN_REVIEW",
            "selected_candidate": "candidate_1",
            "hard_gate_failures": ["content_boundary"],
            "reasoning_summary": "出现章子怡真名",
        }
    )
    kept = strip_allowed_name_boundaries(dirty, [], allowed_names=["许静蕾"])
    assert HardGate.CONTENT_BOUNDARY in kept.hard_gate_failures
```

If `ReviewIssue.model_validate` enums need exact values, copy a working `_issue()` helper from `test_schemas.py`.

- [ ] **Step 2: Run test — expect FAIL** (function missing)

- [ ] **Step 3: Implement**

```python
from novel_agent.domain.schemas.base import HardGate

_FORBIDDEN_REAL_NAME_RE = re.compile(r"章子怡|赵薇|周迅|徐静蕾|范冰冰|李冰冰|刘亦菲")


def strip_allowed_name_boundaries(
    verdict: JudgeVerdict,
    issues: list[ReviewIssue],
    allowed_names: list[str] | None = None,
) -> JudgeVerdict:
    allowed = [n for n in (allowed_names or []) if n]
    if not allowed or HardGate.CONTENT_BOUNDARY not in verdict.hard_gate_failures:
        return verdict
    blob = " ".join(
        [verdict.reasoning_summary]
        + [issue.claim for issue in issues if issue.hard_gate == HardGate.CONTENT_BOUNDARY]
        + [r.reason for r in verdict.rulings]
    )
    if _FORBIDDEN_REAL_NAME_RE.search(blob):
        return verdict
    if not any(name in blob for name in allowed):
        return verdict
    gates = [g for g in verdict.hard_gate_failures if g != HardGate.CONTENT_BOUNDARY]
    return verdict.model_copy(update={"hard_gate_failures": gates})
```

Call from `sanitize_verdict` after building `cleaned_gates`, passing `allowed_names`. Change signature:

```python
def sanitize_verdict(
    verdict: JudgeVerdict,
    issues: list[ReviewIssue],
    allowed_names: list[str] | None = None,
) -> JudgeVerdict:
```

n6: `sanitize_verdict(raw, issues, names)`.

If after strip there are no gates and no accepted rulings, existing PASS rewrite in `sanitize_verdict` still applies — run strip **before** that PASS rewrite, on the working `verdict` copy.

- [ ] **Step 4: pytest factory gates PASS**

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/production/factory.py src/novel_agent/production/loop.py tests/unit/test_factory_gates.py
git commit -m "fix: drop content_boundary when Judge flags a character-card name"
```

---

### Task 5: n5 ReviewReport JSON fail does not stick ADVERSARIAL_REVIEW

**Files:**
- Modify: `src/novel_agent/production/loop.py` `_n5` and `_advance`
- Test: `tests/workflow/test_chapter_loop.py` if an existing n5 mock exists; otherwise a focused unit test of the branch by extracting the critical-error decision into `factory.py` is **not** required — add the `_advance` try/except and a loop test only if the file already patches `run_reviewer`. If adding a full loop test is large, the `_n5` change plus this assertion in a new `tests/unit/test_n5_parse.py` that imports and inspects the helper is enough.

Chosen implementation (spec §5.6):

Inside `_n5` gather loop, if `isinstance(result, BaseException)` and `'StructuredOutputError' in type(result).__name__ or 'StructuredOutputError' in str(result)`: treat as `absent`, do **not** set `critical_error`.

At the end: if `not reports` and any critical role is in `absent`: `raise NodeFailed("n5_parallel_review", "StructuredOutputError: ReviewReport 校验失败")`.

In `_advance` ADVERSARIAL_REVIEW branch, wrap `await _n5(...)` like n6:

```python
            try:
                await _n5(...)
            except NodeFailed as exc:
                if "StructuredOutputError" not in str(exc):
                    raise
                transition(planning, project_id, chapter_key, ChapterStatus.HUMAN_REVIEW)
                session.commit()
                return "n5_parallel_review", "ReviewReport 非法,升级人工"
```

- [ ] **Step 1: Write a failing test** in `tests/workflow/test_chapter_loop.py` only if a reviewer mock already exists. Search for `n5_parallel_review` in that file first. If none, add `tests/unit/test_factory_gates.py` skip — then add a tiny helper:

```python
def critical_parse_failure_should_raise(reports: list, absent: list[str], critical: set[str]) -> bool:
    return (not reports) and bool(set(absent) & critical)
```

Test: `reports=[]`, `absent=['continuity']`, critical `{'continuity'}` → True; `reports=[...]` → False.

- [ ] **Step 2: FAIL then implement `_n5` + `_advance`**

- [ ] **Step 3: pytest the touched tests PASS**

- [ ] **Step 4: Commit**

```bash
git add src/novel_agent/production/loop.py tests/unit/test_factory_gates.py tests/workflow/test_chapter_loop.py
git commit -m "fix: n5 ReviewReport JSON fail becomes absent or HUMAN_REVIEW, not stuck ADVERSARIAL_REVIEW"
```

---

### Task 6: Fresh write on PLANNED/NEEDS_REPLAN fails paused/running loop

**Files:**
- Modify: `src/novel_agent/production/loop.py` around `find_resumable_run` (`loop.py:231-250`)
- Test: `tests/workflow/test_chapter_loop.py` or `tests/workflow/test_runner_resume.py` (use whichever already constructs a paused workflow)

**Interfaces:**
- Consumes: chapter.status, resumable run status
- Produces: PLANNED + paused n6 → failed old run + new run

- [ ] **Step 1: Write the failing test**

If `test_runner_resume.py` exists, add:

```python
def test_planned_chapter_does_not_resume_paused_judge(tmp_path, ...existing fixture...):
    # create paused chapter_loop current_node=n6_judge
    # set chapter status PLANNED
    # run_chapter_loop(..., gates=auto)
    # assert old run.status == "failed"
    # assert a newer workflow_run exists
```

Copy fixture style from `test_failed_workflow_not_resumed` in `tests/workflow/test_chapter_loop.py` (line ~366 area). Do not invent a new DB stack.

- [ ] **Step 2: FAIL (paused run is resumed, n3 idempotency reuses old drafts)**

- [ ] **Step 3: Implementation**

Replace the resume block:

```python
    run = ops.find_resumable_run(project_id, "chapter_loop", chapter_key)
    if run is not None and run.status in {"paused", "running"}:
        if chapter.status in {ChapterStatus.PLANNED, ChapterStatus.NEEDS_REPLAN}:
            ops.update_workflow(run.id, status="failed", current_node=run.current_node)
            ops.void_succeeded_nodes_for_chapter(chapter_key)
            reset_to_planned(planning, project_id, chapter_key)
            chapter = planning.get_chapter(project_id, chapter_key)
            run = None
    if run is None:
        last = ops.latest_workflow_for_chapter(project_id, "chapter_loop", chapter_key)
        ...existing failed-path...
        run = ops.create_workflow_run(project_id, "chapter_loop", chapter_key)
```

HUMAN_REVIEW / ADVERSARIAL_REVIEW / JUDGING / DRAFTING still resume.

- [ ] **Step 4: pytest resume tests PASS**

- [ ] **Step 5: Commit**

```bash
git add src/novel_agent/production/loop.py tests/workflow
git commit -m "fix: PLANNED/NEEDS_REPLAN write fails paused loops instead of resuming them"
```

---

## Self-review

1. Spec coverage: empty packet §5.1 → Task 1; leak §5.2 → Task 2; on-brief + sole n=1 §5.3–5.4 → Task 3; whitelist §5.5 → Task 4; n5 §5.6 → Task 5; resume §5.7 → Task 6. Outline sanitizer intentionally has no task.
2. No TBD in steps. Live overnight strings copied.
3. `required_names` / `allowed_names` naming is consistent. `pick_*` gained the third arg; loop n6 updated in Task 3.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-17-overnight-factory-gates.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a cloud agent per task, review between tasks
2. **Inline Execution** — execute tasks in this session using executing-plans

Which approach?
