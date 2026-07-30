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
