# AI 长篇小说创作智能体 — 工程实施 Spec(阶段0 + 阶段1)

> 状态:v1.0 — 已完成对抗评审(裁决 APPROVE_WITH_FIXES)并逐条修订
> 日期:2026-07-27
> 上游文档:`docs/AI_Novel_Agent_PRD_Architecture.md`(V2.2,下称 PRD;引用记为 `PRD §n`)
> 本 Spec 定位:把 PRD 蓝图收敛为**可开工的工程规格**。凡 PRD 已定义且无歧义的内容只引用不复述;本文只写落地决策、边界与验收。

---

## 1. 范围与边界

### 1.1 本期做(In Scope)

| 阶段 | 内容 | 对应 PRD |
|---|---|---|
| **阶段0:无 UI 工作流验证**(本 Spec 主体) | AgentScope 多 Agent 单章生产循环原型 + SQLite 持久化 + CLI 人工门禁 | PRD §21 阶段0 |
| **阶段1:本地 MVP**(本 Spec 只给概要,详细任务在阶段0退出后再规划) | FastAPI + Web 写作台 + 五级大纲树 + 批次审阅 + 导出 | PRD §21 阶段1 |

### 1.2 本期不做(Out of Scope,硬边界)

- PRD §4.3 全部非目标(自动发布、检测器对抗、批量账号、微调、K8s 等)。
- PRD §15.3 全部"不建议首期引入"清单(双 Runtime、PostgreSQL/Redis、Kafka 等)。
- LanceDB 语义检索:**推迟到阶段2**(见 §3 决策 D4)。阶段0/1 检索用结构化字段查询 + 最近窗口 + 分层摘要即可满足 3~5 章与单卷范围。
- P1/P2 产品功能(关系图、伏笔台账 UI、朱雀记录页、多模型 A/B 等)。

### 1.3 成功判据(阶段0 退出条件,逐字对齐 PRD §21)

1. 从项目创意出发,能生成**三章相互连贯的待审稿**。连贯性按客观清单判定:①后章上下文包实际包含前章事实;②跨章实体状态无冲突;③终稿无未关闭的 P0 连续性 issue;④人工通读签字。
2. **人为植入的硬冲突**(正史冲突/信息越权/因果断裂各≥1 个回归样本)能被评审举证,并被 Judge 阻断,不得放行至 `HUMAN_REVIEW` 通过态。
3. **任一节点可重跑**:杀掉进程后从最后成功节点恢复,且不重复提交正史。
4. 两轮修订上限生效:第二轮仍有硬门禁失败 → 自动 `HUMAN_REVIEW`。
5. 全链路每次模型调用有 ModelRun 记录(Token/耗时/成本/提示词版本)。

---

## 2. 锁定的工程决策(Decision Log)

PRD 给了方向,以下是本 Spec 拍板的落地决策。改动任何一条须回到本表记录理由。

