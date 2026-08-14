# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-14）

**长跑默认不因单章 REPLAN 停卷；该章挂起，后续章继续。** 交互 `write-batch` 仍默认停批；隔夜 `run-volume` / 写作台长跑默认 keep-going。

**写作台长跑控制台已落地。** 未跑付费 API；默认 CI 仍不打网。

工厂仍是原来的 `novel run-volume` / `POST /projects/{id}/run-volume`。没有第二套 runner、没有 Redis、没有云队列。

写作台（`apps/web`，**18765** strictPort）现在有一条常驻「长跑控制台」：

- 开跑：预算 USD + 最多章数（原 `跑一卷` 仍走同一路由）。
- 跑中：当前章、已完成 / 计划章数、花费 vs 预算；可协作停止。
- 停止：`POST /projects/{id}/run-volume/stop` 只在进程内记下请求，循环在**下一章检查点**（与预算 / 章数上限同一处）停下，不杀进程。
- 人门：`HUMAN_REVIEW` 给出批准 + 续跑；`NEEDS_REPLAN` 给出续规划 / 开下一卷 + 续跑；`STALE` 续跑；`BUDGET` 说明预算用尽并给出续跑 / 再开跑。不再只显示一句「已停」。
- 长跑默认不因单章 REPLAN 停卷；该章挂起，后续章继续。交互 `write-batch` 仍默认停批，需 `--keep-going` / `--continue-on-replan` 才继续。
- 轮询仍在 `status === "running"` 时每 1.5s 拉一次；`current_chapter` / `chapters_done` / `status` / `stop_reason` 变化时刷新大纲 / 审稿 / 章节轨。

`VolumeRunStatus` 原有字段已够用，只加了 `cancel_requested`。`stop_reason` 就是门禁种类。

**第三次真实 MiniMax 现场：R5 outline planner 死于思维链截断 JSON（#21 已合进 `main`）。** 末世《余烬回声》Story Bible 走到 R5，`outline_planner` 两次 `_PlanOut` 校验失败：`Expecting value: line 2 column 11 (char 12)`。首呼 `16000/16000`（打满当时上限，截断），修复轮 2332 token 仍解析失败。更早一次 MiniMax ping 的 `content` 以 `<think>...` 开头。根因：MiniMax-M3 OpenAI 兼容默认 adaptive thinking，推理吃掉输出预算，JSON 被截断或被 think 块污染；旧 `_extract_json` 只剥 markdown 栅栏，think 内的 `{` 会把思维链和正文粘成非法 JSON。

