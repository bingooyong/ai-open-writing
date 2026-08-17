# Outline sanitizer — Design Spec

- Date: 2026-08-17
- Status: draft (from 《穿回去当导演》 20-chapter overnight run, after factory-gates #32)
- Repo: `bingooyong/ai-open-writing`
- Upstream: `main` `300c393` (PR #32 merged)
- Evidence: project 5 in `data/novel.db`; overnight factory spec §2 item 2

## 1. North star

After R5 / `plan-more` / `edit-outline`, persisted chapter YAML must not inject factory-leak tokens into the Writer context, and `cited_beat_ids` / `cited_conflict_ids` must be members of the bible (or empty-both rejected). The operator should not need a per-chapter YAML pass before `write-chapter`.

This spec is **planner/lint only**. It does not rewrite Writer, Judge, or retrieval prompts. It does not edit `factory.py` (leak regex already shipped in #32). Ports stay `8765` / `18765`. No Redis. Leave draft PR #24 alone. Do not commit `data/novel.db`.

## 2. Why this is a sub-project

#32 stops dirty **drafts** from locking. Writer still receives the full outline JSON (`runtime/agents.py` `_ctx_text`). Live project 5 after overnight `edit-outline`:

- All 20 chapters still have `反噬` in `reveal_forbidden`
- From v1c003/v1c008: `耳鸣` / `笔记` / `左眼花` still in that list
- v1c001 `cited_beat_ids = ['b1_救场立身份']` (bible is `b001`…`b020`)
- v1c009–v1c020 both citation lists empty (empty-both lint never ran on import)
- `outline_version` 2 on 19 chapters, **6 on v1c003**

`apply_inherited_spoilers` copies prior `reveal_forbidden` onto later chapters, so one dirty list poisons the volume.

Independent of factory gates. Next piece after this (out of spec): Writer/Judge prompt rewrite.

## 3. Approaches considered

### A. Sanitize + membership lint at persist and import (chosen)

Strip leak tokens from outline fields after inherit, then lint citations against bible ids. Hook R5, `plan-more`, and `apply_outline_edit`.

- Stops the overnight YAML toil without rewriting the planner prompt (MiniMax ignored citation format anyway)
- Import was the hole that let v1c009 empty lists land
- Does not make a wrong-book Writer draft good; factory already handles that

### B. Prompt-only “don’t put 反噬 in reveal_forbidden” (rejected)

Handoff: do not rewrite planner/Writer/Judge prompts as the first lever. Live MiniMax invented `b1_救场立身份` despite the outline planner asking for citations.

### C. Factory-only (already shipped, not enough)

#32 rejects leaky **prose**. It does not stop Writer seeing `reveal_forbidden: [反噬设定, 左眼花]`. That is this spec.

## 4. Overnight holes this spec closes

| Hole | Live example | Current code |
|---|---|---|
| Leak tokens in `reveal_forbidden` | All 20 ch: `反噬设定`; later also `耳鸣`/`左眼花`/`默写分镜笔记的存在` | No sanitizer. Inherit prepends the list (`volume.py:158-169`) |
| Import skips lint | v1c009 empty both persisted at ov=2 | `apply_outline_edit` (`outline.py:67-89`) only Schema-validates |
| Citation membership | v1c001 `b1_救场立身份`, `c2_借技法反噬` | `lint_outline_citations` (`bible.py:157-167`) empty-both only |
| N1 is a no-op | `loop.py` n1_validate_outline → DRAFTING | Stay a no-op if persist+import lint |

Already fixed, do not reopen: factory leak regex, empty-packet Judge, sole-lockable, n5 JSON, paused resume.

## 5. Design

### 5.1 Token strip (`sanitize_outline`)

New helper in `lint/bible.py` (keeps factory.py untouched):

`sanitize_outline(outline: ChapterOutline) -> ChapterOutline`

Strip from `reveal_forbidden` (primary overnight hole) and from `cited_conflict_ids` / `cited_beat_ids` **items**:

| Token | Action |
|---|---|
| `反噬` | drop the list item if the token appears in it |
| `耳鸣` | same |
| `左眼花` | same |
| `左眼薄雾` | same |
| `笔记金手指` | drop that whole item |
| `默写分镜笔记` | drop that whole item |

Do **not** substring-nuke `笔记` (false positive on 工作笔记 if it ever appears in `core_event`). Do **not** strip bare `左眼`. Do **not** strip `穿越` / `穿越身份` (this book’s premise; factory still gates 穿越 in drafts).

Do **not** rewrite `core_event` / `title` in the smallest slice (overnight body fields were already cleaned by hand). Belt-and-suspenders scan of those fields is out of scope.

Skip `PlotUnitCard.canon_constraints` in this spec (live u1 has an 耳鸣 sentence). Separate follow-up if needed.

Preserve item order. Drop empties after strip. Dedup.

### 5.2 When to sanitize

**After inherit, before lint and persist.**

1. `apply_inherited_spoilers` — sanitize `remaining_forbidden` **before** prepend, and sanitize each new outline after inherit.
2. `_ensure_r5` — sanitize each outline before `lint_bible` / `create_chapter`.
3. `plan_more` — same, after inherit.
4. `apply_outline_edit` — `parse_outline_yaml` then `sanitize_outline` then citation lint then bump.

Strip, do not reject, for leak tokens. Operator should not have to hand-edit YAML to delete 反噬.

### 5.3 Citation membership

`cited_beat_ids` are **`PayoffBeat.beat_id`** (`b001`…`b020` live), not StructureMap beats (`StructureBeat` has no `beat_id`). `cited_conflict_ids` are `Conflict.conflict_id` (`c001`…`c020`).

Extend `lint_outline_citations` (known sets from `lint_bible`’s existing `conflicts` / `payoff_beats`):

1. Keep empty-both → finding `outline_citation` (already).
2. **New:** an id not in the known set → finding (e.g. `b1_救场立身份`, `c2_借技法反噬`).
3. If known sets are **empty** (no bible rows yet), skip membership (do not fail every citation). Empty-both still fails.
4. Out of this spec: cited id’s `chapter_key` matching this chapter (v1c003 citing `c001` whose payoff is v1c001).

`lint_bible` already receives `conflicts` and `payoff_beats`. Pass `{c.conflict_id}` / `{b.beat_id}` into `lint_outline_citations`.

`apply_outline_edit` loads `BibleRepo.list_conflicts` / `list_payoff_beats` for the project and runs the same lint. Fail → `OutlineEditError`, do not bump `outline_version`.

R5 / `plan_more` already raise `PlanningError` on lint findings. Membership failures use that path.

N1 stays a status hop.

### 5.4 Spoiler lint interaction

`lint_spoiler_visibility` requires new outlines to inherit `remaining_forbidden`. If 反噬 is stripped from the remaining set, spoiler lint will not demand it. That is correct: do not re-inject tokens factory already gates in drafts.

### 5.5 Testing

No paid APIs. Do **not** add tests to `test_factory_gates.py`.

- Unit: strip 反噬/耳鸣/左眼花 items from `reveal_forbidden`; leave `主角主人真名`; 笔记本 as a forbidden item stays (substring `笔记` alone is not enough).
- Unit: `b1_救场立身份` fails; `b001` passes when known `{b001}`; empty-both still fails; unknown skipped when known set is empty.
- Workflow: `edit-outline` import of leak-token YAML is auto-stripped and persists; import of empty-both is **rejected**.
- Contract: R5 still persists mock outlines (`pb_micro1` / `cf_voice` exist in fixtures).

Live overnight strings in tests, not paraphrases:

- `反噬设定`
- `默写分镜笔记的存在`
- `前世、借技法、代价账本、额角跳痛、耳鸣、偏头痛、左眼花`
- `b1_救场立身份`
- `c2_借技法反噬`

### 5.6 Out of scope

- Writer / Judge / retrieval / outline_planner prompt text
- `factory.py` / `loop.py` gates
- Ports, Redis, PR #24, committing `novel.db`
- `PlotUnitCard.canon_constraints`
- Citation `chapter_key` match
- Rewriting already-locked project 5 rows (operator can re-import if they want; sanitizer helps the next volume)

## 6. Success criteria

A regression using overnight YAML would:

- Persist v1c009-shaped `reveal_forbidden` **without** 反噬/耳鸣/左眼花/默写分镜笔记
- Reject v1c009 empty-both on import
- Reject v1c001 `b1_救场立身份` on persist/import
- Accept mock `b001` / `pb_micro1` when those ids exist
- Leave #32 factory tests green without edits

## 7. Files

| Path | Change |
|---|---|
| `src/novel_agent/lint/bible.py` | `sanitize_outline`; membership in `lint_outline_citations`; `lint_bible` passes known ids |
| `src/novel_agent/production/outline.py` | sanitize + lint inside `apply_outline_edit` |
| `src/novel_agent/planning/volume.py` | sanitize remaining_forbidden + new outlines after inherit |
| `src/novel_agent/planning/conversation.py` | sanitize before R5 lint/persist |
| `tests/unit/test_outline_sanitizer.py` | new |
| `tests/workflow/test_edit_outline.py` | import strip + empty-both reject |
| `tests/contract/test_story_bible.py` | membership fail on invented ids (if a small case fits) |

## 8. Spec self-review

- No TBD. 穿越 left in. 笔记 is item-level, not substring.
- Membership is PayoffBeat/Conflict ids, not StructureMap.
- Factory.py explicitly not touched.
- Import empty-both reject vs token strip (strip tokens, reject empty citations) is explicit.
