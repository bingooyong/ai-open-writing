# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-13）

**卷工厂已完成：滚动窗口续规划、卷翻转、write-batch 续写。**

- `novel plan-more --project-id N` / `POST /projects/{id}/plan-more`：当已规划但未锁定的章少于窗口（默认 5）时，生成下一截章纲 + 场景卡，引用冲突/爽点并跑 bible lint（含爽点间距、孤儿冲突、禁释继承）。
- 默认续写当前卷（5 章锁定后补 `v1c006`…，必要时新开 `u2`）。`--open-volume` 或当前单元 `status=locked`（单元收束夹具）时开 `v2`，新 `PlotUnitCard` 仍指向同一内核与三幕图，不重跑 Story Bible 对话。
- 后续章纲继承既有 `reveal_forbidden` / `reveal_allowed`；规划上下文带上已提交正史 + D15 provisional overlay。
- `write-batch` 先跳过 `CANON_LOCKED`/`EXPORTED`，可用 `--from-chapter` / `from_chapter` 从指定章续写。`resume` 仍不重跑 SUCCESS 节点。D15 STALE 级联按 `order_index` 作用于更长窗口。
- 写作台：大纲树展示多卷；「续规划」调用 plan-more；章节轨「写下一批」写下一截 3 章。
- 端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。

下一任 **不要** 再做卷工厂。下一刀可以是 **长跑运维**（卷级预算、隔夜批次）或 **Stage 2 检索**。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`
2. `uv run ruff check . && uv run mypy src`
3. `cd apps/web && npm ci && npm test && npm run build`

## 仓库地图

| 路径 | 作用 |
|---|---|
| `src/novel_agent/planning/volume.py` | `plan_more` / 滚动窗口 / 卷翻转 / 批次选章 |
| `src/novel_agent/lint/bible.py` | 禁释继承 lint；孤儿冲突对**全部**已规划章键 |
| `src/novel_agent/production/batch.py` | `from_chapter`；跳过已锁定再取 N 章 |
| `src/novel_agent/planning/mock_fixtures.py` | 按计划章节键生成后续冲突/爽点/章纲 |
| `apps/web/src/outline/OutlineTree.tsx` | 「续规划」按钮 |
| `tests/contract/test_volume_factory.py` | 卷工厂契约（mock） |

## 本地怎么跑

```bash
uv run alembic upgrade head
uv run uvicorn novel_agent.api.app:app --host 127.0.0.1 --port 8765
cd apps/web && npm run dev   # http://127.0.0.1:18765
```

CLI：`uv run novel init "书名" --yes` 后 `novel write-batch --project-id 1 --yes`；章锁定后 `novel plan-more --project-id 1 --yes`，再 `novel write-batch --project-id 1 --from-chapter v1c006 --yes`。开新卷加 `--open-volume`。

## 明确不要做

- 不要把前端改回 5173，不要放宽 CORS
- 不要在 pytest 里打付费 API；不要复制 analyzer 源码进本仓
- 不要在 CI 里真的生成百万字
- 不要新建 `source_record` / `timeline_event` 表
- 不要做渠道导出模板（仍属后续切片）

## 下一刀建议（二选一）

1. **长跑运维**：卷级预算、隔夜批次、失败续跑仪表。
2. **Stage 2 检索**：在现有 Canon / 章纲上做检索，不新造 LanceDB 除非 Spec 要求。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。
- 默认 plan-more **不**因结构图高潮已锁定就开 v2；要开卷需 `--open-volume` 或把当前单元标成 `locked`。
- `max_calls_per_chapter` 为 40（双写手 + advocate）。
