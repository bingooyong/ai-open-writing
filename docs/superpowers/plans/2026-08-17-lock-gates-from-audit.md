# Lock Gates From Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Factory refuses to auto-lock drafts that repeat five bible misses from locked 《穿回去当导演》 v1c001–005, still locks a sibling that does not, including when Judge PASSes a non-lockable selected draft.

**Architecture:** Keep Writer/Judge/retrieval prompts unchanged. Extend `factory.py` with `LockGates` and detectors; thread `gates` through pick helpers; after n6, veto a non-lockable Judge PASS (sole lockable sibling or HUMAN_REVIEW). Tests use locked-draft live strings as fixtures. No paid APIs in pytest.

**Tech Stack:** Python 3.12, uv, pytest, existing `JudgeVerdict` / `DraftCandidate` / `HardGate` schemas.

**Spec:** `docs/superpowers/specs/2026-08-17-lock-gates-from-audit-design.md`

## Global Constraints

- Do not rewrite Writer, Judge, or retrieval prompts.
- Ports stay `8765` / `18765`. No Redis. No second runner.
- Leave draft PR #24 alone. Do not reopen outline-sanitizer work.
- Never add the substring `笔记` or bare `左眼` to `_HARD_GATE_LEAK_RE`.
- Do not gate `尾音`. Do not gate `我没说`. Do not gate `心跳` / `手凉` / `出汗` / `手还在抖`.
- Do not add `pov_person` or `cast` fields to `ChapterOutline`.
- No paid APIs in pytest: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_factory_gates.py tests/workflow/test_chapter_loop.py`
- After every task: that pytest slice green, then `uv run ruff check src/novel_agent/production/factory.py src/novel_agent/production/loop.py tests/unit/test_factory_gates.py`
- ONE TASK PER PR. Task 1 ships plumbing + POV + Judge PASS veto only. Tasks 2–5 stay documented until their PRs.

## File map

Modify:

- `src/novel_agent/production/factory.py` — `LockGates`, `chapter_index_from_key`, POV detector, `gates` on pick helpers, PASS veto
- `src/novel_agent/production/loop.py` — build `LockGates`; pass into picks; veto non-lockable PASS
- `tests/unit/test_factory_gates.py` — locked-draft POV + PASS-veto fixtures
- `tests/workflow/test_chapter_loop.py` — MockProvider Judge PASS on leaky selected draft

Create:

- `docs/superpowers/specs/2026-08-17-lock-gates-from-audit-design.md`
- `docs/superpowers/plans/2026-08-17-lock-gates-from-audit.md`

---

### Task 1: LockGates plumbing + POV person lock + Judge PASS veto

**Files:**
- Create: `docs/superpowers/specs/2026-08-17-lock-gates-from-audit-design.md`
- Create: `docs/superpowers/plans/2026-08-17-lock-gates-from-audit.md`
- Modify: `src/novel_agent/production/factory.py`
- Modify: `src/novel_agent/production/loop.py` `_n6`
- Test: `tests/unit/test_factory_gates.py`
- Test: `tests/workflow/test_chapter_loop.py`

**Interfaces:**
- Consumes: existing `is_lockable_draft(text, boundaries, required_names=None)`, n6 candidates, `package.outline.pov`
- Produces: `LockGates`, `chapter_index_from_key`, `is_lockable_draft(..., gates=)`, `enforce_lockable_verdict(...)`; POV-person drafts not lockable; Judge PASS on a non-lockable selected draft does not auto-lock

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_factory_gates.py`:

