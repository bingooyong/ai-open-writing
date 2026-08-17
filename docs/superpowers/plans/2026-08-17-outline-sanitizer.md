# Outline Sanitizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and import chapter outlines without injecting 反噬/耳鸣/左眼花 into Writer context, and without accepting invented `b1_救场立身份` citation ids.

**Architecture:** Planner/lint only. `sanitize_outline` strips leak items; `lint_outline_citations` checks membership against bible payoff/conflict ids. Hook R5, plan-more inherit, and `apply_outline_edit`. Do not touch `factory.py`.

**Tech Stack:** Python 3.12, uv, pytest, existing `ChapterOutline` / `BibleRepo` / `LintFinding`.

**Spec:** `docs/superpowers/specs/2026-08-17-outline-sanitizer-design.md`

## Global Constraints

- Do not rewrite Writer, Judge, retrieval, or outline_planner prompts.
- Do not edit `src/novel_agent/production/factory.py` or `loop.py` gates.
- Ports stay `8765` / `18765`. No Redis. Leave draft PR #24 alone.
- Do not commit `data/novel.db` or `.env`.
- Never substring-nuke `笔记` or bare `左眼`. Never strip `穿越` / `穿越身份`.
- No paid APIs in pytest: `UV_PYTHON_PREFERENCE=managed uv run pytest -q tests/unit/test_outline_sanitizer.py tests/workflow/test_edit_outline.py tests/contract/test_story_bible.py tests/unit/test_factory_gates.py`
- After every task: that pytest slice green, then `uv run ruff check` on touched files.
- `cited_beat_ids` membership is `PayoffBeat.beat_id`, not StructureMap.

## File map

Create:

- `tests/unit/test_outline_sanitizer.py`

Modify:

- `src/novel_agent/lint/bible.py`
- `src/novel_agent/production/outline.py`
- `src/novel_agent/planning/volume.py`
- `src/novel_agent/planning/conversation.py`
- `tests/workflow/test_edit_outline.py`
- `tests/contract/test_story_bible.py` (only if a small membership case fits existing fixtures)

---

### Task 1: `sanitize_outline` token strip

**Files:**
- Create: `tests/unit/test_outline_sanitizer.py`
- Modify: `src/novel_agent/lint/bible.py`

**Interfaces:**
- Consumes: `ChapterOutline`
- Produces: copy with leak items removed from `reveal_forbidden` and cited-id lists

- [ ] **Step 1: Write the failing test**

Overnight strings verbatim. Build a minimal `ChapterOutline` the same way `test_edit_outline.py` / schema tests do (copy required fields from a fixture helper if one exists).

```python
def test_sanitize_outline_strips_overnight_forbidden_items() -> None:
    outline = _outline(
        reveal_forbidden=[
            "穿越身份",
            "默写分镜笔记的存在",
            "反噬设定",
            "前世、借技法、代价账本、额角跳痛、耳鸣、偏头痛、左眼花",
            "主角主人真名",
            "笔记本备用",  # substring 笔记 must NOT drop this
        ],
        cited_conflict_ids=["c2_借技法反噬", "c001"],
        cited_beat_ids=["b1_救场立身份", "b001"],
    )
    cleaned = sanitize_outline(outline)
    assert "穿越身份" in cleaned.reveal_forbidden
    assert "主角主人真名" in cleaned.reveal_forbidden
    assert "笔记本备用" in cleaned.reveal_forbidden
    assert "反噬设定" not in cleaned.reveal_forbidden
    assert "默写分镜笔记的存在" not in cleaned.reveal_forbidden
    assert not any("耳鸣" in item or "左眼花" in item for item in cleaned.reveal_forbidden)
    assert "c2_借技法反噬" not in cleaned.cited_conflict_ids
    assert "c001" in cleaned.cited_conflict_ids
    assert "b1_救场立身份" in cleaned.cited_beat_ids  # membership is Task 2; strip only 反噬/耳鸣/左眼花/笔记金手指/默写分镜笔记
    assert "b001" in cleaned.cited_beat_ids
```

Wait: `b1_救场立身份` does **not** contain a strip token. It stays for Task 1; Task 2 membership rejects it. `c2_借技法反噬` contains 反噬 → drop the item.