| # | 决策 | 理由 |
|---|---|---|
| D1 | 语言/运行时:**Python 3.11+,uv 管理依赖,单仓 monorepo** | 与 AgentScope 生态一致(PRD §15.1);uv 锁定可复现 |
| D2 | Agent Runtime:**AgentScope(以开工时最新稳定版为准,M0 核验后锁定)** | PRD §14.2;版本号必须经核验项 V1 确认,不盲信"2.0"字样 |
| D3 | 工作流:**自研表驱动 FSM,不用 AgentScope Plan 做控制流** | PRD §11 "显式工作流管状态,AgentScope 管 Agent" |
| D4 | 阶段0/1 **不引入 LanceDB**,检索走 SQLite 结构化查询+摘要;`memory_retrieval` 留接口 | 3~5 章批次与单卷范围内,实体状态查询足够;避免过早引入第二存储。PRD §15.1 允许(全文硬查询本就走结构化字段) |
| D5 | ORM:**SQLModel + Alembic**;所有跨 Agent 交换对象用 **Pydantic v2 Schema** | PRD §15.1、§11(Pydantic 校验) |
| D6 | 阶段0 交互:**Typer CLI**(`novel` 命令),人工门禁=CLI 交互确认 | 阶段0 无 UI(PRD §21) |
| D7 | 模型接入:**自研轻量模型网关**(`ModelGateway` 协议 + provider 适配器 + mock provider),不直接在 Agent 内调 SDK | PRD §15.2 统一接口;mock provider 支撑离线测试 |
| D8 | 角色-模型路由:`creative_model` / `review_model` / `judge_model` / `extract_model` 四槽位,env 配置;Judge 与 Writer **必须不同模型族**,预算不足时至少独立上下文 | PRD §9.4 规则7、§15.2 |
| D9 | 正文与元数据**物理分离**:正文存 `DraftVersion.content`(纯文本),结构化产物(摘要/CanonDelta 提案/偏离说明)独立字段 | PRD §8.4 |
| D10 | 正史写入:**单写入器**(`CanonWriter`),仅在 Approval 存在后以单事务提交 CanonDelta;任何 Agent 无直接写权 | PRD §2.12、§9.1 |
| D11 | 盲化/匿名化在**应用层代码**实现(候选稿重命名、评审报告剥离 agent/model 字段),不依赖提示词自觉 | PRD §9.4 规则2 |
| D12 | Git:M0 第一件事 `git init` + 初始提交;**每章 canon 提交即 commit 检查点**,批次导出后再加一个批次检查点;git 操作失败只告警重试、不回滚已提交的 canon 事务 | PRD §2.12 第5步(逐章)与 §11(逐批次)原文不一致,此处拍板取并集;当前目录尚非 git 仓库 |
| D13 | 阶段0 即包含**最小 TXT/Markdown 导出**(CLI),便于退出条件1的人工检验 | 成本极低,直接服务验收 |
| D14 | 提示词即代码:`prompts/` 下按角色分文件,YAML frontmatter 记版本/适用模型/IO Schema 引用;提示词变更必须跑回归集 | PRD §16 末段 |
| D15 | **批次连跑 canon 语义(provisional overlay)**:批次内后章的上下文包可读取前章**提案态** canon 快照(标记 `provisional`);前章在人工门禁被退回时,基于其 provisional 事实构建的后章一律置 `STALE` 强制重跑(级联失效)。已提交(canon)与提案态(provisional)在上下文包中显式区分 | 消解"三章连贯"与 PRD §2.12"未批准草稿不得污染后续上下文"的正面冲突:污染被允许但**可追踪、可级联撤销**;此项属领域决策,开工前需用户确认 |
| D16 | **Writer/Reviser 两段式输出协议**:正文按场景以纯文本分段输出,结构化元数据(摘要/canon 提案/偏离说明)独立 JSON 输出,gateway 层组装为 DraftCandidate | 长中文正文进 JSON 的转义/截断失败率高;D9 只解决了存储分离,传输层必须同样分离 |

---

## 3. 系统架构(阶段0 收敛版)

```
┌─────────────────────────────────────────────────────┐
│ CLI (Typer): novel init / plan / write-batch /       │
│              review-batch / approve / export / resume│
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────┐   ┌───────────────────┐
│ Workflow Controller (自研FSM)│──▶│ SQLite (真源)      │
│ 节点调度·门禁·预算·两轮上限· │   │ 业务表+WorkflowRun/ │
│ 幂等·租约·恢复               │   │ NodeRun+快照        │
└──────────────┬──────────────┘   └───────────────────┘
               │ 任务包(Pydantic)
┌──────────────▼──────────────────────────────────────┐
│ AgentScope Runtime                                   │
│  writing_team: Writer A (B 条件启用)                 │
│  review_team : RedTeam + Plot/Character/Continuity/  │
│                Prose Reviewer(并行,独立上下文)      │
│  judgment    : Judge                                 │
│  revision    : Reviser                               │
│  canon       : Canon Curator(仅提案)               │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────┐   ┌───────────────────┐
│ ModelGateway                 │   │ 项目包导出          │
│ 四槽位路由·重试·成本记录·mock│   │ Markdown/YAML/JSON │
└─────────────────────────────┘   │ + Git 检查点        │
                                  └───────────────────┘
```

要点(均为 PRD 既定原则的工程化):
- Controller 与 AgentScope 之间只交换 Pydantic 对象;AgentScope 私有类型不出 `services/agent_*` 边界(PRD §16)。
- Context Curator 在阶段0 由**代码实现**(确定性组装 `ChapterContextPackage`,按 PRD §12.2 顺序),不消耗 LLM 调用;Producer/Orchestrator 职责由 Workflow Controller 承担,不设 LLM Agent。
- 确定性 Lint(重复 n-gram、格式、工程污染正则、禁写词)在评审前执行,代码实现零模型成本(PRD §9.2 末条)。

## 4. 仓库结构(对 PRD §16 的阶段0裁剪)

