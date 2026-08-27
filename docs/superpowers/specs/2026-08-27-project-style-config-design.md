# Project writing style configuration — Design Spec

- Date: 2026-08-27
- Status: implementing
- Repo: `bingooyong/ai-open-writing`
- Scope: persist a project style pack and inject it as `# 风格规则` on every chapter write/review

## 1. Investigation (hypothesis checked)

The vacant-slot hypothesis is **correct**. Production never fills `ChapterContextPackage.style_rules`.

| Surface | Today |
|---|---|
| `ChapterContextPackage.style_rules` | Field exists, default `""` |
| `ContextBuilder.build(..., style_rules="")` | Passes the arg through; never reads `project.settings` |
| `production/loop.py` `ctx()` / `stage_chapter_overlay` | Do not pass `style_rules` |
| `runtime/agents.py` `_ctx_text` | Already injects `# 风格规则` **if** the string is non-empty |
| Prose reviewer | Always receives `# 风格规则\n{ctx.style_rules}` (often a heading with empty body) |
| `PlanningRepo.update_project` | Rebuilds `settings` with only `enable_writer_b` / `enable_reader_advocate` — **drops** any other key |
| `project.settings` | JSON column, no extra table. Currently those two flags only |
| Kernel `do_not_write` / lock gates | Unrelated; do not change |

Empty style pack must keep today's writer behavior: no `# 风格规则` heading content (omit the heading when rules are empty).

## 2. North star

A project can persist a style pack under `project.settings["style"]`. Every chapter write/review for that project compiles it into `package.style_rules`. Callers do **not** have to pass `style_rules` into `ContextBuilder.build`. An explicit non-empty `style_rules` argument still wins (existing tests pass `"克制叙述"`).

Do **not** store or inject third-party novel body (no 叶默 / 刘亦非 / 封于修 sample chapters). Abstract profile params + original short samples only.

## 3. Approaches considered

### A. `settings.style` JSON + builder default (chosen)

Store a `StylePack` object in the existing `project.settings` JSON. `ContextBuilder` loads and compiles it when the `style_rules` arg is empty. Fix `update_project` to merge onto the current dict so flag patches cannot wipe style.

- No migration / no new table
- Loop and overlay need no new args
- PATCH `style` is a full replace of `settings.style`

### B. New `project_style` table (rejected)

Yagni. The pack is a small JSON document already shaped for `settings`.

### C. Fill `previous_ending` from last locked chapter as style few-shot (rejected)

`previous_ending` is a **continuity** window, not a style teacher. Late-volume locked chapters in this corpus often carry 公文 / 骑缝 / 档案 register. Feeding that tail into new chapters would fight the oral-short-beat pack. Continuity already has entity states, retrieval, and outlines. **Do not wire `previous_ending` in this change.** Style samples in the pack are the few-shot.

## 4. Style pack shape

Stored at `project.settings["style"]`:

```json
{
  "id": "oral_short_beat",
  "label": "一句一段·镜头短句",
  "profile": {
    "paragraph_unit": "sentence",
    "avg_sentence_chars": [8, 22],
    "punch_line_max_chars": 8,
    "dialogue_ratio_hint": 0.4,
    "narrator_distance": "close_camera",
    "interior": "short_judgment",
    "time_place": "isolated_lines",
    "result_first": true
  },
  "rules": "<compiled Chinese writer rules>",
  "samples": ["<2 original shorts>"]
}
```

Pydantic `StylePack` / `StyleProfile` validate on read and write. Unknown, missing, or invalid `settings.style` → empty `style_rules`, no crash. Invalid PATCH body → 400.

Compiled injection string (kept short):

1. `rules` text
2. A labeled samples block: `节奏样例（只学句长、空行、叙述距离，不学情节）` plus the original samples

Default pack frozen at `src/novel_agent/style/packs/oral_short_beat.json` (author-owned 林朔/老郑 / 片场 samples only).

## 5. Wiring

1. **Builder** — if `style_rules` arg is empty/whitespace, compile from `project.settings["style"]`.
2. **Loop / overlay** — no `style_rules` arg; builder default is enough. Do not add `previous_ending` (see §3.C).
3. **`prompts/writer.md`** — one discipline line: 若上下文含风格规则，叙述口吻必须服从；场景卡只决定情节。
4. **`prompts/prose.md`** — branch in the template: if 风格规则 is non-empty, violating it is P1 (书面长句、一段三句以上、说明书式调度、公文腔). 「不做风格洁癖」 applies **only** when 风格规则 is empty.
5. **`PlanningRepo.update_project`** — copy current `settings`, patch only provided flag keys, write the merged dict.
6. **`PlanningRepo.update_project_style(project_id, style: dict)`** — full replace of `settings.style` after validation. `None` / omitted key on PATCH does not clear style; sending a valid pack replaces it.
7. **API** — `ProjectPatch.style`; GET/list project includes `style` (`id` / `label` / `rules` present when set, else `null`).
8. **CLI** — `novel style show --project N` and `novel style set --project N --pack oral_short_beat` (optional `--rules-file`). The installed command is `novel` (`novel-agent` is the package name).
9. **Tests** — builder default + override; update_project preserves style; writer heading present/absent; prose prompt documents the branch.
10. **Out of scope** — lock gates, kernel `do_not_write`, seeding a live `project_id`, web textarea (CLI + API is enough).

## 6. Error handling

| Input | Behavior |
|---|---|
| No `settings.style` | `style_rules=""`; writer omits `# 风格规则` |
| Malformed style JSON | Same as missing (read path) |
| PATCH invalid pack | HTTP 400, settings unchanged |
| Unknown `--pack` | CLI exit 2 |
| Missing project | CLI exit 2 / HTTP 404 |

## 7. Testing

- `tests/unit/test_context_builder.py` — pack in settings, no arg → rules present; explicit arg overrides; garbage style → empty, no crash
- `tests/unit/test_repos.py` — `update_project(enable_writer_b=...)` keeps `settings["style"]`
- `tests/contract/test_agents.py` — writer user text has `# 风格规则` iff non-empty
- Prompt file assertions for writer discipline + prose branch
- API PATCH `style` round-trip; CLI show/set

Do not rewrite lock-gate tests. Do not add third-party novel text to the repo.
