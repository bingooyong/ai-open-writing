# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-14）

**渠道导出模板已完成：generic / 起点 / 番茄 / 简易 EPUB3。** Stage 2 LanceDB 检索、长跑、写作台仍在。

- 默认只导出 `CANON_LOCKED`（及 `EXPORTED`）章。`--include-drafts` / `include_drafts=true` 含未锁定稿，供写作台预览。
- `novel export --project-id N --channel qidian|fanqie|generic|epub --format txt|md|epub [--out path] [--include-drafts]`
- `--channel` 默认 `generic`（现有 txt/md 版式，清洗工程污染）。`--format epub` 视为 epub 渠道。
- `GET /projects/{id}/export?channel=&format=&include_drafts=` 返回文件。
- 写作台章节轨：渠道 + 格式下拉，可勾选「含草稿」后下载。
- 起点：`第N章 标题` + 空行 + 正文；有卷名或多卷时加 `第X卷 卷名`。番茄：同形章标题，标题后直接接正文，无书名/卷名页。EPUB3 为 zip（`mimetype=application/epub+zip`，一章一个 xhtml）。
- **不是** 起点/番茄官方投稿 API，不登录、不抓取。
- 端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。

下一任 **不要** 再做渠道导出骨架。下一刀是 **检索质量/评测** 或 **真实模型 Stage 0 冒烟**（若他们要）。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`
2. `uv run ruff check . && uv run mypy src`
3. `cd apps/web && npm ci && npm test && npm run build`

## 仓库地图

| 路径 | 作用 |
|---|---|
| `src/novel_agent/production/export.py` | 渠道模板：generic / qidian / fanqie / epub |
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
导出：`uv run novel export --project-id 1 --channel qidian --format txt --out /tmp/book.txt`。

## 明确不要做

- 不要把前端改回 5173，不要放宽 CORS
- 不要在 pytest 里打付费 API / 付费嵌入；不要复制 analyzer 源码进本仓
- 不要在 CI 里真的生成百万字
- 不要新建 `source_record` / `timeline_event` 表
- 不要训练自定义模型、不要上云向量库

## 下一刀建议（二选一）

1. **检索质量/评测**：固定问句集、命中率、以及是否值得换真实嵌入。
2. **真实模型 Stage 0 冒烟**：`novel smoke-stage0 --confirm-real-models --budget-usd …`（不计默认 CI）。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。
- 默认 plan-more **不**因结构图高潮已锁定就开 v2；要开卷需 `--open-volume` 或把当前单元标成 `locked`。
- `max_calls_per_chapter` 为 40（双写手 + advocate）。
- mock 的 `cost_estimate` 默认为 0；隔夜 mock 请带 `--max-chapters`，USD 硬上限主要约束真实模型。
- LanceDB 表不能从空 list 创建；无事实时直接不建表，检索为空。