```
ai-open-writing/
  pyproject.toml  uv.lock  alembic/  .env.example
  src/novel_agent/
    cli/                    # Typer 入口
    workflow/               # FSM: states.py transitions.py runner.py lease.py budget.py
    agents/                 # base.py writer.py red_team.py reviewers.py judge.py reviser.py canon_curator.py
    runtime/                # AgentScope 初始化、消息适配、盲化/匿名化
    gateway/                # ModelGateway 协议、providers/(openai_compat.py anthropic.py mock.py)、cost.py
    context/                # context_builder.py(ChapterContextPackage 组装)
    lint/                   # 确定性检查:重复、格式、污染、禁写项
    domain/
      schemas/              # Pydantic: kernel.py character.py outline.py scene.py draft.py
                            #          review_issue.py judge_verdict.py canon_delta.py context_package.py
      models/               # SQLModel 表
      repos/                # 仓储层(唯一 SQL 入口)
      canon_writer.py       # 单写入器
    export/                 # txt.py markdown.py project_package.py
  prompts/                  # planning/ writing/ red_team/ reviewers/ judge/ revision/(YAML frontmatter 版本化)
  tests/
    unit/  contract/        # 每个 Agent IO Schema 契约测试(mock gateway)
    workflow/               # FSM/幂等/恢复
    regression/samples/     # 植入冲突回归集(§8)
    judge_calibration/
  docs/
```

阶段1 增量:`src/novel_agent/api/`(FastAPI)与 `apps/web/`,不影响上述结构。

## 5. 领域模型(P0 最小集)

**建表**(SQLModel;字段细节以 PRD §13.1 为准,此处仅锁定"哪些表进阶段0"):

`project, story_kernel, reader_contract, character, character_arc, relationship_state, volume, plot_unit, chapter, scene, draft_version, review_issue, judge_verdict, canon_delta, entity_state, plot_thread, approval, model_run, workflow_run, node_run`

**阶段0 不建**:`creative_brief, timeline_event, source_record, export_package, story_bible(版本表)` —— 立项信息并入 project JSON 字段;时间线/来源管理属阶段2;导出阶段0 只产文件不建表。story_bible 阶段0 以「kernel + character + relationship + entity_state + plot_thread + 世界规则(project.world_rules JSON)」的组合视图存在,阶段1 再抽独立版本表。

**关键 Pydantic Schema**(跨 Agent 契约,全部带 `schema_version` 字段):
- `StoryKernel`(PRD §2.5 YAML)、`CharacterCard`(§2.6)、`PlotUnitCard`(§2.7)、`ChapterOutline`(§2.9)、`SceneCard`(§2.9 YAML)
- `ChapterContextPackage`(§2.10 清单 + §12.2 组装顺序)
- `DraftCandidate`(candidate_id 盲化名、scenes[]、chapter_summary、canon_proposals、deviation_notes)
- `ReviewIssue`(§9.3 红队 YAML 全字段:claim/evidence/violated_rule/severity/failure_consequence/recommended_rollback_level/confidence;evidence 必须含正文定位)
- `JudgeVerdict`(§9.4 YAML 全字段;verdict 五枚举)
- `CanonDelta`(§2.12 YAML 全字段)
- `RevisionOrder`(Judge → Reviser 的授权范围:issue_ids、scope 段落/场景、locked_strengths)

**评审后补充的数据落点(修订新增)**:
- `chapter.revision_round`:两轮修订计数持久化字段(语义见 §6 N7),kill+resume 后不得归零。
- `draft_version.locked_ranges`:锁定段落(场景 id+段落区间),Reviser 与人工"段落指令重写"共用。
- 盲化映射(candidate_id ↔ Writer 实体/模型):存入 N3 节点的 NodeRun 快照,Judge 选定后由代码解盲,不进任何 Agent 上下文。
- `ReviewIssue.evidence` 定位结构:`scene_id + 原文引文`;引文与正文匹配采用归一化(去空白/标点)模糊阈值,不要求逐字节相等。
- **CanonDelta 字段 → 目标表映射**:

| CanonDelta 字段 | 阶段0 落点 |
|---|---|
| character_state_changes / resource_changes / knowledge_changes / new_facts | `entity_state`(以 state_type 区分:position/ability/resource/knowledge/fact) |
| relationship_changes | `relationship_state` |
| foreshadowing_created / progressed / resolved | `plot_thread`(status 迁移) |
| world_rule_proposals | `project.world_rules` JSON(带变更记录) |
| timeline_events | 阶段0 仅保留在 `canon_delta` 原始记录中,**不参与结构化冲突校验**(timeline_event 表属阶段2) |

## 6. 工作流状态机