已做（#21 已合进 `main`）：
- `_extract_json` / `parse_two_part` 先剥 `<think>` / `<thinking>` / `<reason>` / `<reasoning>`（含未闭合标签）再找 `{...}`。
- 修复轮只回传剥离后的 JSON 片段；若 `finish_reason=length|max_tokens` 或 `output_tokens >= max_tokens`，明确告知截断，不再把 16k 思维链塞回下一轮。
- 官方 MiniMax OpenAI-compat 字段（见 [text-openai-api](https://platform.minimax.io/docs/api-reference/text-openai-api)）：`json_mode` 时 `thinking: {type: disabled}`（M3 可关；M2.x 接受但关不掉）；一律 `reasoning_split=true`；同时传 `max_completion_tokens`。未发明非官方参数。
- 规划胖调用上限：outline `32768`，people/structure `16384`。Writer 两段式仍 16k，未改写手声口。
- pytest 仍只走 MockProvider，不打付费 API。

**黄金三章 lint 不再要求字面「主角」（已合进 `main`）。** 同一次 MiniMax-M3 跑里，模型用姓名（林暮）+ 封口/停电写第 1 章，`lint_golden_three` 只认 `主角/危机/问题/冲突/当场/眼前/承诺`，R2 整份结构被丢弃。现在传入内核抽出的活人名（名叫/名为/化妆师 后的词）即算「有活人」；纯世界观/历史沿革/地理志第 1 章仍失败。不要改回只认「主角」二字。

**`--chapters N` Story Bible 窗口范围已收口（#20 已合进 `main`）。** 同一场 MiniMax-M3 开书《余烬回声》(`novel init --chapters 3`) 在 Concept Judge R4 死于范围错位，不是文笔差。

现场形态：
- 结构策划发明了 115 章全书（中点 ch48 / 绝境 ch79 / 高潮 ch108 / 终局 ch115）。
- 冲突/爽点策划只填了滚动窗 `v1c001–v1c003`（对 `--chapters 3` 是对的）。
- R4 Concept Judge 按全书要冲突条目，REVISE 一次后仍非 PASS → 停（已知坑）。

选定政策（写入测试）：**窗口外 chapter_key 对 Judge 是草图，不是冲突合同。**
- 结构图可以勾勒后半本，但命名 `chapter_key` 应落在滚动窗或下一卷开篇拍（`v2c001`）；更远的幕用 `volume_id` + summary。
- R4 只要求冲突/爽点覆盖滚动窗 + 黄金三章。`ch48`/`ch115` 没有对应冲突行不得硬失败。
- 入参会先 `scope_structure_for_judge`：远章键清空并标 `named_key_status=sketch`，不回传原键，避免裁判再当合同。
- 纯设定黄金三章、空冲突列表仍失败。
- 实现：`src/novel_agent/domain/window_scope.py`；提示词 `structure_planner` / `concept_judge` 已升到 v2。

仍勿回退：冲突/爽点 lint 的 `rolling_keys` 若被一次性铺成全书 115 章，窗口与 Concept Judge 会对不上。滚动窗口应保持切片，不要把全书章键塞进单次 R3/R4/R5。

**章标题由系统盖章。** 按 `order_index` 生成「第N章 标题」（阿拉伯数字，如 `第1章 醒木`，不是「第一章」）。写手禁止写入正文；审稿页 / generic·起点·番茄·EPUB 导出共用 `novel_agent.production.heading.chapter_heading`。

**两段式 SCENE 标记用真实 scene_id；解析容忍占位词与重复块。** 格式说明必须带本批真实 id 与 `<<<SCENE:v1c001_s1>>>` 这类例子，禁止示范「场景id」二字。`parse_two_part` 先剥 think 包装，把 `场景id` / `scene_id` / `场景ID` 按序填入剩余期望槽，重复真实 id 留最后一块非空正文。`call_two_part` 默认修复 2 次。

端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。

Stage 0 冒烟骨架不要再动，除非人工付费跑暴露缺口。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`
2. `uv run ruff check . && uv run mypy src`
3. `cd apps/web && npm ci && npm test && npm run build`

## 仓库地图

| 路径 | 作用 |
|---|---|
| `apps/web/src/volume/VolumeRunConsole.tsx` | 写作台长跑控制台 |
| `apps/web/src/volume/mapVolumeConsole.ts` | idle / running / gate / budget 视图模型 |
| `src/novel_agent/production/volume_run.py` | `run_volume`、协作停止、`VolumeRunStatus` |
| `src/novel_agent/api/routes.py` | `POST/GET .../run-volume`、`POST .../run-volume/stop` |
| `src/novel_agent/domain/window_scope.py` | 滚动窗 vs 全书草图；Judge 入参裁剪远章键 |
| `tests/unit/test_window_scope.py` | 余烬回声 ch48/ch108 结构 + 三章冲突不得当范围错位失败 |
| `src/novel_agent/verification/stage0_smoke.py` | 三章真实模型冒烟（gated） |
| `tests/contract/test_run_volume.py` | 长跑契约：门禁、预算、协作停止、控制台字段 |
| `tests/regression/test_stage0_smoke.py` | 门闩 / 离线清单 / 预检锁当前工厂 |
| `eval/retrieval/golden_queries.json` | 冻结检索金标问句 |
| `src/novel_agent/eval/retrieval.py` | 植入语料、打分、报告 |
| `docs/retrieval-eval.md` | hash vs 真实嵌入决策与实测 |
| `src/novel_agent/production/heading.py` | 章标题唯一函数：`第N章 标题` |
| `src/novel_agent/production/export.py` | 渠道模板：generic / qidian / fanqie / epub |
| `src/novel_agent/memory/` | `MemoryRetrieval` 协议、hash 嵌入、LanceDB 索引、收集器 |
| `src/novel_agent/context/context_builder.py` | 组装包并填充 `retrieval_facts` |
| `src/novel_agent/domain/canon_writer.py` | 正史提交成功后重建索引 |
| `tests/unit/test_retrieve_eval.py` | 金标下限 / 破坏期望命中 / CLI / 无网络 |
| `tests/unit/test_memory_retrieval.py` | 植入事实命中 / 幂等 / 预算裁剪 |
| `tests/unit/test_channel_export.py` | 起点/番茄标题、EPUB zip、默认不含草稿 |

## 本地怎么跑

```bash
uv run alembic upgrade head
uv run uvicorn novel_agent.api.app:app --host 127.0.0.1 --port 8765
cd apps/web && npm run dev   # http://127.0.0.1:18765
```

CLI：`uv run novel retrieve --project-id 1 --query "西市火灾"`。
评测：`uv run novel retrieve-eval`（临时库，默认 hash）。
导出：`uv run novel export --project-id 1 --channel qidian --format txt --out /tmp/book.txt`。
长跑：`uv run novel run-volume --project-id 1 --yes --budget-usd 1 --max-chapters 8`。

**人工付费 Stage 0 冒烟（本环境未跑）：**

```bash
# 四槽位必须是真实 provider；judge.family ≠ creative.family
# 预检约按当前工厂首轮（双写手 + 6 评审 + overlay extract）估 USD
uv run novel smoke-stage0 --confirm-real-models --budget-usd 15
```

缺确认、缺正数预算、任一槽位 mock，命令都会拒绝。报告写在 `artifacts/verification/stage0-smoke-*.json`（可用 `--report` 指定）。不要把该命令加进默认 CI。

## 明确不要做

- 不要把前端改回 5173，不要放宽 CORS
- 不要在 pytest 里打付费 API / 付费嵌入；不要复制 analyzer 源码进本仓
- 不要在 CI 里真的生成百万字
- 不要新建 `source_record` / `timeline_event` 表
- 不要训练自定义模型、不要上云向量库
- 不要再改 Stage 0 冒烟骨架，除非人工付费跑暴露缺口
- 不要另起一套 runner / Redis / 云队列；长跑只走现有 `run-volume`
- 不要让隔夜 `run-volume` 因单章 `NEEDS_REPLAN` 停卷；该章挂起，后续已规划章继续
- 不要重写 Writer / Judge / retrieval；这是台子体验，不是工厂重写
- 不要让写手在正文里写「第N章 / 第一章」；不要把章标题格式写成「第一章」或 `v1c001 标题`
- 不要把两段式示例写成 `<<<SCENE:场景id>>>` / `<<<SCENE:scene_id>>>`；格式说明必须用真实 scene_id

## 下一刀建议

1. **人工本地用 MiniMax 再跑** `novel init --chapters 3`（同类火花即可），确认 R4 不再因「没给远章写冲突」停死；真质量 REVISE 仍只有一轮。写手两段式现在带真实 scene_id，解析也容忍占位词/重复块。
2. 用 MiniMax-M3 重跑《余烬回声》Story Bible R5（outline 现 32k + 关 thinking）。不要在 pytest 里打付费 API。
3. 若仍要一次规划全书 100+ 章：先拆滚动窗口，不要让 R3/R4/R5 吃 115 个章键。
4. 人工本地跑付费 Stage 0 冒烟并审清单。不要再改冒烟预检表，除非付费跑再暴露缺口。
5. 看写作台还缺什么（审稿台与长跑控制台的衔接、过夜 mock 的章数体验），不要重启 smoke-stage0。
6. 不要把黄金三章 lint 改回只认字面「主角」；不要改回端口 5173。
7. 若要动检索本身（评测已冻结）：先用金标试词面权重，再考虑真实嵌入；真实嵌入保持 opt-in。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。MiniMax 现场曾把「只规划了 3 章冲突 vs 115 章结构图」当成质量问题 REVISE，现已按滚动窗裁剪 Judge 入参；真质量 REVISE 仍只有一轮。
- 默认 plan-more **不**因结构图高潮已锁定就开 v2；要开卷需 `--open-volume` 或把当前单元标成 `locked`。
- `max_calls_per_chapter` 为 40（双写手 + advocate）。
- mock 的 `cost_estimate` 默认为 0；隔夜 mock 请带 `--max-chapters`，USD 硬上限主要约束真实模型。
- 协作停止只在章与章之间生效；正在写的那一章会跑完当前 `run_chapter_loop`。
- 停止旗标是**进程内**的；换一个 API 进程看不到。单进程 `uvicorn` 写作台够用。
- LanceDB 表不能从空 list 创建；无事实时直接不建表，检索为空。
- hash 混合在小语料上弱于纯词面：`lexical_overlap` 已能召回的事实会被 hash 向量往后推。
- `stage_provisional`（批次 overlay）不重建检索索引；后章 `retrieval_facts` 主要来自规划期场景/章纲（首次 retrieve 会懒加载 reindex）。正史 `finalize` 才会 `_reindex`。
- Stage 0 冒烟预检只覆盖首轮 happy path，不含 REVISE 轮次。
