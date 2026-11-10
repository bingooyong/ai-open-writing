# 项目级写作风格配置 — Design Spec

- Date: 2026-08-27
- Status: implemented
- Repo: `bingooyong/ai-open-writing`
- Scope: factory context + project.settings; no new table; no third-party novel text

## 1. North star

`ChapterContextPackage.style_rules` existed but production never filled it. Writer therefore defaulted to long-paragraph paperwork cadence. Style is a **project setting**, not a bible round and not a chapter lock. Scene cards decide *what happens*; the style pack decides *how it is said*.

Reference rhythm (一句一段, 时间地点单独成段, 心里话只留判断, 过程可砍, 镜头短句) is encoded as a frozen pack. Third-party 叶默/刘亦非/封于修 chapters are **not** stored in this repo; only original shorts ship as few-shot.

## 2. 大 / 中 / 小

- **大风格**：项目级口吻总闸。存在 `project.settings["style"]`。一经写入，Writer / Prose 只看编译后的 `style_rules`；不随章切换，也不由场景卡改口吻。
- **中风格**：冻结包。第一批五包，用 `id` 或中文别名加载（`load_frozen_pack` / `novel style set --pack`）。包内 `mid_style` 与别名同名。场景卡决定发生什么，中风格决定怎么说。
- **小风格**：`profile` 节奏旋钮（句长区间、一段几句、对白占比、叙述距离、心里话、时空写法、结果前置）。`samples` 只学句长、空行、叙述距离，不学情节。

### 第一批中风格目录

| id | 中文别名 / `mid_style` | 口吻 |
| --- | --- | --- |
| `oral_short_beat` | 镜头短句 | 一句一段，镜头短句，结果前置 |
| `craft_baimiao` | 职业白描 | 物件与工序推戏，一段两到四句仍要具体 |
| `dialogue_scene` | 对话场 | 对白承担场面，叙述只当舞台提示 |
| `dual_cut` | 双线切开 | 空行切第二现场；反应是信息到位不是打脸 |
| `close_interior` | 心理密距 | 判断贴 POV，自由间接，连续心理不超过三句 |

`src/novel_agent/style/__init__.py` 的 `ALIASES` 双向解析中文名 → 文件 id。已有项目（含 project 5）当前包保持 `oral_short_beat`；换中风格必须显式 `style set`。

## 3. Storage

`project.settings["style"]` holds the pack object:

```json
{
  "id": "oral_short_beat",
  "label": "一句一段·镜头短句",
  "mid_style": "镜头短句",
  "profile": { "...rhythm knobs..." },
  "rules": "<compiled Chinese>",
  "samples": ["<2 ORIGINAL shorts>"]
}
```

`StylePack.mid_style` is optional. Frozen copies: `src/novel_agent/style/packs/*.json`.

`PlanningRepo.update_project` **merges** flag patches onto the existing settings dict so `style` is not wiped. `set_project_style` / `get_project_style` are the dedicated accessors.

## 4. Compile and inject

`compile_style_rules(style)` joins `rules` + blank line + `节奏样例（只学句长、空行、叙述距离，不学情节）：` + samples.

`ContextBuilder.build`: if `style_rules` arg is empty, load the compiled string from `project.settings["style"]`. Explicit non-empty arg still wins. Invalid/missing pack → `""`, no crash.

`loop.py` does **not** pass `style_rules` (builder default is enough). Do **not** wire `previous_ending` from locked tails as a style few-shot; paperwork register would poison the cadence. Style samples are the few-shot.

Writer prompt: if context contains 风格规则, obey voice; scene cards only decide plot.
Prose reviewer: if 风格规则 is non-empty, violations are P1 (书面长句, 一段三句以上, 说明书式调度, 公文腔). Empty rules keep 「不做风格洁癖」.

## 5. API / CLI

- `GET /projects/{id}` includes `style` (object or null).
- `PATCH /projects/{id}` accepts optional `style`.
- `novel style list` — frozen catalog (`id` / 中文别名 / `label`)
- `novel style show --project N`
- `novel style set --project N --pack oral_short_beat`（中文别名亦可，如 `--pack 镜头短句`）

## 6. Out of scope

No new table. No clone of private canon prose. No change to kernel/chapters when seeding a pack. Do not rewrite an existing project's current pack (project 5 stays `oral_short_beat`). Plot bans (no 打脸, no real names, no 系统) stay in kernel/boundaries.
