# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-14）

**检索质量/评测已完成。** 渠道导出模板、Stage 2 LanceDB 检索、长跑、写作台仍在。

- 冻结金标：`eval/retrieval/golden_queries.json`（14 问，覆盖人物/关系/场景/冲突/爽点/摘要，含改写与暗示）。
- 离线 runner：`novel_agent.eval.retrieval` 植入确定性项目、重建索引、对每问调用生产 `MemoryRetrieval.retrieve`。
- 指标：recall@1/3/8、hit_rate、MRR；另报词面-only 对照。报告 stdout + `--out`（默认 `reports/retrieval-eval.md`）。
- CLI：`novel retrieve-eval [--golden PATH] [--out PATH] [--compare-real]`。默认强制 `HashEmbedding`，不访问网络。`--compare-real` 仅当 `embedding.provider=openai_compat` 已配置。
- pytest 锁文档化下限，见 `docs/retrieval-eval.md`。
- **决策：默认继续 mock/hash，不换成真实嵌入。** hash 混合已过下限；词面-only 更好，说明短板是 hash 向量噪声，不是缺付费语义模型。

端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。

下一任 **不要** 再做检索评测骨架。下一刀是 **真实模型 Stage 0 冒烟**。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`
2. `uv run ruff check . && uv run mypy src`
3. `cd apps/web && npm ci && npm test && npm run build`

## 仓库地图

| 路径 | 作用 |
|---|---|
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

## 明确不要做

- 不要把前端改回 5173，不要放宽 CORS
- 不要在 pytest 里打付费 API / 付费嵌入；不要复制 analyzer 源码进本仓
- 不要在 CI 里真的生成百万字
- 不要新建 `source_record` / `timeline_event` 表
- 不要训练自定义模型、不要上云向量库

## 下一刀建议

1. **真实模型 Stage 0 冒烟**：`novel smoke-stage0 --confirm-real-models --budget-usd …`（不计默认 CI）。

若要动检索本身（本切片已冻结评测）：先用金标试词面权重，再考虑真实嵌入；真实嵌入保持 opt-in。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。
- 默认 plan-more **不**因结构图高潮已锁定就开 v2；要开卷需 `--open-volume` 或把当前单元标成 `locked`。
- `max_calls_per_chapter` 为 40（双写手 + advocate）。
- mock 的 `cost_estimate` 默认为 0；隔夜 mock 请带 `--max-chapters`，USD 硬上限主要约束真实模型。
- LanceDB 表不能从空 list 创建；无事实时直接不建表，检索为空。
- hash 混合在小语料上弱于纯词面：`lexical_overlap` 已能召回的事实会被 hash 向量往后推。
