# Overnight factory gates — Design Spec

- Date: 2026-08-17
- Status: draft (from 《穿回去当导演》 20-chapter overnight run)
- Repo: `bingooyong/ai-open-writing`
- Upstream: PRs #29 / #30 / #31 already on `main` (`5d69b0c`)
- Evidence: private canon `bingooyong/yujin-huisheng-canon` (`d427e4c`), project 5 in `data/novel.db`

## 1. North star

After a 20-chapter volume write, the chapter factory must **auto-lock** a lockable draft when Judge/reviewer output is empty, schema-echo, or wrongly REPLAN, without a human rewriting YAML or SQL.

This spec is **factory-loop only**. It does not rewrite Writer, Judge, or retrieval prompts. Ports stay `8765` / `18765`. No Redis. No second runner. Leave draft PR #24 alone.

## 2. Why this is a sub-project

#29–#31 already stop: empty-packet HUMAN_REVIEW (some wordings), Chinese `revision_scope` lint, n7 `xxx`, Writer B <800 chars, SCENE scaffold / “请补场景卡”, sole-lockable when the sibling is leaky, per-run call budget, story-order `latest_entity_states`.

Overnight still needed **manual lock** for most of 003, 005–007, 009, 012–015, 018–020. Auto N8 after #29: 001, 002, 004, 008, 010, 011, 016, 017 (several of those PASSes were schema-echo PASS, not a real Judge read).

Independent pieces, build order:

1. **This spec — overnight factory gates** (empty packet, leak regex, on-brief, whitelist, n5 JSON, dead resume)
2. Outline import sanitizer (反噬 / 耳鸣 / 笔记 / 左眼 in default YAML, invalid `cited_beat_ids`) — **out of this spec**
3. Writer/Judge prompt rewrite — **out of this spec**

## 3. Approaches considered

### A. Factory-only gates (chosen)

Keep Writer/Judge prompts. Teach the loop to treat empty/schema-echo as “no verdict”, treat 民国/密室 junk as not lockable, treat 许静蕾 as a character-card name, treat n5 JSON fail as absent reviewer, fail dead paused/running workflows before a fresh write.

- Matches the overnight operator recipe (pick the on-brief draft, strip leaks, lock)
- Tests live in `tests/unit/test_factory_gates.py` and `tests/workflow/test_chapter_loop.py`
- Does not make both-off-brief chapters good (v1c012 沈奕/陈恪 stays HUMAN_REVIEW)

### B. Rewrite Judge + Writer prompts (rejected)

Would reduce 民国 dumps and schema echo at the source, but the standing constraint is not to rewrite those prompts, and overnight already spent tokens on prompt-adjacent retries.

### C. Outline sanitizer + factory (deferred)

Every overnight chapter needed `edit-outline` to strip 反噬/耳鸣/左眼 and empty `cited_beat_ids`. Real, but it is planner/lint (`planning/volume.py`, `lint/bible.py`), not the chapter loop. Separate spec.

## 4. Overnight holes this spec closes

Evidence from project 5 Judge reasons and drafts (whitespace-stripped ≥800, current `_HARD_GATE_LEAK_RE` false):

| Hole | Live example | Current code |
|---|---|---|
| Empty-packet wording miss | v1c012 「输入内容为空，未检测到任何场景候选」; v1c013 「未提供实际场景」; v1c020 schema echo | `_EMPTY_PACKET_MARKERS` (`factory.py:48-57`) has no those strings |
| Empty-packet + invented gate | v1c012/013/020 `hard_gate_failures=['source_risk']`; v1c006 `info_violation` with 「用户未提供评审材料」 | `is_empty_packet_verdict` returns False if any hard_gate (`factory.py:115-116`) |
| Wrong-book long prose | v1c018 d88 周意/陆怀 民国 vs d89 林朔; v1c011 d75 陆沉; v1c005 仙侠 | `is_lockable_draft` has no character-name check; `pick_sole_lockable_candidate` returns None when both “clean” (`factory.py:232-234`) and when `len(candidates)<2` (v1c014 only Writer B) |
| Allowed variant as 真名 | v1c009 `content_boundary(许静蕾真名)` | `sanitize_verdict` (`loop.py:131-172`) does not whitelist character-card names |
| 左眼 / 反噬 leak | v1c008/010 左眼花、左眼薄雾 | `_HARD_GATE_LEAK_RE = 穿越\|耳鸣\|真名\|实习生` (`factory.py:61`). 「笔记」 stays out |
| n5 JSON fail stuck | v1c015 `n5_parallel_review` Continuity `StructuredOutputError` | `_n5` raises `NodeFailed` (`loop.py:741-742`); `_advance` does not catch it (unlike n6/n7). Chapter stays `ADVERSARIAL_REVIEW`; volume keep-going skips that status |
| Dead resume | overnight `UPDATE workflow_run SET status='failed'` before every fresh write | `find_resumable_run` (`ops.py:120`) picks `running\|paused`; reset-to-planned only when last status is **failed** (`loop.py:231-249`) |

