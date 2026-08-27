# Project writing style configuration — Design Spec

- Date: 2026-08-27
- Status: implementing (five frozen 中风格 packs)
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
| Prose reviewer | Injects `# 风格规则` only when `style_rules` is non-empty |
| `PlanningRepo.update_project` | Must merge onto the current dict so flag patches cannot wipe `style` |
| `project.settings` | JSON column, no extra table |
| Kernel `do_not_write` / lock gates | Unrelated; do not change |

Empty style pack must keep today's writer behavior: omit `# 风格规则` when rules are empty.

## 2. North star

A project can persist a style pack under `project.settings["style"]`. Every chapter write/review for that project compiles it into `package.style_rules`. Callers do **not** have to pass `style_rules` into `ContextBuilder.build`. An explicit non-empty `style_rules` argument still wins (existing tests pass `"克制叙述"`).

Do **not** store or inject third-party novel body (no 叶默 / 刘亦非 / 封于修 sample chapters). Abstract profile params + original short samples only (林朔 / 老郑 / 许静蕾 片场). Do **not** seed a live `project_id`.

## 3. Style layers: 大 / 中 / 小

| Layer | Chinese | What it is | Where it lives |
|---|---|---|---|
| 大风格 | channel / genre | 网文频道、题材口吻(玄幻/都市/行业剧…) | **Not this task.** Channel export / genre, not `settings.style`. |
| 中风格 | narrative engine | 一场戏怎么往前走:镜头短句、职业白描、对话场、双线切开、心理密距 | **One frozen pack == one 中风格.** `StylePack.id` + `mid_style`. |
| 小风格 | sentence knobs | 句长、一段几句、对白占比、叙述距离 | Inside each pack's `profile`. |

A project picks **one** 中风格 pack. Switching packs is a full replace of `settings.style`.

## 4. Approaches considered

### A. `settings.style` JSON + builder default (chosen)

Store a `StylePack` object in the existing `project.settings` JSON. `ContextBuilder` loads and compiles it when the `style_rules` arg is empty. Fix `update_project` to merge onto the current dict so flag patches cannot wipe style.

### B. New `project_style` table (rejected)

Yagni.

### C. Fill `previous_ending` from last locked chapter as style few-shot (rejected)

Late-volume locked chapters often carry 公文 / 骑缝 register. Style samples in the pack are the few-shot. Do not wire `previous_ending`.

## 5. Style pack shape

Stored at `project.settings["style"]`:

```json
{
  "id": "oral_short_beat",
  "label": "一句一段·镜头短句",
  "mid_style": "镜头短句",
  "profile": { "...小风格 knobs..." },
  "rules": "<compiled Chinese writer rules>",
  "samples": ["<2 original shorts>"]
}
```

`mid_style` is optional (default `""`) so older stored packs still parse. Frozen packs always set it.

Pydantic `StylePack` / `StyleProfile` validate on read and write. Unknown, missing, or invalid `settings.style` → empty `style_rules`, no crash. Invalid PATCH body → 400.

Compiled injection string: `rules` + `节奏样例（只学句长、空行、叙述距离，不学情节）` + samples.

Load via `load_frozen_pack(id_or_alias)` (`load_builtin_pack` is the same function). CLI `--pack` and PATCH `pack` accept English ids and Chinese aliases.

## 6. Frozen catalog (five 中风格)

| id | mid_style / alias | label |
|---|---|---|
| `oral_short_beat` | 镜头短句 | 一句一段·镜头短句 |
| `craft_baimiao` | 职业白描 | 职业白描 |
| `dialogue_scene` | 对话场 | 对话场 |
| `dual_cut` | 双线切开 | 双线切开 |
| `close_interior` | 心理密距 | 心理密距 |

Files under `src/novel_agent/style/packs/<id>.json`. Samples use 林朔 / 老郑 / 许静蕾 片场 only.

## 7. Wiring

1. **Builder** — if `style_rules` arg is empty/whitespace, compile from `project.settings["style"]`.
2. **Loop / overlay** — no `style_rules` arg; do not add `previous_ending`.
3. **`prompts/writer.md`** — 若上下文含风格规则，叙述口吻必须服从；场景卡只决定情节。
4. **`prompts/prose.md`** — 若风格规则非空 → P1; otherwise 不做风格洁癖.
5. **`PlanningRepo.update_project`** — merge flag keys onto current `settings`.
6. **`PlanningRepo.update_project_style`** — full replace of `settings.style`.
7. **API** — `ProjectPatch.style` (full dict) and `ProjectPatch.pack` (frozen id or Chinese alias). GET includes `style`.
8. **CLI** — `novel style list`, `novel style show --project N`, `novel style set --project N --pack <id|别名>`.
9. **Out of scope** — lock gates, kernel `do_not_write`, seeding a live `project_id`, 大风格/channel, web textarea.

## 8. Error handling

| Input | Behavior |
|---|---|
| No `settings.style` | `style_rules=""`; writer/prose omit `# 风格规则` |
| Malformed style JSON | Same as missing (read path) |
| PATCH invalid pack / unknown alias | HTTP 400, settings unchanged |
| Unknown `--pack` | CLI exit 2 |
| Missing project | CLI exit 2 / HTTP 404 |

## 9. Testing

- Each frozen pack loads and compiles; aliases resolve; `style list` prints all five ids + labels
- No 叶默 / 刘亦非 / 封于修 in any pack JSON
- Builder default + override; `update_project` preserves style; writer/prose heading present/absent
- API PATCH `style` round-trip; PATCH `pack` alias; CLI show/set/list
