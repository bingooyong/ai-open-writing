# novel-agent

本地优先的 AI 长篇小说创作智能体。阶段 0 为 CLI 工作流；阶段 1 写作台含对话、五级大纲树、批次审稿、关系全景、章节轨、Concept Judge / Writer B / Reader Advocate，以及**卷工厂**（滚动窗口续规划、卷翻转）。

Python 3.11+，用 [uv](https://docs.astral.sh/uv/) 管理依赖。默认四槽位均为 mock，不访问网络、不产生费用。

## 安装

```bash
uv sync
```

复制 `.env.example` 为 `.env` 后按需填写模型槽位。密钥只放环境变量，不要提交。

写作台前端：

```bash
cd apps/web
npm install
```

## 最短 mock 全链路（CLI）

```bash
uv run novel init "说书人传奇" --brief "说书人发现故事会成真" --yes
# 默认开 Concept Judge；CI 可加 --skip-concept-judge
uv run novel write-batch --project-id 1 --chapters 3 --yes
uv run novel plan-more --project-id 1 --yes          # 窗口不足时补下一截章纲
uv run novel write-batch --project-id 1 --from-chapter v1c006 --yes
uv run novel export --project-id 1 --format md --out /tmp/book.md
uv run novel export --project-id 1 --channel qidian --format txt --out /tmp/qidian.txt
uv run novel export --project-id 1 --format epub --out /tmp/book.epub
```

`--yes` 在非 TTY 下跳过人工确认（自动选内核候选 1，PASS 章自动批准并提交正史）。不要把 `.env`、`data/novel.db` 提交进 Git。

其它常用命令：`novel graph --project-id 1 --format mermaid`、`novel write-chapter --project-id 1 --chapter-key v1c001 --yes`、`novel resume --project-id 1 --yes`、`novel review-batch --project-id 1`、`novel edit-outline v1c001 --project-id 1 --out outline.yaml`、`novel plan-more --project-id 1 --yes`（`--open-volume` 开下一卷）、`novel retrieve --project-id 1 --query "西市火灾"`（Stage 2 检索调试）、`novel export --project-id 1 --channel qidian --format txt`（渠道模板；默认只出已锁定章，`--include-drafts` 含草稿）。

## 本地写作台（FastAPI + Vite）

同一 `data/novel.db`，CLI 与 Web 共用 `PlanningRepo` / `BibleRepo` / 生产循环 / `CanonWriter`。CORS 默认只放行 localhost。

两个终端：

```bash
uv run novel serve          # http://127.0.0.1:8765
cd apps/web && npm run dev  # http://localhost:18765 ，Vite 代理 /projects 到 API
```

不要用 Vite 默认端口 5173（会和本机其它服务冲突）。`novel doctor` 会打印 `api_url` 与 `desk_url`。`POST /projects` 带 spark 且 `auto_bible=true`（默认）时，等价于 `novel init --yes`。交互 UI 走 `POST /projects/{id}/bible/rounds/{n}/confirm`。`GET /projects/{id}/bible` 含 `concept_judge` 与 `settings`。项目设置可开关 Writer B / Reader Advocate（默认开）。Source Reviewer 仅当存在 `source_record` 表才加入（当前仓库无此表则跳过）。五级大纲读 `GET /projects/{id}/outline-tree`（从 PlanningRepo 现有行组装，不另存）。窗口不足时 `POST /projects/{id}/plan-more` 续规划；审稿台读 `GET /projects/{id}/review`；批准 / 退回 / `locked_ranges` 走已有编排器。关系全景读 `GET /projects/{id}/graph`（Graph DTO，不调 LLM）。`write-batch` 可带 `from_chapter`，默认跳过已锁定章。

`GET /projects/{id}/retrieve?q=` 返回索引命中（章摘要 / 实体关系 / 场景卡 / 冲突爽点）。写作台章节轨展示「本上下文检索到」。索引是 LanceDB，真源仍是 SQLite。

`GET /projects/{id}/export?channel=qidian|fanqie|generic|epub&format=txt|md|epub` 返回可下载文件。写作台章节轨用渠道 + 格式下拉导出。默认只含 `CANON_LOCKED`；勾选「含草稿」预览未锁定稿。起点/番茄是排版模板，不是官方投稿 API。

本 slice 不含：新 `source_record` / `timeline_event` 表、CI 内百万字实跑、云向量库或付费嵌入、真实起点/番茄登录或抓取。

## 测试

```bash
uv run pytest -q
uv run pytest tests/regression -q   # M4 回归集 R1–R6（mock）
uv run ruff check .
uv run mypy src
cd apps/web && npm test             # Graph DTO → G6、大纲树映射、证据定位
```

默认测试全部走 mock，**不会**调用付费 API。

## 可选：真实模型冒烟（不计默认 CI）

需要四槽位均为真实 provider，且 Judge 与 Writer 不同模型族。默认拒绝执行：

```bash
uv run novel smoke-m26 --confirm-real-models --budget-usd 1.00
uv run novel smoke-chapter --confirm-real-models --budget-usd 1.00
uv run novel smoke-stage0 --confirm-real-models --budget-usd 10.00
```

槽位仍为 mock 或缺价时，命令会跳过并说明原因。报告写入 `artifacts/verification/`，仅含脱敏元数据。正文质量不是通过标准。
