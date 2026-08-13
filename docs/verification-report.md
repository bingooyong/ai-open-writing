# 开工前核验报告(Plan §M0.3/M0.4,Spec §11)

> 日期:2026-07-27 | 结论:**G0 门禁通过,可以开工**

## V1 — AgentScope ✅

| 项 | 结论 | 证据 |
|---|---|---|
| 当前稳定版本 | **2.0.5**(2026-07-23 发布) | PyPI `agentscope` JSON API |
| 2.0 系列状态 | 2026-05-26 通义实验室正式发布 2.0,已迭代 2.0.0→2.0.5,趋稳 | 通义实验室发布消息(2026-05-26)、PyPI 版本序列 |
| Python 要求 | `>=3.11`,与 Spec D1 一致 | PyPI metadata |
| 许可证 | **Apache-2.0**,商用/修改无阻塞 | PyPI metadata |
| 能力核对 | 事件流、权限系统、沙箱工作区、人机协作、ReAct、实时介入均在 2.0 公告中确认,与 PRD §14.2 描述一致 | 2.0 发布报道与社区文档 |
| 仓库 | `github.com/agentscope-ai/agentscope`(由 modelscope/agentscope 迁移) | GitHub |
| 锁定决策 | pyproject 锁 `agentscope==2.0.5`;升级须过回归集(PRD §17.3) | — |
| 待办(M2.4 前) | ~~并发评审 API 形态确认~~ **已实测(2026-07-27)**:2.0.5 的 `agentscope.agent.Agent` 为 ReAct 自主循环 Agent(toolkit/context 管理/reply),面向工具型自主任务;阶段0 的评审/裁判是单次调用+独立上下文+严格 IO 的认知任务,直接套用会引入不可控自主性(PRD §14.2 警告项)。**执行 G0 预设 fallback**:agent 层以 asyncio.gather 自管并发实现于 `runtime/`,全部调用仍走 ModelGateway(D7);AgentScope 保留为锁定依赖,其 `ChatModelBase`/`Msg` 适配缝已勘察(接口签名存档于本节),P1 需要 middleware/permission/studio 能力时按缝接入 | 实测脚本输出 |

## V2 — oh-story-claudecode ✅

MIT 许可(PRD §2.2 已确认)。阶段0 仅吸收方法论(写前守卫/滚动细纲/状态追踪),不复制其文件,无许可证义务触发。若未来复制代码/提示词文件,须保留 LICENSE 与 NOTICE(Spec/PRD §14.4)。

## V3 — 模型槽位 ⏸(不阻塞)

四槽位(creative/review/judge/extract)供应商与型号**待用户确认**;开发全程 mock provider 先行,真实模型只在 M2.6/M3.3 冒烟与 M4.2 验收使用。约束:judge 与 creative 须不同模型族(Spec D8)。

## V4 — Python 版本 ✅

AgentScope 2.0.5 要求 ≥3.11;本机 uv 0.11.14 可自动管理解释器,项目锁 `.python-version=3.12`(3.11~3.13 本机均有,取中间版本稳妥)。

---
*后续核验追加写入本文件(M2.4 API 实测、M4.2 验收证据索引)。*

## M2.6 受限真实模型 smoke

`novel smoke-m26` 默认拒绝。只有同时提供 `--confirm-real-models` 与正数
`--budget-usd` 才会继续；四槽位必须均为真实 provider，真实槽位必须声明
`family`，且 judge 与 creative 的 family 必须不同。未知型号必须在槽位中显式
配置每百万 input/output token 价格。

命令在任何 provider 调用前对 12 个 prompt role 做全程最坏成本预检，运行中每次
调用前再核验剩余硬预算和逐角色调用上限；普通角色最多 2 次，评审角色最多 4 次
(仍低于 M2.6 要求的每角色 5 次上限)。报告默认写入
`artifacts/verification/m26-smoke-<timestamp>.json`，仅包含脱敏元数据、版本引用、
token/成本/延迟、Schema 校验状态、中文 evidence 定位计数与正文哈希。
评审可以返回零个 issue；但只要存在 issue，其所有 evidence span 都必须能在
对应场景正文中定位，否则 smoke 失败并保留脱敏报告。

### G001 M2.6 真实模型验收（2026-08-12）

- 脱敏报告：`artifacts/verification/g001-minimax-evidence-repair6.json`
- run id：`20260812T154730321414Z`
- 结果：12 个 prompt role 全部完成，`missing_roles=[]`；18 条 ModelRun 均含
  prompt version、输入/输出 token、延迟、成本及非空输入/输出版本引用。
- 结构化输出：每个角色的最终调用均通过 Schema 或两段式输出校验；修复调用仍受
  逐角色上限控制（普通角色 2 次，评审角色 4 次，均不超过 M2.6 的 5 次上限）。
- 中文 evidence：RedTeam/Plot/Character/Continuity/Prose 的未定位计数均为 0；
  Plot 的 2 条和 Prose 的 1 条 issue 引文均能定位，零 issue 的评审按契约允许。
- 预算：保守预检 `$0.984`，硬上限 `$1.00`，实际成本 `$0.096965`。
- 脱敏审计：报告未包含密钥、完整提示词、待审正文或原稿。
- 完成后基线：`113 passed`；Ruff 全绿；mypy 对 44 个 source files 全绿。

## M4 阶段0 mock 验收（2026-08-13）

回归集走现有 `run_chapter_loop` / `lint_draft` / `run_judge`，默认 pytest 不调用付费 API。

### M4.1 回归集

`tests/regression/samples/` 六个微型项目（kernel + 角色 + 章纲 + 植入稿 + 期望裁决）：

| 样本 | 植入 | mock 结果 | 误杀/漏杀 |
|---|---|---|---|
| R1 | 已死角色苏晚梅现身 | Judge `REPLAN_SCENE`，`rollback_target=scene_card` | 无漏杀 |
| R2 | POV 使用章纲禁止的书局主人真名 | Judge `REPLAN_SCENE`，`rollback_target=scene_card` | 无漏杀 |
| R3 | 未铺垫的签约结果 | Judge `REPLAN_CHAPTER`，`rollback_target=chapter_outline` | 无漏杀 |
| R4 | 正文残留 `{"issue_id": ...}` | N4 lint 拦截，`stopped_at=n4_lint`，评审/Judge 零调用 | 工程污染未进入评审 |
| R5 | 无证据 P0 正史冲突意见 | 代码 `downweighted`；Judge 原裁决被 `sanitize_verdict` 降为 PASS | 无证据项未采纳为阻断 |
| R6 | 干净稿 | PASS → `CANON_LOCKED` | 无误杀 |

### M4.3 Judge 校准

- R5：空 evidence 的硬门禁意见进入 Judge，但不得留在 `hard_gate_failures` / `accepted` 阻断集。
- R6：干净样本不被误杀。
- 匿名化：Judge 的 `system`+`user` 不含 `writer_a` / `reviewer_role` / `mock-model` 及 `DEFAULT_FORBIDDEN` 模型族前缀。

### M4.2 真实模型三章冒烟（非 CI）

`novel smoke-stage0 --confirm-real-models --budget-usd N` 默认拒绝。四槽位任一为 mock 或未定价则跳过并说明（不发起付费调用）。报告写入 `artifacts/verification/stage0-smoke-*.json`，清单对齐 Spec §1.3 五条退出条件；正文质量不是通过标准。本里程碑未跑付费三章，证据以 mock 回归集为准。

### 完成后基线

`193 passed`（含 `tests/regression` 17）；Ruff 全绿；mypy 对 67 个 source files 全绿。

