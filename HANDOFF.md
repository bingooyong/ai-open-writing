# HANDOFF — 给下一任 Agent

把本文件当作唯一交接入口。先读本文件，再读 `docs/PRD.md` 与 `docs/spec.md`。

## 当前状态（2026-08-13）

**Stage 1 slice 3 已完成：planning adversarial（Concept Judge）+ extra reviewers（Writer B / Reader Advocate）。**

- 工厂：`uv run novel init "书名"` 仍会跑完 R1–R6 + 5 章 PASS（默认 **开启** Concept Judge）。
- 写作台：`GET /projects/{id}/bible` 含 `concept_judge` 与 `settings`；对话面板展示裁决笔记；项目设置可开关 Writer B / Reader Advocate。
- **Concept Judge**：R2（及 R4）后裁决 PASS / REVISE / REJECT。REJECT 不落后续轮次；REVISE 修一轮再判。`--skip-concept-judge` 给 CI。
- **Writer B**：N3 并行第二候选，`agent_role=writer_b`，默认开。
- **Reader Advocate**：N5 并行非关键评审（黄金三章 / 爽点 / 钩子），默认开。
- **Source Reviewer**：仅当存在 `source_record` 表才加入；当前仓库无此表，跳过（不新造存储）。
- 审稿台：展示 **Judge 选中谱系** 的最新稿（含 revision），避免 Writer B 的更高 id 盖住主稿。
- 端口未改：前端 **18765**（strictPort）、API **8765**。禁止 5173。
- 测试：`uv run pytest -q` **218 passed**；`apps/web` vitest **11 passed**。

下一任 **不要** 再做 slice 3。下一刀是 **百万字卷工厂**（滚动大纲超过 5 章）或 **渠道导出模板**。

## 给下一任：先做什么

1. `uv sync && uv run pytest -q`（应 218 passed）
2. `cd apps/web && npm ci && npm test && npm run build`
3. 读 `docs/PRD.md` Stage 1 剩余、`docs/spec.md` §5.5 / §6.3 / §7

## 仓库地图

| 路径 | 作用 |
|---|---|
| `src/novel_agent/planning/adversary.py` | Concept Judge 门禁（PASS/REVISE/REJECT） |
| `src/novel_agent/planning/settings.py` | Writer B / Reader Advocate 开关 |
| `src/novel_agent/planning/conversation.py` | R1–R6；R2/R4 后插 Judge |
| `src/novel_agent/production/loop.py` | N3 Writer B；N5 Reader Advocate；选中谱系 |
| `src/novel_agent/runtime/agents.py` | `run_concept_judge` / `run_reader_advocate` |
| `prompts/concept_judge.md` `prompts/reader_advocate.md` `prompts/source.md` | 新提示词 |
| `apps/web/src/bible/mapConceptJudge.ts` | 对话面板 Judge 笔记 |
| `alembic/versions/e7a1c3d5f902_stage1_concept_judge_settings.py` | `project.concept_judge` + `settings` |

## 本地怎么跑

```bash
uv run alembic upgrade head
uv run uvicorn novel_agent.api.app:app --host 127.0.0.1 --port 8765
cd apps/web && npm run dev   # http://127.0.0.1:18765
```

CLI：`uv run novel init "书名"`（默认开 Judge）；`--skip-concept-judge` 加速。

## 明确不要做

- 不要把前端改回 5173，不要放宽 CORS
- 不要在 pytest 里打付费 API；不要复制 analyzer 源码进本仓
- 不要新建 `source_record` / `timeline_event` 表（本 slice 已声明跳过）
- 不要在没有 Spec 的情况下发明新的存储设计

## 下一刀建议（二选一）

1. **百万字卷工厂**：滚动大纲超过 5 章；卷级 `run_volume`；与现有 5 章 smoke 并存。
2. **渠道导出**：`prompts/channel/*.md` + 导出 API；不改规划图。

## 已知坑

- Writer B 失败不阻断 Writer A。
- Judge 选中谱系：审稿台 `latest_chapter_draft` 跟 verdict 走，不跟 max(id)。
- Concept Judge REVISE 只修一轮；仍非 PASS 则停在该轮。
- `max_calls_per_chapter` 已提到 40（双写手 + advocate）。