```python
from novel_agent.domain.schemas import VerdictType
from novel_agent.production.factory import (
    LockGates,
    chapter_index_from_key,
    enforce_lockable_verdict,
    is_lockable_draft,
    is_usable_draft,
)

V1C001_OPEN = "场记板上的墨迹没干透，我用拇指抹了一下：第三十二场。"
V1C002_OPEN = "林朔把凉透的茶水搁在椅脚边，手心还攥着杯壁。"


def test_chapter_index_from_key() -> None:
    assert chapter_index_from_key("v1c001") == 1
    assert chapter_index_from_key("v1c013") == 13
    assert chapter_index_from_key("nope") is None


def test_first_person_dominant_is_not_lockable_when_pov_is_name() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    prose = _long_prose() + V1C001_OPEN * 10
    assert is_usable_draft(prose)
    assert is_lockable_draft(prose, [], ["林朔"], gates) is False
    assert pick_lockable_candidate([_candidate("candidate_1", prose)], [], ["林朔"], gates) is None


def test_third_person_linshuo_still_lockable() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    prose = _long_prose() + "林朔盯着监视器。兆薇从化妆间出来。" * 5
    assert is_lockable_draft(prose, [], ["林朔"], gates) is True
    assert pick_lockable_candidate([_candidate("candidate_1", prose)], [], ["林朔"], gates) is not None


def test_pov_gate_skipped_when_gates_omitted() -> None:
    prose = _long_prose() + V1C001_OPEN * 10
    assert is_usable_draft(prose)
    assert pick_lockable_candidate([_candidate("candidate_1", prose)], []) is not None


def test_judge_pass_on_first_person_dominant_does_not_lock_without_sibling() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    leaked = _candidate("candidate_1", _long_prose() + V1C001_OPEN * 10)
    verdict = JudgeVerdict.model_validate(
        {
            "verdict": "PASS",
            "selected_candidate": "candidate_1",
            "reasoning_summary": "PASS",
        }
    )
    out = enforce_lockable_verdict(verdict, [leaked], [], ["林朔"], gates)
    assert out.verdict is VerdictType.HUMAN_REVIEW


def test_judge_pass_on_first_person_picks_third_person_sibling() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    leaked = _candidate("candidate_1", _long_prose() + V1C001_OPEN * 10)
    clean = _candidate(
        "candidate_2",
        _long_prose() + "林朔盯着监视器。兆薇从化妆间出来。" * 5,
    )
    verdict = JudgeVerdict.model_validate(
        {
            "verdict": "PASS",
            "selected_candidate": "candidate_1",
            "reasoning_summary": "PASS",
        }
    )
    out = enforce_lockable_verdict(verdict, [leaked, clean], [], ["林朔"], gates)
    assert out.verdict is VerdictType.PASS
    assert out.selected_candidate == "candidate_2"
```

Add to `tests/workflow/test_chapter_loop.py`:

```python
async def test_judge_pass_on_leaky_selected_draft_locks_clean_sibling(tmp_path) -> None:
    """Live hole: Judge PASS never consulted is_lockable_draft; v1c001 draft 44 locked with 实习生."""
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    leak = "实习生把场记板递过来。"
    mock.register(
        "writer_a",
        lambda req: two_part_text(req, SCENE_1 + leak, SCENE_2, "泄漏A"),
    )
    mock.register(
        "writer_b",
        lambda req: two_part_text(req, SCENE_1, SCENE_2, "干净B"),
    )
    mock.register("judge", lambda _req: verdict_json("PASS"))
    try:
        result = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        rec = ProductionRepo(session).get_draft(result.draft_id)
        assert "实习生" not in rec.content_text
    finally:
        session.close()


async def test_judge_pass_on_only_leaky_draft_stays_human_review(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    leak = "实习生把场记板递过来。"
    mock.register(
        "writer_a",
        lambda req: two_part_text(req, SCENE_1 + leak, SCENE_2, "泄漏A"),
    )
    mock.register(
        "writer_b",
        lambda req: two_part_text(req, SCENE_1 + leak, SCENE_2, "泄漏B"),
    )
    mock.register("judge", lambda _req: verdict_json("PASS"))
    try:
        result = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert result.status is ChapterStatus.HUMAN_REVIEW
        assert result.verdict is VerdictType.HUMAN_REVIEW
        assert "n9_canon_commit" not in _node_names(session, result.workflow_run_id)
    finally:
        session.close()
```

Keep every existing PR #32 test. Do not change their `pick_*` calls (no `gates`).

- [ ] **Step 2: Run tests to verify they fail**

Run:

```
UV_PYTHON_PREFERENCE=managed uv run pytest tests/unit/test_factory_gates.py::test_first_person_dominant_is_not_lockable_when_pov_is_name tests/unit/test_factory_gates.py::test_judge_pass_on_first_person_picks_third_person_sibling tests/workflow/test_chapter_loop.py::test_judge_pass_on_only_leaky_draft_stays_human_review -v
```