Already fixed, do not re-open: n7 `xxx`, Chinese `revision_scope`, Writer B min 800, SCENE scaffold, per-run budget, story-order entity states.

## 5. Design

### 5.1 Empty packet

Extend `_EMPTY_PACKET_MARKERS` with:

- `输入内容为空`
- `未检测到任何场景`
- `未提供实际场景`
- `未提供实际裁决`
- `JSON Schema`
- `Schema 定义`
- `$defs`
- `缺少必需字段`
- `缺少必需的 verdict`

Change `is_empty_packet_verdict`:

- If `is_empty_packet_reason(reasoning_summary)` is true, treat as empty **even when** `hard_gate_failures` is only `source_risk` and/or `info_violation` (Judge invents these on empty packets).
- If `hard_gate_failures` contains a real gate (`canon_conflict`, `causality_break`, `core_constraint`, `content_boundary`, …) **and** the reason does **not** match empty markers, it is not empty.
- HUMAN_REVIEW with no accepted rulings and empty-packet reason remains empty.

Existing n6 path already: empty → retry drop quotes → `pick_lockable_candidate` → `synthesize_pass_verdict`. No new control flow beyond the detector.

### 5.2 Hard-gate leak regex

`_HARD_GATE_LEAK_RE` becomes:

```
穿越|耳鸣|真名|实习生|左眼花|左眼薄雾|反噬
```

Do **not** add `笔记` (false positive on 工作笔记 / 笔记本). Do **not** add `左眼` alone (false positive on 左眼皮).

A draft with 左眼花 is usable at n3 (long prose) but not lockable. Sole-lockable can then pick the sibling.

### 5.3 On-brief lockability

`is_lockable_draft(text, boundaries, required_names=None)`:

- Existing checks unchanged.
- If `required_names` is a non-empty list: the draft is **not** lockable unless at least one name appears as a substring in the text.
- `required_names` come from `package.characters[].name` (character cards). Empty card list → skip this check (tests that do not pass names keep current behavior).

`pick_lockable_candidate` / `pick_sole_lockable_candidate` take the same optional `required_names` and pass them through.

Overnight: 周意/陆怀/陆沉/沈奕 drafts have zero of 林朔、樊冰屏、周洵、许静蕾、张紫衣、兆薇、黎冰屏、柳奕妃 → not lockable. Sibling with 林朔 → sole-lockable PASS.

If **both** drafts fail on-brief, stay on the Judge verdict (HUMAN_REVIEW / REPLAN). Do not invent a lock.

### 5.4 Sole-lockable with one candidate

`pick_sole_lockable_candidate`:

- If exactly one candidate and it is lockable → return it (overnight v1c014 only Writer B).
- If two or more and exactly one lockable → return that one (existing).
- If zero lockable, or two+ lockable → None.

Update `test_sole_lockable_none_when_both_clean_or_both_junk`: the single-clean case must now return that candidate, not None.

### 5.5 Character-name whitelist on Judge 真名

`sanitize_verdict(verdict, issues, allowed_names=None)`:

- After existing downweight logic, drop a `content_boundary` hard gate when every supporting issue claim/reason (and the reasoning_summary hit) is only flagging a string that is in `allowed_names` (character-card names).
- Drop matching accepted rulings the same way.
- If that was the only remaining gate/ruling, existing “no evidence → PASS” path may fire; if other real gates remain, leave the verdict type as-is.

Do not whitelist 章子怡 / 徐静蕾 (not on the card). 许静蕾 on the card stays.

n6 calls `sanitize_verdict` with `package.characters` names.

### 5.6 n5 ReviewReport JSON fail

`_advance` ADVERSARIAL_REVIEW branch: wrap `await _n5(...)` like n6:

```
except NodeFailed as exc:
    if "StructuredOutputError" not in str(exc):
        raise
    transition(... HUMAN_REVIEW)
    return "n5_parallel_review", "ReviewReport 非法,升级人工"
```

Additionally inside `_n5`: if a **critical** reviewer returns `StructuredOutputError` / invalid JSON, treat that reviewer as `absent` instead of setting `critical_error`, so a later retry that reaches n6 can still empty-packet-lock. Prefer absent-and-continue when at least one non-critical report parsed; only HUMAN_REVIEW when the node cannot produce any reports.

