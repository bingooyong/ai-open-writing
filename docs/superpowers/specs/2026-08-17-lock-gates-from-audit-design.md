# Lock gates from audit — Design Spec

- Date: 2026-08-17
- Status: draft (from locked 《穿回去当导演》 v1c001–005 bible misses)
- Repo: `bingooyong/ai-open-writing`
- Upstream: `main` `9f8fbad` (PR #33 outline sanitizer; PR #32 factory gates at `300c393`)
- Evidence: locked v1c001–005 drafts that still violate the story bible; live v1c001 draft 44 is Judge PASS and contains `实习生`

## 1. North star

The chapter factory **refuses to auto-lock** drafts that repeat five bible misses from locked 《穿回去当导演》 v1c001–005, and still **locks a sibling** that does not.

This spec is **factory-loop only**. It does not rewrite Writer, Judge, or retrieval prompts. Ports stay `8765` / `18765`. No Redis. No second runner. Leave draft PR #24 alone. Do not reopen outline-sanitizer work. Do not add `pov_person` or `cast` fields to `ChapterOutline`.

## 2. Why this is a sub-project

#32 already stops empty-packet Judge, leak regex (`穿越|耳鸣|真名|实习生|左眼花|左眼薄雾|反噬`), on-brief character-card names, 许静蕾 whitelist, n5 JSON, and PLANNED-vs-paused resume.

Those leak/on-brief checks only run inside n6 **fallbacks**: `pick_lockable_candidate` on empty Judge, `pick_sole_lockable_candidate` on non-PASS. A real Judge PASS goes `_apply_verdict` → HUMAN_REVIEW → auto n8 `CANON_LOCKED` and **never** consults `is_lockable_draft`.

Live proof: locked v1c001 draft 44 is Judge PASS and contains `实习生`, which is already in `_HARD_GATE_LEAK_RE`.

Independent pieces, build order:

1. **This spec — lock gates from audit** (LockGates plumbing, POV person lock, Judge PASS veto; later 徐姐 / mechanism-naming / body-cost / unscheduled character)
2. Writer/Judge prompt rewrite — **out of this spec**

## 3. Approaches considered

### A. Factory-only lock gates + PASS veto (chosen)

Keep Writer/Judge prompts. Teach `is_lockable_draft` five bible-miss detectors behind a `LockGates` object. Thread `gates` through the existing pick helpers. After n6 has a selected candidate, if that draft is not lockable, do not treat PASS as lockable: synthesize PASS onto the sole lockable sibling, or force HUMAN_REVIEW.

- Matches the north star (refuse the miss, lock the sibling)
- Closes the Judge PASS hole that let draft 44 lock with `实习生`
- Tests live in `tests/unit/test_factory_gates.py` and `tests/workflow/test_chapter_loop.py`
- Does not make a chapter good when every candidate repeats the miss

### B. Rewrite Writer/Judge prompts (rejected)

Would reduce first-person dumps and 徐姐 leaks at the source, but the standing constraint is not to rewrite those prompts.

### C. Add `pov_person` / `cast` to ChapterOutline (rejected)

Outline schema stays as-is. Infer POV person from `outline.pov`. Unscheduled-character schedule is derived from volume outline fields at loop time, not stored on `ChapterOutline`.

## 4. Overnight / locked-draft holes this spec closes

| Hole | Live example | Current code |
|---|---|---|
| Judge PASS skips lock gates | v1c001 draft 44 PASS contains `实习生` | `is_lockable_draft` only in empty-packet / non-PASS fallbacks (`loop.py` `_n6`) |
| First-person dump in a named-POV chapter | v1c001 `我用拇指抹了一下`; v1c003-style 我-dominant, 林朔=0 | No POV-person detector |
| 徐姐-style real-name adjacency + 实习场记 | later locked misses | leak regex has `实习生` but not `实习场记` / 徐姐 adjacency |
| Mechanism named in prose | `我没解释` / `他不写笔记` | `_HARD_GATE_LEAK_RE` must not gain bare `笔记` |
| Body-cost symptoms in ch1–3 | `嗡声` `眩晕` `额角` `跳痛` `偏头痛` `失明` `耳侧` | no chapter-index-aware gate; do not gate `尾音` / `心跳` / `手凉` / `出汗` / `手还在抖` |
| Unscheduled character too early | 黎冰屏 first at v1c013 appearing in v1c004 | no schedule lookahead; 兆薇 in c001 is allowed |

Already fixed, do not re-open: empty-packet Judge, 左眼花/反噬 leak regex, on-brief names, 许静蕾 whitelist, n5 JSON, paused resume, outline sanitizer.

## 5. Design

### 5.1 LockGates plumbing

```python
@dataclass(frozen=True)
class LockGates:
    required_names: list[str] | None = None
    pov: str = ""
    pov_person: str | None = None  # "first" | "third"
    chapter_index: int | None = None
    card_names: list[str] | None = None
    schedule: list[tuple[int, str]] | None = None
    reveal_forbidden: list[str] | None = None
```

Keep signature:

```python
is_lockable_draft(text, boundaries, required_names=None, gates: LockGates | None = None)
```

Existing positional `required_names` still works. When `gates` is omitted, new detectors skip (PR #32 tests stay green). When both are passed, `gates.required_names` wins if it is not `None`; otherwise the positional list is used.

Thread `gates` through `_lockable_candidates` / `pick_lockable_candidate` / `pick_sole_lockable_candidate`.

Helper `chapter_index_from_key(key: str) -> int | None` parses `c(\d+)` from `v1c001` → `1`. Missing / unparsable → `None`.

Task 1 introduces the dataclass and threads `pov` + `chapter_index`. Later tasks fill `card_names` / `schedule` / `reveal_forbidden`. Do not implement those detectors in Task 1.

### 5.2 POV person lock (Task 1)

Infer `pov_person` if unset:

- `outline.pov` in `{我, 第一人称}` → `"first"`
- else if `pov` is non-empty → `"third"`
- else skip the detector

Counts:

- `wo` = count of `我` that is **not** the prefix of `我们` (`我(?!们)`)
- `pov_n` = substring count of the pov name (e.g. `林朔`)

Rules:

- Third (default): **not** lockable if `wo >= 8` and `wo / (wo + pov_n) >= 0.75`
- First: **not** lockable if `pov_n >= 8` and `wo / (wo + pov_n) <= 0.25`

This must catch v1c001-style (我 dominant, 林朔=0) and v1c003-style, and must **not** catch v1c002/004/005-style third person.

Live fixtures (use these strings, not paraphrases). Pad with existing `_long_prose()` so `MIN_DRAFT_PROSE_CHARS` is met:

```python
V1C001_OPEN = "场记板上的墨迹没干透，我用拇指抹了一下：第三十二场。"
V1C002_OPEN = "林朔把凉透的茶水搁在椅脚边，手心还攥着杯壁。"
```

`_long_prose() + V1C001_OPEN * 10` with `LockGates(pov="林朔", required_names=["林朔"])` is usable but not lockable.

`_long_prose() + "林朔盯着监视器。兆薇从化妆间出来。" * 5` with the same gates **is** lockable.

### 5.3 Judge PASS veto (Task 1 — required, not a fallback-only gate)

Lockability gates apply to **Judge PASS**, not only empty-packet / non-PASS fallbacks.

After n6 has a verdict with selected candidate text, if that draft is not `is_lockable_draft(..., gates=...)`, do **not** treat PASS as lockable.

- If there is **exactly one other lockable sibling**, synthesize PASS onto that sibling (same as sole-lockable).
- If none (or the selected one is the only candidate and it fails), force `HUMAN_REVIEW` / do not synthesize PASS.
- If the selected draft **is** lockable, keep the Judge PASS (do not run sole-lockable over two clean candidates).

Non-PASS sole-lockable fallback stays: REPLAN/HUMAN_REVIEW/REVISE with exactly one lockable candidate still synthesizes PASS onto that candidate.

Empty-packet path still uses `pick_lockable_candidate` when Judge is absent; that path already consults `is_lockable_draft`.

### 5.4 徐姐-style real-name adjacency + 实习场记 (Task 2, document only)

Not lockable if the draft contains `实习场记`, or a 徐姐-style real-name adjacency (徐姐 next to a forbidden real-name / 静蕾 form). Exact detector lands in Task 2. Do not add `笔记` or bare `左眼` to `_HARD_GATE_LEAK_RE`. `实习生` remains a leak from #32.

### 5.5 Mechanism-naming (Task 3, document only)

Not lockable if the draft matches:

`我没解释|没法解释|不能解释自己为什么|他不写笔记|我不写笔记|没有写笔记`

Do **not** gate bare `笔记`. Do **not** gate `我没说`. Never add substring `笔记` to `_HARD_GATE_LEAK_RE`.

### 5.6 Body-cost in ch1–3 only (Task 4, document only)

Not lockable if `chapter_index` is 1, 2, or 3 and the draft matches:

`嗡声|眩晕|额角|跳痛|偏头痛|失明|耳侧`

Skip `心跳` / `手凉` / `出汗` / `手还在抖`. Skip if `chapter_index` is `None` or `> 3`. Do not gate `尾音`.

### 5.7 Unscheduled character (Task 5, document only)

Build `first_schedule` from volume outline `title` + `core_event` + `pov`, lookahead=1. A name whose first scheduled chapter is later than `chapter_index + 1` is too early.

`reveal_forbidden` substring wins (许静蕾/周洵登场). 黎冰屏 first at v1c013 appearing in v1c004 is too early. 兆薇 in c001 is allowed.

`ChapterOutline` does not gain `pov_person` or `cast`.

### 5.8 loop.py wiring (Task 1)

`_n6` builds:

```python
LockGates(
    required_names=names,
    pov=package.outline.pov,
    chapter_index=chapter_index_from_key(chapter_key),
)
```

and passes `gates` into `pick_lockable_candidate`, `pick_sole_lockable_candidate`, and the Judge PASS veto. Production gets POV immediately; later tasks add more fields to the same constructor.

### 5.9 Testing

No paid APIs in pytest. Extend `tests/unit/test_factory_gates.py` for LockGates / POV / PASS veto. Extend `tests/workflow/test_chapter_loop.py` with MockProvider: Judge PASS on a first-person-dominant / `实习生` draft does **not** auto-lock; a third-person / clean sibling still can.

Live locked-draft strings must appear as fixtures, not paraphrases.

### 5.10 Error handling

- Lockability gates apply to Judge PASS, not only empty-packet fallbacks.
- Empty packet with no lockable candidate: keep raising `StructuredOutputError("Judge 空包且无可用合规候选")`.
- PASS on a non-lockable selected draft with no lockable sibling: force HUMAN_REVIEW, do not synthesize PASS, do not auto n8.
- Both drafts repeating the same miss: stay HUMAN_REVIEW / original non-PASS verdict. Do not invent a lock.
- `wo + pov_n == 0`: POV detector does not fire (not lockable-by-POV).
- When `gates` is omitted, POV / later detectors skip; #32 leak / on-brief / empty-packet behavior unchanged.

### 5.11 Out of scope

- Writer / Judge / retrieval prompt text
- Outline YAML sanitizer (PR #33)
- Ports, Redis, second runner
- Draft PR #24
- Adding `pov_person` or `cast` to `ChapterOutline`
- Gating `尾音`, bare `笔记`, bare `左眼`, `我没说`, `心跳` / `手凉` / `出汗` / `手还在抖`
- Implementing Tasks 2–5 in the Task 1 PR beyond documenting them

## 6. Success criteria

A regression using locked-draft strings would:

- Refuse to auto-lock `_long_prose() + V1C001_OPEN * 10` when POV is 林朔
- Still lock `_long_prose() + "林朔盯着监视器。兆薇从化妆间出来。" * 5` with the same gates
- Refuse to auto-lock a Judge PASS whose selected draft is first-person-dominant or contains `实习生`
- Synthesize PASS onto the sole lockable third-person sibling
- Leave PR #32 tests green when `gates` is omitted

## 7. Files

| Path | Change |
|---|---|
| `src/novel_agent/production/factory.py` | `LockGates`, `chapter_index_from_key`, POV detector, `gates` on pick helpers, PASS veto helper |
| `src/novel_agent/production/loop.py` | build `LockGates`; pass into picks; veto non-lockable Judge PASS |
| `tests/unit/test_factory_gates.py` | POV + PASS veto fixtures |
| `tests/workflow/test_chapter_loop.py` | MockProvider: PASS on leaky/first-person selected draft does not auto-lock |

## 8. Spec self-review

- No TBD on Task 1. PASS veto is explicit in §5.3 / §5.10.
- Tasks 2–5 are specified enough to implement later; Task 1 PR must not ship those detectors.
- `笔记` / `左眼` / `尾音` / `我没说` disambiguated.
- `ChapterOutline` is not extended.