Also: `左眼薄雾` item drops. `穿越身份` stays.

- [ ] **Step 2: Run test — expect FAIL** (function missing)

`UV_PYTHON_PREFERENCE=managed uv run pytest tests/unit/test_outline_sanitizer.py::test_sanitize_outline_strips_overnight_forbidden_items -v`

- [ ] **Step 3: Implement**

```python
_OUTLINE_LEAK_ITEM_RE = re.compile(r"反噬|耳鸣|左眼花|左眼薄雾|笔记金手指|默写分镜笔记")


def _clean_token_list(items: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or _OUTLINE_LEAK_ITEM_RE.search(item):
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def sanitize_outline(outline: ChapterOutline) -> ChapterOutline:
    return outline.model_copy(
        update={
            "reveal_forbidden": _clean_token_list(outline.reveal_forbidden),
            "cited_conflict_ids": _clean_token_list(outline.cited_conflict_ids),
            "cited_beat_ids": _clean_token_list(outline.cited_beat_ids),
        }
    )
```

Do not import or change `factory.py`.

- [ ] **Step 4: pytest unit file PASS + ruff**

- [ ] **Step 5: Commit**

```
git add src/novel_agent/lint/bible.py tests/unit/test_outline_sanitizer.py
git commit -m "fix: strip 反噬/耳鸣/左眼花 items from persisted outlines"
```

---

### Task 2: citation membership lint

**Files:**
- Modify: `src/novel_agent/lint/bible.py` `lint_outline_citations` + `lint_bible`
- Test: `tests/unit/test_outline_sanitizer.py`

**Interfaces:**
- Consumes: cited ids + optional known sets
- Produces: findings for unknown ids; empty-both unchanged; empty known sets skip membership

- [ ] **Step 1: Failing tests**

```python
def test_lint_outline_citations_rejects_invented_ids() -> None:
    findings = lint_outline_citations(
        ["c2_借技法反噬"],
        ["b1_救场立身份"],
        "v1c001",
        known_conflict_ids={"c001", "c002"},
        known_beat_ids={"b001", "b002"},
    )
    assert findings
    blob = " ".join(f.message for f in findings)
    assert "b1_救场立身份" in blob
    assert "c2_借技法反噬" in blob

    ok = lint_outline_citations(["c001"], ["b001"], "v1c001",
        known_conflict_ids={"c001"}, known_beat_ids={"b001"})
    assert ok == []

    empty = lint_outline_citations([], [], "v1c009")
    assert empty and "未引用" in empty[0].message

    skipped = lint_outline_citations(
        ["b1_救场立身份"], ["x"], "v1c001",
        known_conflict_ids=set(), known_beat_ids=set(),
    )
    # known empty → no membership findings; not empty-both so []
    assert skipped == []
```

Fix the last case: cited_conflict `b1_救场立身份` is a conflict id in the first arg. Use `([], ["b1_救场立身份"], ...)` with empty known_beat_ids → skip membership → `[]`.

- [ ] **Step 2: FAIL then implement**

```python
def lint_outline_citations(
    cited_conflict_ids: Sequence[str],
    cited_beat_ids: Sequence[str],
    chapter_key: str,
    known_conflict_ids: AbstractSet[str] | None = None,
    known_beat_ids: AbstractSet[str] | None = None,
) -> list[LintFinding]:
    ...
```

In `lint_bible` loop:

```python
    known_c = {c.conflict_id for c in conflicts}
    known_b = {b.beat_id for b in payoff_beats}
    for chapter_key, conflict_ids, beat_ids in outline_citations:
        findings.extend(
            lint_outline_citations(
                conflict_ids,
                beat_ids,
                chapter_key,
                known_conflict_ids=known_c,
                known_beat_ids=known_b,
            )
        )
```

