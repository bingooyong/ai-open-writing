# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-13）

**长跑运维已完成：卷级预算、隔夜 `run-volume`、失败续跑状态。**

- `novel run-volume --project-id N --yes --budget-usd <正数> [--max-chapters N] [--open-volume]`：无人值守循环。窗口不足时 `plan-more`，再写下一截未锁定章；`CANON_LOCKED` 不重跑。
- 硬 USD 上限（真实模型须有单价）；mock 仍必须带正数 `--budget-usd`，并沿用单章 `max_calls_per_chapter`。停在预算、`HUMAN_REVIEW`、`NEEDS_REPLAN`、`STALE`、`max-chapters`。
- 进程被杀后：`novel resume` 或再次 `run-volume` 从最后 SUCCESS 节点续跑，不重写已锁定章。
- `POST /projects/{id}/run-volume` 后台执行；`GET /projects/{id}/run-volume` 返回 chapters_done / spent_usd / stop_reason。写作台「跑一卷」轮询，不堵 UI。
- 端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。

下一任 **不要** 再做长跑运维。下一刀是 **Stage 2 检索** 或 **渠道导出**。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`
2. `uv run ruff check . && uv run mypy src`
3. `cd apps/web && npm ci && npm test && npm run build`

## 仓库地图

| 路径 | 作用 |
|---|---|
| `src/novel_agent/production/volume_run.py` | `run_volume` 隔夜循环 / 停因 / 进程内互斥 |
| `src/novel_agent/planning/volume.py` | `plan_more` / 滚动窗口 / 卷翻转 / 批次选章 |
| `src/novel_agent/production/batch.py` | `from_chapter`；跳过已锁定再取 N 章 |
| `src/novel_agent/production/loop.py` | 单章 N1→N9；resume 不重跑 SUCCESS 节点 |
| `apps/web/src/App.tsx` | 「跑一卷」+ 进度 / 停因 |
| `tests/contract/test_run_volume.py` | 长跑契约（mock） |

## 本地怎么跑

```bash
uv run alembic upgrade head
uv run uvicorn novel_agent.api.app:app --host 127.0.0.1 --port 8765
cd apps/web && npm run dev   # http://127.0.0.1:18765
```

CLI：`uv run novel init "书名" --yes` 后 `novel run-volume --project-id 1 --yes --budget-usd 1 --max-chapters 8`。

## 明确不要做

- 不要把前端改回 5173，不要放宽 CORS
- 不要在 pytest 里打付费 API；不要复制 analyzer 源码进本仓
- 不要在 CI 里真的生成百万字
- 不要新建 `source_record` / `timeline_event` 表
- 不要做渠道导出模板（仍属后续切片）

## 下一刀建议（二选一）

1. **Stage 2 检索**：在现有 Canon / 章纲上做检索，不新造 LanceDB 除非 Spec 要求。
2. **渠道导出**：按渠道模板导出已锁定正文。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。
- 默认 plan-more **不**因结构图高潮已锁定就开 v2；要开卷需 `--open-volume` 或把当前单元标成 `locked`。
- `max_calls_per_chapter` 为 40（双写手 + advocate）。
- mock 的 `cost_estimate` 默认为 0；隔夜 mock 请带 `--max-chapters`，USD 硬上限主要约束真实模型。