**章节状态**(逐字采用 PRD §8.9):
`PLANNED → DRAFTING → ADVERSARIAL_REVIEW → JUDGING → (NEEDS_REVISION | NEEDS_REPLAN | HUMAN_REVIEW) → HUMAN_REVIEW → APPROVED → CANON_LOCKED → EXPORTED`

**节点图**(单章,对应 PRD §10 流程图):

| 节点 | 执行者 | 幂等键 | 失败策略 |
|---|---|---|---|
| N1 validate_outline | 代码(写前守卫:无章纲/场景卡即拒绝进入 DRAFTING) | chapter_id+outline_ver | 硬失败→人工 |
| N2 build_context | 代码 ContextBuilder | chapter_id+canon_ver | 重试3 |
| N3 draft | Writer A(关键章 +B 并行) | chapter_id+outline_ver+attempt | 重试2(模型级) |
| N4 lint | 代码 | draft_ver | 重试1 |
| N5 parallel_review | 4 Reviewer + RedTeam(AgentScope 并发,各自独立上下文) | draft_ver+reviewer | **Continuity 与 RedTeam 不可缺席**(任一失败→节点失败);其余评审单缺席不阻断,缺席清单随 issue 集显式传入 Judge;NodeRun 按 reviewer 子记录粒度落快照,resume 只补跑缺失的 reviewer |
| N6 judge | Judge(输入:盲化候选+匿名化报告+缺席清单) | draft_ver+review_set_hash | 重试1;Schema 修复1次后仍非法→HUMAN_REVIEW |
| N7 revise | Reviser(仅 RevisionOrder 范围) | verdict_id | 回 N4;**轮次语义:同一 draft 谱系内 REVISE_LOCAL 裁决计数 ≤2**(持久化于 chapter.revision_round);REPLAN 产生新谱系→计数重置;第二轮后仍有硬门禁失败→HUMAN_REVIEW |
| N8 human_gate | CLI 批准/退回/改指令 | — | 阻塞等待 |
| N9 canon_commit | CanonWriter(事务:校验冲突→写 canon→Git 检查点) | canon_delta_id | 事务回滚;幂等(重复提交检测) |

**通用机制**:每节点执行前后写 `NodeRun`(input_snapshot/output_snapshot JSON、attempt、lease_until、budget_spent);`novel resume` 从最后 SUCCESS 节点续跑;预算门禁(单章调用数/Token 上限,PRD §8.11)在节点入口检查,超限→PAUSED 等 CLI 决定。

**REPLAN 与人工退回的处理(阶段0)**:Judge 裁 `REPLAN_SCENE/REPLAN_CHAPTER`,或人工门禁选"退回"后,章节置 `NEEDS_REPLAN` 并**升级人工**——阶段0 不设自动重规划 Agent。提供最小编辑入口:`novel edit-outline <chapter>` 将章纲/场景卡导出为 YAML,人工修改后导入,校验通过则 bump `outline_ver` 并回到 N1 重新走循环(旧 draft 谱系作废,revision_round 重置)。

**批次连跑语义(D15)**:`write-batch` 内第 k+1 章的上下文包 = 已提交 canon + 前序各章的 provisional canon overlay(显式标记);人工门禁退回第 k 章时,第 k+1..n 章自动置 `STALE`,其稿件与 provisional 增量作废,待第 k 章重走后按新 canon 重跑。

**规划链**(开书,一次性):kernel 三候选(Story Architect 提示词,复用 Writer 槽位)→ CLI 选定 → 角色卡 → 卷纲 → 剧情单元 → 章纲+场景卡(滚动 5 章)。阶段0 规划链**只做单轮生成+人工确认**,不做 PRD §10 的规划对抗(Concept Judge 等)——那是阶段1 增强项(见 §10)。

## 7. Agent 规格(阶段0 阵容)

| Agent | 模型槽位 | 输入(仅此) | 输出 Schema | 写权限 |
|---|---|---|---|---|
| Writer A/B | creative | ChapterContextPackage | DraftCandidate | 只产候选,不落正史 |
| Red-Team Critic | review | 盲化候选+约束集 | list[ReviewIssue] | 无 |
| Plot/Character/Continuity/Prose Reviewer | review | 盲化候选+各自所需最小上下文切片 | list[ReviewIssue] | 无 |
| Judge | judge(≠creative 模型族) | 盲化候选+匿名化 issue 集+约束集 | JudgeVerdict | 无 |
| Reviser | creative | 候选+RevisionOrder | DraftCandidate(修订版)+变更说明 | 仅授权范围;锁定段不可改 |
| Canon Curator | extract | 批准稿+当前 canon 快照 | CanonDelta | 仅提案 |