When `conflicts`/`payoff_beats` default to `()`, known sets are empty → membership skipped (keeps callers that don't pass bible rows from failing). R5 / plan_more already pass real lists.

- [ ] **Step 3: pytest unit + `tests/contract/test_story_bible.py` (R5 mock still persists)**

- [ ] **Step 4: Commit**

```
git commit -m "fix: reject outline citations that are not bible beat/conflict ids"
```

---

### Task 3: `apply_outline_edit` sanitize + lint

**Files:**
- Modify: `src/novel_agent/production/outline.py`
- Test: `tests/workflow/test_edit_outline.py`

**Interfaces:**
- After parse: `sanitize_outline` then `lint_outline_citations` with `BibleRepo` lists
- Empty-both or unknown ids → `OutlineEditError`, no `outline_version` bump
- Leak-token YAML → stripped, then lint (if citations remain valid, persist)

- [ ] **Step 1: Failing tests** in `test_edit_outline.py`

Reuse the existing REPLAN → export → import fixture.

1. Import YAML whose outline `reveal_forbidden` contains `反噬设定` and `默写分镜笔记的存在`, with valid mock citation ids from the fixture bible → succeeds, stored `reveal_forbidden` has neither string.
2. Import YAML with `cited_conflict_ids: []` and `cited_beat_ids: []` → `OutlineEditError` / CLI nonzero, `outline_version` unchanged.
3. Import `cited_beat_ids: [b1_救场立身份]` when bible has `b001`/`pb_micro1` → error.

Look up the mock project's real beat/conflict ids from the existing test setup (likely `pb_micro1` / `cf_voice`). Use those for the happy path, not invented `b001` unless the fixture has them.

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement in `apply_outline_edit` after parse, before replace_scene_cards**

```python
    outline = sanitize_outline(outline)
    bible = BibleRepo(session)
    findings = lint_outline_citations(
        outline.cited_conflict_ids,
        outline.cited_beat_ids,
        chapter_key,
        known_conflict_ids={c.conflict_id for c in bible.list_conflicts(project_id)},
        known_beat_ids={b.beat_id for b in bible.list_payoff_beats(project_id)},
    )
    if findings:
        raise OutlineEditError("; ".join(item.message for item in findings))
```

Need `BibleRepo` import. Session already available.

- [ ] **Step 4: pytest `test_edit_outline.py` + unit sanitizer + factory_gates (untouched, still green)**

- [ ] **Step 5: Commit**

```
git commit -m "fix: edit-outline strips leak tokens and lints citation membership"
```

---

### Task 4: R5 + plan-more sanitize after inherit

**Files:**
- Modify: `src/novel_agent/planning/volume.py` (`apply_inherited_spoilers` and/or `plan_more` persist)
- Modify: `src/novel_agent/planning/conversation.py` `_ensure_r5`
- Test: `tests/contract/test_volume_factory.py` inherit case + `tests/contract/test_story_bible.py` R5

**Interfaces:**
- Sanitize `remaining_forbidden` before inherit so 反噬 does not re-inject
- Sanitize each new outline after inherit
- Existing inherit test uses `主角主人真名` — must still inherit
- Add a case: previous outline forbidden contains `反噬设定`; new outline after inherit must **not** contain it
- R5 mock persist still succeeds

- [ ] **Step 1: Failing inherit test** (extend `test_volume_factory.py` inherit case around the `主角主人真名` assertion)

- [ ] **Step 2: FAIL then implement**

Prefer sanitizing inside `apply_inherited_spoilers` so every caller is covered:

```python
    remaining = _clean_token_list(remaining_forbidden)
    ...
        forbidden = _clean_token_list([*remaining, *outline.reveal_forbidden])
```

And in `_ensure_r5` map `sanitize_outline` over planner outlines before lint.

Do not rewrite prompts.

- [ ] **Step 3: pytest contract volume + story_bible + unit + edit_outline + factory_gates**

- [ ] **Step 4: Commit**

```
git commit -m "fix: strip leak tokens from inherited reveal_forbidden before persist"
```

---

## Self-review

1. Spec §5.1 strip → Task 1; §5.3 membership → Task 2; §5.2 import hook → Task 3; persist/inherit → Task 4. Unit cards / chapter_key match have no task.
2. Factory.py never in the file map.
3. Overnight strings copied. `穿越身份` kept.

## Execution handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — cloud agent per task, review between tasks
2. **Inline Execution** — this session

Which approach?
