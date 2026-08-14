# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-14）

**黄金三章 lint 不再要求字面「主角」。** 由一次真实 MiniMax-M3 Story Bible 跑（末世《余烬回声》）发现：模型用姓名（林暮）+ 封口/停电写第 1 章，`lint_golden_three` 只认 `主角/危机/问题/冲突/当场/眼前/承诺`，R2 整份结构被丢弃。现在传入内核抽出的活人名（名叫/名为/化妆师 后的词）即算「有活人」；纯世界观/历史沿革/地理志第 1 章仍失败。端口未改：前端 **18765**、API **8765**。

**真实模型 Stage 0 冒烟（代码侧）已完成。** 未跑付费 API；默认 CI 仍不进入该命令。

- 命令：`uv run novel smoke-stage0 --confirm-real-models --budget-usd …`
- 实现：`src/novel_agent/verification/stage0_smoke.py`；CLI 在 `smoke-stage0`。
- 规划仍走紧凑链 `run_planning_chain`（kernel / character / outline），不跑完整 Story Bible R0–R5 / Concept Judge，以免把三章预算打爆。
- 章节循环走生产工厂默认：Writer A+B、5 名基线评审 + reader-advocate、Judge、PASS 后 overlay extract、ContextBuilder `retrieval_facts`。
- 预检按**当前工厂首轮**计价：creative 9（规划 3 + 双写手×3）、review 18（6 角色×3）、judge 3、extract 3。不含修订轮；超支仍由事后 `spent > budget` 与 `max_calls_per_chapter=40` 兜住。
- 硬门：无 `--confirm-real-models` 拒绝；缺/零预算拒绝；任一槽位 mock 拒绝；`judge.family` 必须不同于 `creative.family`；预检必须落入预算。
- pytest 只走 `providers=` 注入的 `MockProvider`，不打网。报告脱敏（无 api_key / 无场景标记泄漏）。
- 退出条件 6 项：三章草稿、植入冲突（仍指回归门）、resume 幂等、修订上限、ModelRun 完整、后章 `retrieval_facts`。

端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。

下一任 **不要** 再改冒烟骨架，除非人工付费跑暴露缺口。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`
2. `uv run ruff check . && uv run mypy src`
3. `cd apps/web && npm ci && npm test && npm run build`

## 仓库地图

| 路径 | 作用 |
|---|---|
| `src/novel_agent/verification/stage0_smoke.py` | 三章真实模型冒烟（gated） |
| `tests/regression/test_stage0_smoke.py` | 门闩 / 离线清单 / 预检锁当前工厂 |
| `eval/retrieval/golden_queries.json` | 冻结检索金标问句 |
| `src/novel_agent/eval/retrieval.py` | 植入语料、打分、报告 |
| `docs/retrieval-eval.md` | hash vs 真实嵌入决策与实测 |
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

## 下一刀建议

1. **人工本地跑付费 Stage 0 冒烟**并审清单（代码侧骨架已齐；本仓未花模型钱）。
2. 付费跑若暴露缺口再开刀；否则转向写作台/长跑体验，不要再改冒烟预检表。

若要动检索本身（评测已冻结）：先用金标试词面权重，再考虑真实嵌入；真实嵌入保持 opt-in。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。
- 默认 plan-more **不**因结构图高潮已锁定就开 v2；要开卷需 `--open-volume` 或把当前单元标成 `locked`。
- `max_calls_per_chapter` 为 40（双写手 + advocate）。
- mock 的 `cost_estimate` 默认为 0；隔夜 mock 请带 `--max-chapters`，USD 硬上限主要约束真实模型。
- LanceDB 表不能从空 list 创建；无事实时直接不建表，检索为空。
- hash 混合在小语料上弱于纯词面：`lexical_overlap` 已能召回的事实会被 hash 向量往后推。
- `stage_provisional`（批次 overlay）不重建检索索引；后章 `retrieval_facts` 主要来自规划期场景/章纲（首次 retrieve 会懒加载 reindex）。正史 `finalize` 才会 `_reindex`。
- Stage 0 冒烟预检只覆盖首轮 happy path，不含 REVISE 轮次。