Expected: FAIL (ImportError for `LockGates` / `enforce_lockable_verdict`, or the leaky PASS path still `CANON_LOCKED`).

- [ ] **Step 3: Write minimal implementation**

In `factory.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class LockGates:
    required_names: list[str] | None = None
    pov: str = ""
    pov_person: str | None = None
    chapter_index: int | None = None
    card_names: list[str] | None = None
    schedule: list[tuple[int, str]] | None = None
    reveal_forbidden: list[str] | None = None


_CHAPTER_INDEX_RE = re.compile(r"c(\d+)", re.IGNORECASE)
_WO_RE = re.compile(r"我(?!们)")


def chapter_index_from_key(key: str) -> int | None:
    match = _CHAPTER_INDEX_RE.search(key or "")
    if not match:
        return None
    return int(match.group(1))


def _effective_required_names(
    required_names: list[str] | None,
    gates: LockGates | None,
) -> list[str] | None:
    if gates is not None and gates.required_names is not None:
        return gates.required_names
    return required_names


def _resolved_pov_person(gates: LockGates) -> str | None:
    if gates.pov_person in {"first", "third"}:
        return gates.pov_person
    pov = (gates.pov or "").strip()
    if pov in {"我", "第一人称"}:
        return "first"
    if pov:
        return "third"
    return None


def _pov_person_blocks(text: str, gates: LockGates) -> bool:
    person = _resolved_pov_person(gates)
    if person is None:
        return False
    blob = text or ""
    wo = len(_WO_RE.findall(blob))
    pov_n = blob.count(gates.pov) if gates.pov else 0
    total = wo + pov_n
    if total <= 0:
        return False
    share = wo / total
    if person == "third":
        return wo >= 8 and share >= 0.75
    return pov_n >= 8 and share <= 0.25


def is_lockable_draft(
    text: str,
    boundaries: list[str],
    required_names: list[str] | None = None,
    gates: LockGates | None = None,
) -> bool:
    if not is_usable_draft(text):
        return False
    if check_boundaries(text, boundaries):
        return False
    if check_engineering_leak(text):
        return False
    if has_hard_gate_leak(text):
        return False
    names = [n for n in (_effective_required_names(required_names, gates) or []) if n]
    if names and not any(n in (text or "") for n in names):
        return False
    if gates is not None and _pov_person_blocks(text, gates):
        return False
    return True


def _lockable_candidates(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
    gates: LockGates | None = None,
) -> list[DraftCandidate]:
    return [
        draft
        for draft in candidates
        if is_lockable_draft(draft.full_text(), boundaries, required_names, gates)
    ]


def pick_lockable_candidate(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
    gates: LockGates | None = None,
) -> DraftCandidate | None:
    viable = _lockable_candidates(candidates, boundaries, required_names, gates)
    if not viable:
        return None
    return max(viable, key=lambda item: prose_char_count(item.full_text()))


def pick_sole_lockable_candidate(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
    gates: LockGates | None = None,
) -> DraftCandidate | None:
    viable = _lockable_candidates(candidates, boundaries, required_names, gates)
    if len(viable) != 1:
        return None
    return viable[0]


def enforce_lockable_verdict(
    verdict: JudgeVerdict,
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
    gates: LockGates | None = None,
) -> JudgeVerdict:
    selected = next(
        (item for item in candidates if item.candidate_id == verdict.selected_candidate),
        None,
    )
    selected_lockable = selected is not None and is_lockable_draft(
        selected.full_text(), boundaries, required_names, gates
    )
    if verdict.verdict is VerdictType.PASS and selected_lockable:
        return verdict
    sole = pick_sole_lockable_candidate(candidates, boundaries, required_names, gates)
    if sole is not None:
        reason = (
            "Judge PASS 所选稿未过工厂锁门,但仅一稿合规:选用该候选,继续锁定。"
            if verdict.verdict is VerdictType.PASS
            else "Judge 拒绝 PASS,但仅一稿合规且无硬门禁泄漏:选用该候选,继续锁定。"
        )
        return synthesize_pass_verdict(sole, reason=reason)
    if verdict.verdict is VerdictType.PASS:
        return verdict.model_copy(
            update={
                "verdict": VerdictType.HUMAN_REVIEW,
                "reasoning_summary": (
                    f"{verdict.reasoning_summary}（所选稿未过工厂锁门,不自动锁定）"
                ),
            }
        )
    return verdict
```

