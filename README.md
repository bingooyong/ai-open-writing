# novel-agent

本地优先的 AI 长篇小说创作智能体（阶段 0：无 UI 工作流验证）。

Python 3.11+，用 [uv](https://docs.astral.sh/uv/) 管理依赖。默认四槽位均为 mock，不访问网络、不产生费用。

## 安装

```bash
uv sync
```

复制 `.env.example` 为 `.env` 后按需填写模型槽位。密钥只放环境变量，不要提交。

## 最短 mock 全链路

```bash
uv run novel init "说书人传奇" --brief "说书人发现故事会成真" --yes
uv run novel write-batch --project-id 1 --chapters 3 --yes
uv run novel export --project-id 1 --format md --out /tmp/book.md
```

`--yes` 在非 TTY 下跳过人工确认（自动选内核候选 1，PASS 章自动批准并提交正史）。不要把 `.env`、`data/novel.db` 提交进 Git。

其它常用命令：`novel graph --project-id 1 --format mermaid`、`novel write-chapter --project-id 1 --chapter-key v1c001 --yes`、`novel resume --project-id 1 --yes`、`novel review-batch --project-id 1`、`novel edit-outline v1c001 --project-id 1 --out outline.yaml`。

## 测试

```bash
uv run pytest -q
uv run pytest tests/regression -q   # M4 回归集 R1–R6（mock）
uv run ruff check .
uv run mypy src
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