硬规则(代码强制,非提示词约定):写手不审自己、评审不改稿、裁判不写正文、修订者不新增问题(Reviser 输出中出现 RevisionOrder 外的改动 → lint 拒绝)。无证据 issue(evidence 为空,或经归一化模糊匹配仍定位不到正文)由代码**降权标记后仍随集进入 Judge**,Judge 不得将其采纳为阻断项(对齐 PRD §9.3 末条;不做进 Judge 前静默过滤,避免吞掉表述不精确的真实举证)。

**结构化输出策略**:gateway 层统一 JSON mode/tool-call → Pydantic 校验 → 失败自动修复 1 次(重发校验错误)→ 仍失败按节点失败策略处理。**例外(D16)**:Writer/Reviser 的正文走两段式协议——正文按场景纯文本分段输出、元数据独立 JSON 输出,由 gateway 组装为 DraftCandidate,避免长中文正文进 JSON。

## 8. 回归集(阶段0 必备,验收依赖)

`tests/regression/samples/` 固定样本,每个 = 微型项目(kernel+角色+章纲+植入缺陷的候选稿)+ 期望裁决:

| 样本 | 植入缺陷 | 期望 |
|---|---|---|
| R1 正史冲突 | 角色已死复活 | Judge 阻断,rollback=场景卡/正文 |
| R2 信息越权 | POV 使用不可知信息 | 阻断,rollback=场景卡 |
| R3 因果断裂 | 关键结果无前置 | 阻断,rollback=章纲/场景卡 |
| R4 工程污染 | 正文混入 JSON/提示词 | lint 层直接拦截(不消耗评审) |
| R5 无证据意见 | 评审报告 evidence 为空 | 代码过滤,Judge 不得采纳为阻断 |
| R6 干净样本 | 无缺陷 | PASS(校准误杀率) |

模型/提示词/AgentScope/Controller 升级前必须全量重跑(PRD §17.3)。

## 9. 非功能与安全(阶段0 适用子集)

- 密钥仅 env(`.env` gitignore;`.env.example` 入库)。日志默认不落完整提示词与正文,`NOVEL_DEBUG_LOG=1` 临时开启并打警告(PRD §18.3)。
- Agent 无 Shell/文件写/网络工具;AgentScope 工具注册白名单为空集起步。
- SQLite `journal_mode=WAL`;备份=复制 db 文件+项目包导出。
- 内容边界:项目 `do_not_write` 注入所有生成与评审提示词;lint 含禁写词表检查。

## 10. 阶段1(MVP)概要 — 详细规划推迟到阶段0退出

增量:FastAPI(项目/章节/版本/审批/任务 API)+ Web 写作台(React+TS:大纲树、章节编辑器、差异、证据/裁决视图、批次审批)+ story_bible 版本表 + 规划链对抗(Concept Judge)+ Writer B/Reader Advocate/Source Reviewer 条件启用 + 渠道导出模板 + timeline_event/source_record 表。验收对齐 PRD §22.1。**本 Spec 不为阶段1 排任务,阶段0 退出时以实测数据重估。**

## 11. 开工前必须核验(M0 第一批任务,阻塞后续)

| # | 核验项 | 方法 | 失败预案 |
|---|---|---|---|
| V1 | AgentScope 当前稳定版本、并发/Routing/Handoff API 形态、许可证 | 官方 repo/docs | API 不符→在 `runtime/` 适配层内消化;能力缺失→并发评审退化为 asyncio.gather 自管 |
| V2 | oh-story-claudecode 许可证与可吸收内容(MIT 已知,复核) | repo | 仅方法论借鉴,不复制文件则无阻塞 |
| V3 | 四槽位模型供应商选定与配额(creative/review/judge/extract) | 用户确认 | mock provider 先行,不阻塞开发 |
| V4 | Python 3.11 vs 3.12 与 AgentScope 兼容性 | V1 附带 | 取交集 |

## 12. 验收标准映射

阶段0 验收 = §1.3 五条 + 回归集 §8 全绿 + 测试套件(unit/contract/workflow)通过 + PRD §22.3 合规四条(代码审查确认无自动发布/无检测对抗/无未授权语料入库/导出需确认)。

---

*本 Spec 由 autopilot Phase 0 生成;已经独立对抗评审(裁决 APPROVE_WITH_FIXES)并逐条修订,冻结为 v1.0。*