Chosen rule (explicit):

1. Per-reviewer parse fail → that role goes to `absent`, do not set `critical_error` for `StructuredOutputError`.
2. If after the gather there are zero parsed reports **and** a critical role failed parse → raise `NodeFailed` with `StructuredOutputError` so `_advance` maps to HUMAN_REVIEW.
3. Otherwise continue to JUDGING with `absent` filled.

Volume keep-going already skips HUMAN_REVIEW; that is acceptable. The overnight failure mode to kill is **stuck ADVERSARIAL_REVIEW** with a dead n5.

### 5.7 Dead paused/running resume

In `run_chapter_loop`, before treating `find_resumable_run` as live:

If a resumable run is `paused` or `running`, **and** the chapter is not `CANON_LOCKED` / `EXPORTED`, **and** the caller is a fresh `write-chapter --yes` (auto gates) with no in-process node lease newer than N minutes is **too fuzzy**.

Explicit rule:

- If resumable status is `paused` and `current_node` is `n6_judge` / `n5_parallel_review` / `n4_lint` **and** chapter status is `NEEDS_REPLAN` or `PLANNED` (operator imported a new outline or asked a new write): fail that run (`status=failed`), void succeeded nodes, `reset_to_planned`, create a new run. Same as the existing failed path.
- If resumable status is `running` and `updated_at` is older than 15 minutes with no in-flight model_run for that `workflow_run_id` in the last 15 minutes: treat as dead, same fail/void/reset.
- If `running` and there is a recent `model_run` for that workflow: resume (true crash recovery).

Do not silently resume a paused HUMAN_REVIEW/REPLAN loop onto a rewritten outline; that reused `{chapter}|{outline_ver}|1|n3` and mixed old drafts overnight.

CLI `write-chapter --yes` always goes through this. Manual review UI that intends to resume the same paused run is unchanged if chapter status is still `HUMAN_REVIEW` and outline_ver did not bump — then resume is correct.

Simpler implementation that matches the overnight operator:

When creating a new loop would otherwise resume `paused`/`running`, **if chapter status is `PLANNED` or `NEEDS_REPLAN`**: fail the old run first, then create new. HUMAN_REVIEW / ADVERSARIAL_REVIEW / JUDGING / DRAFTING still resume.

That is the chosen rule. One boolean, no timestamps.

### 5.8 Testing

No paid APIs in pytest. Extend `tests/unit/test_factory_gates.py` for detector/lockability/whitelist. Extend `tests/workflow/test_chapter_loop.py` (and resume tests if present) for n5 parse fail and PLANNED-vs-paused fail.

Live overnight strings must appear in tests as fixtures, not paraphrases.

### 5.9 Error handling

- Empty packet with no lockable candidate: keep raising `StructuredOutputError("Judge 空包且无可用合规候选")` (existing).
- Both drafts off-brief: do not synthesize PASS.
- 许静蕾 whitelist must not swallow a `content_boundary` that also cites 章子怡.

### 5.10 Out of scope

- Writer / Judge / retrieval prompt text
- Outline YAML sanitizer / `cited_beat_ids` membership
- Ports, Redis, second runner
- Draft PR #24
- Making a chapter lockable when every candidate is the wrong book

## 6. Success criteria

A regression test file using overnight strings would have auto-locked:

- v1c012 / v1c013 / v1c020 empty+source_risk → pick lockable on-brief draft
- v1c018 民国 sibling → sole-lockable B
- v1c014 single Writer B on-brief → sole-lockable
- v1c009 许静蕾 content_boundary dropped
- v1c008 左眼花 draft not lockable
- v1c015 n5 JSON fail → HUMAN_REVIEW or JUDGING with continuity absent, **not** stuck ADVERSARIAL_REVIEW
- Fresh write on PLANNED while old loop paused → new workflow, not resume n6

## 7. Files

| Path | Change |
|---|---|
| `src/novel_agent/production/factory.py` | markers, empty detector, leak regex, required_names, sole n=1 |
| `src/novel_agent/production/loop.py` | pass names into picks; sanitize whitelist; n5 parse; PLANNED fails paused run |
| `src/novel_agent/domain/repos/ops.py` | only if a helper `fail_workflow_run` is missing |
| `tests/unit/test_factory_gates.py` | new cases |
| `tests/workflow/test_chapter_loop.py` | n5 + resume |

## 8. Spec self-review

- No TBD. Empty-packet invented gates listed. Sole n=1 vs both-clean None is explicit.
- Outline sanitizer called out as a later spec, not mixed in.
- 笔记 / 左眼 vs 左眼花 disambiguated.
