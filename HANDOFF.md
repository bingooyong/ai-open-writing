# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-14）

**Stage 2 检索已完成：`MemoryRetrieval` 协议 + 本地 LanceDB 索引 + ContextBuilder 注入。**

- SQLite 仍是工作流 / canon 真源。检索只是索引，不是第二本圣经。
- 默认实现：项目旁 `memory/lancedb`（LanceDB）。嵌入默认 hash/mock，pytest 无网络；真实嵌入走 `NOVEL_EMBEDDING__*`，精神同模型槽位。
- 索引对象：已提交（及标记好的提案态）章摘要、实体/关系事实、场景卡、冲突/爽点一句话。不索引 `.env`、密钥或正文全文。
- `ContextBuilder.build` 在未显式传入 `retrieval_facts` 时经协议填充。提示词顺序：硬约束 → 检索事实 → 近文窗口。超预算仍先裁检索。
- 重建索引：`CanonWriter.finalize` 成功后、`plan-more` 写入新章纲后。幂等。
- `novel retrieve --project-id N --query "..."`；`GET /projects/{id}/retrieve?q=`。写作台章节轨展示「本上下文检索到」。
- 端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。

下一任 **不要** 再做 Stage 2 检索骨架。下一刀是 **渠道导出** 或 **检索质量/评测**。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`
2. `uv run ruff check . && uv run mypy src`
3. `cd apps/web && npm ci && npm test && npm run build`

## 仓库地图

| 路径 | 作用 |
|---|---|
| `src/novel_agent/memory/` | `MemoryRetrieval` 协议、hash 嵌入、LanceDB 索引、收集器 |
| `src/novel_agent/context/context_builder.py` | 组装包并填充 `retrieval_facts` |
| `src/novel_agent/domain/canon_writer.py` | 正史提交成功后重建索引 |
| `src/novel_agent/planning/volume.py` | `plan-more` 新章纲后重建索引 |
| `tests/unit/test_memory_retrieval.py` | 植入事实命中 / 幂等 / 预算裁剪 |

## 本地怎么跑

```bash
uv run alembic upgrade head
uv run uvicorn novel_agent.api.app:app --host 127.0.0.1 --port 8765
cd apps/web && npm run dev   # http://127.0.0.1:18765
```

CLI：`uv run novel retrieve --project-id 1 --query "西市火灾"`。

## 明确不要做

- 不要把前端改回 5173，不要放宽 CORS
- 不要在 pytest 里打付费 API / 付费嵌入；不要复制 analyzer 源码进本仓
- 不要在 CI 里真的生成百万字
- 不要新建 `source_record` / `timeline_event` 表
- 不要训练自定义模型、不要上云向量库

## 下一刀建议（二选一）

1. **渠道导出**：按渠道模板导出已锁定正文。
2. **检索质量/评测**：固定问句集、命中率、以及是否值得换真实嵌入。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。
- 默认 plan-more **不**因结构图高潮已锁定就开 v2；要开卷需 `--open-volume` 或把当前单元标成 `locked`。
- `max_calls_per_chapter` 为 40（双写手 + advocate）。
- mock 的 `cost_estimate` 默认为 0；隔夜 mock 请带 `--max-chapters`，USD 硬上限主要约束真实模型。
- LanceDB 表不能从空 list 创建；无事实时直接不建表，检索为空。