In `loop.py` `_n6` `fn()`, after `names = ...`:

```python
        gates = LockGates(
            required_names=names,
            pov=package.outline.pov,
            chapter_index=chapter_index_from_key(chapter_key),
        )
```

Replace the empty-packet pick and the non-PASS sole-lockable block:

```python
        if raw is None:
            picked = pick_lockable_candidate(candidates, package.boundaries, names, gates)
            if picked is None:
                raise StructuredOutputError("Judge 空包且无可用合规候选")
            raw = synthesize_pass_verdict(picked)
        verdict = sanitize_verdict(raw, issues, names)
        verdict = enforce_lockable_verdict(
            verdict, candidates, package.boundaries, names, gates
        )
```

Import `LockGates`, `chapter_index_from_key`, `enforce_lockable_verdict`.

Do **not** implement 徐姐 / mechanism-naming / body-cost / unscheduled detectors.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```
UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_factory_gates.py tests/workflow/test_chapter_loop.py
uv run ruff check src/novel_agent/production/factory.py src/novel_agent/production/loop.py tests/unit/test_factory_gates.py
```

Expected: PASS / ruff clean.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-17-lock-gates-from-audit-design.md \
  docs/superpowers/plans/2026-08-17-lock-gates-from-audit.md \
  src/novel_agent/production/factory.py src/novel_agent/production/loop.py \
  tests/unit/test_factory_gates.py tests/workflow/test_chapter_loop.py
git commit -m "fix: POV person lock and veto non-lockable Judge PASS"
```

---

### Task 2: 徐姐-style real-name adjacency + 实习场记

**Files:**
- Modify: `src/novel_agent/production/factory.py` (`is_lockable_draft` when `gates` is set)
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: `LockGates` from Task 1
- Produces: drafts with `实习场记` or 徐姐-adjacent real-name forms are usable but not lockable

- [ ] **Step 1: Write the failing test** (do not start until Task 1 is merged)

```python
def test_intern_clapper_and_xujie_adjacency_not_lockable() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    intern = _long_prose() + "林朔把实习场记的夹板接过来。"
    xujie = _long_prose() + "林朔听见有人喊徐姐，静蕾两个字差点出口。"
    clean = _long_prose() + "林朔盯着监视器。兆薇从化妆间出来。"
    assert is_usable_draft(intern) and is_usable_draft(xujie)
    assert is_lockable_draft(intern, [], ["林朔"], gates) is False
    assert is_lockable_draft(xujie, [], ["林朔"], gates) is False
    assert is_lockable_draft(clean, [], ["林朔"], gates) is True
```

- [ ] **Step 2: FAIL then implement the Task 2 detector only. Do not touch `_HARD_GATE_LEAK_RE` with `笔记` or bare `左眼`.**
- [ ] **Step 3: pytest + ruff PASS**
- [ ] **Step 4: Commit** `fix: refuse 实习场记 and 徐姐-style real-name adjacency`

---

### Task 3: mechanism-naming

**Files:**
- Modify: `src/novel_agent/production/factory.py`
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: `LockGates`
- Produces: `我没解释|没法解释|不能解释自己为什么|他不写笔记|我不写笔记|没有写笔记` not lockable; bare `笔记` and `我没说` still lockable

- [ ] **Step 1: Write the failing test**

```python
def test_mechanism_naming_not_lockable_but_bare_notebook_is() -> None:
    gates = LockGates(pov="林朔", required_names=["林朔"])
    named = _long_prose() + "林朔说我没解释，他不写笔记。"
    notebook = _long_prose() + "林朔合上笔记本，把工作笔记收进抽屉。"
    unsaid = _long_prose() + "林朔我没说今晚加戏。"
    assert is_lockable_draft(named, [], ["林朔"], gates) is False
    assert is_lockable_draft(notebook, [], ["林朔"], gates) is True
    assert is_lockable_draft(unsaid, [], ["林朔"], gates) is True
```

- [ ] **Step 2: FAIL then implement. Never add substring `笔记` to `_HARD_GATE_LEAK_RE`.**
- [ ] **Step 3: pytest + ruff PASS**
- [ ] **Step 4: Commit** `fix: refuse mechanism-naming phrases, not bare 笔记`

---

### Task 4: body-cost in ch1–3 only

**Files:**
- Modify: `src/novel_agent/production/factory.py`
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: `LockGates.chapter_index`
- Produces: `嗡声|眩晕|额角|跳痛|偏头痛|失明|耳侧` not lockable when `chapter_index` in `{1,2,3}`; skip if `None` or `>3`; skip `心跳`/`手凉`/`出汗`/`手还在抖`; do not gate `尾音`

- [ ] **Step 1: Write the failing test**

```python
def test_body_cost_gated_only_in_early_chapters() -> None:
    early = LockGates(pov="林朔", required_names=["林朔"], chapter_index=1)
    late = LockGates(pov="林朔", required_names=["林朔"], chapter_index=4)
    skipped = LockGates(pov="林朔", required_names=["林朔"], chapter_index=None)
    symptom = _long_prose() + "林朔额角跳痛，耳侧嗡声，眩晕得看不清监视器。"
    heartbeat = _long_prose() + "林朔心跳很快，手凉，出汗，手还在抖，尾音发虚。"
    assert is_lockable_draft(symptom, [], ["林朔"], early) is False
    assert is_lockable_draft(symptom, [], ["林朔"], late) is True
    assert is_lockable_draft(symptom, [], ["林朔"], skipped) is True
    assert is_lockable_draft(heartbeat, [], ["林朔"], early) is True
```

- [ ] **Step 2: FAIL then implement. Do not gate `尾音`.**
- [ ] **Step 3: pytest + ruff PASS**
- [ ] **Step 4: Commit** `fix: refuse early-chapter body-cost symptoms`

---

### Task 5: unscheduled character

**Files:**
- Modify: `src/novel_agent/production/factory.py`
- Modify: `src/novel_agent/production/loop.py` to fill `card_names`, `schedule`, `reveal_forbidden`
- Test: `tests/unit/test_factory_gates.py`

**Interfaces:**
- Consumes: `LockGates.schedule` as `list[tuple[int, str]]` (`first_schedule` from volume outline title+core_event+pov, lookahead=1), `reveal_forbidden`
- Produces: 黎冰屏 first at v1c013 appearing in v1c004 is not lockable; 兆薇 in c001 is lockable; `reveal_forbidden` substring wins (许静蕾/周洵登场)

- [ ] **Step 1: Write the failing test**

```python
def test_unscheduled_character_too_early_is_not_lockable() -> None:
    gates = LockGates(
        pov="林朔",
        required_names=["林朔"],
        chapter_index=4,
        card_names=["林朔", "兆薇", "黎冰屏"],
        schedule=[(1, "林朔"), (1, "兆薇"), (13, "黎冰屏")],
        reveal_forbidden=["许静蕾登场", "周洵登场"],
    )
    early = _long_prose() + "林朔看见黎冰屏站在监视器后面。"
    ok = _long_prose() + "林朔盯着监视器。兆薇从化妆间出来。"
    forbidden = _long_prose() + "林朔听见许静蕾登场的通告。"
    assert is_lockable_draft(early, [], ["林朔"], gates) is False
    assert is_lockable_draft(ok, [], ["林朔"], gates) is True
    assert is_lockable_draft(forbidden, [], ["林朔"], gates) is False
```

Do not add `pov_person` or `cast` to `ChapterOutline`. Build schedule in `loop.py` from volume outlines.

- [ ] **Step 2: FAIL then implement**
- [ ] **Step 3: pytest + ruff PASS**
- [ ] **Step 4: Commit** `fix: refuse unscheduled character appearances`

---

## Self-review

1. Spec coverage: plumbing + POV + PASS veto → Task 1; 徐姐 → Task 2; mechanism-naming → Task 3; body-cost → Task 4; unscheduled → Task 5. Outline sanitizer / prompt rewrite have no task.
2. No TBD in Task 1 steps. Live v1c001 opening and `实习生` PASS hole copied.
3. `LockGates` / `gates` / `enforce_lockable_verdict` naming is consistent. `pick_*` gained `gates`; loop `_n6` updated in Task 1.

## Execution handoff

This session executes **Task 1 only**. Do not start Tasks 2–5.
