# 实施计划:AI 长篇小说创作智能体 — 阶段0(工作流验证)

> 状态:v1.0 — 已完成对抗评审(裁决 APPROVE_WITH_FIXES)并逐条修订
> 上游:`.omc/autopilot/spec.md`(下称 Spec)、`docs/AI_Novel_Agent_PRD_Architecture.md`(PRD)
> 范围:**仅阶段0**。阶段1(MVP)在阶段0 退出评审后另行排任务(Spec §10)。
> 规模标记:S≈半天内 / M≈1天 / L≈2-3天(单执行者当量,仅用于相对排序,非承诺)

---

## 0. 计划总览

```
M0 工程基线与核验 ──▶ M1 领域层 ──▶ M2 网关与Agent层 ──▶ M3 单章循环端到端 ──▶ M4 阶段0验收
   (串行,阻塞)        (部分可并行)    (与M1后半并行)        (集成,串行为主)       (串行)
```

关键路径:M0.1→M1.1→M1.3→M3.1→M3.3→M3.3b→M3.4→M3.5→M4.2
并行机会:M1.2/M1.4 与 M2.1/M2.2 可双线;M2.3 各 Agent 提示词可多执行者并行。

**执行者分层**(autopilot Phase 2 用):
- 简单(Haiku 级):脚手架、配置文件、导出、样本数据整理
- 标准(Sonnet 级):仓储层、CLI、lint、契约测试、提示词初稿
- 复杂(Opus 级):FSM 核心、幂等/恢复、Judge 提示词与校准、盲化机制、CanonWriter 事务

---

## M0 工程基线与核验(阻塞全部后续)

| ID | 任务 | 规模 | 依赖 | DoD |
|---|---|---|---|---|
| M0.1 | `git init` + `.gitignore`(.env/.omc/state/db 等)+ 初始提交(现有 docs/ 与 .omc 产物) | S | — | `git log` 有初始提交;敏感路径已忽略 |
| M0.2 | uv + pyproject 脚手架:src 布局(Spec §4)、ruff、pytest、mypy(basic)、pre-commit | S | M0.1 | `uv run pytest` 空套件通过;`uv run ruff check` 通过 |
| M0.3 | **核验 V1**:AgentScope 稳定版本/API/许可证(WebSearch+官方 docs),产出 `docs/verification-report.md`,在 pyproject 锁定版本 | M | M0.2 | 报告含:版本号、并发/结构化输出 API 实测样例、许可证结论;若 API 与 Spec 假设不符,先改 Spec 再继续 |
| M0.4 | 核验 V2~V4(oh-story 许可证复核、模型槽位供应商确认[需用户输入]、Python 版本交集) | S | M0.2 | 报告追加;V3 未定不阻塞(mock 先行) |
| M0.5 | 配置系统:pydantic-settings 读 env,四模型槽位 + 预算参数 + `.env.example` | S | M0.2 | 单测:缺失必填项时报错清晰 |

**门禁 G0**:V1 结论若为"AgentScope 不可用/许可证不符"→ 停止并上报用户(备选:纯 asyncio 自管 Agent 编排,需用户拍板)。

## M1 领域层(数据即真源)

| ID | 任务 | 规模 | 依赖 | DoD |
|---|---|---|---|---|
| M1.1 | Pydantic Schema 全集(Spec §5 清单,含 schema_version;ReviewIssue 的 evidence 定位结构;RevisionOrder) | M | M0.5 | 每个 Schema 有效/非法样例单测;JSON Schema 可导出 |
| M1.2 | SQLModel 表 + Alembic 首迁移(Spec §5 建表清单;WAL 开启) | M | M1.1 | `alembic upgrade head` 幂等;回滚可用 |
| M1.3 | 仓储层 repos(唯一 SQL 入口):project/chapter/draft/issue/verdict/canon/model_run/workflow | M | M1.2 | CRUD+查询单测;禁止业务层裸 SQL(ruff 自定义规则或约定+审查) |
| M1.4 | **FSM 核心**:章节状态机+节点表(Spec §6)、表驱动转移校验、NodeRun 快照读写、租约、attempt | L | M1.3 | 非法转移抛错单测;快照 round-trip 单测 |
| M1.5 | 幂等与恢复:幂等键实现、`resume` 从最后 SUCCESS 节点续跑、canon 重复提交检测 | L | M1.4 | **杀进程测试**:任意节点后 kill,resume 不重跑已成功节点、不重复写 canon;**revision_round 不因重启归零** |
| M1.6 | 预算模块:单章调用数/Token 上限、节点入口检查、PAUSED 态 | S | M1.4 | 超限单测:进入 PAUSED 且状态可查 |
| M1.7 | CanonWriter 单写入器:冲突校验(与 entity_state/relationship/plot_thread 快照比对)→事务提交→Git 检查点 | L | M1.3 | R1 类冲突被校验拦截;提交后 git log 出现检查点;失败回滚干净 |

## M2 网关与 Agent 层

| ID | 任务 | 规模 | 依赖 | DoD |
|---|---|---|---|---|
| M2.1 | ModelGateway:协议、openai 兼容+anthropic 适配器、重试/超时、ModelRun 落库、成本估算 | M | M0.5 | mock+真实各一冒烟;每次调用产生 ModelRun 记录,**断言 token/耗时/成本/prompt_version/关联版本各字段非空** |
| M2.2 | **mock provider**:按角色返回固定 fixture(可注入缺陷),支撑全链路离线测试 | M | M2.1 | 契约测试全部走 mock,无网络可跑 |
| M2.3 | 结构化输出层:JSON 强制→Pydantic 校验→修复重试1次→失败上抛;**Writer/Reviser 两段式协议(Spec D16:正文纯文本分段+元数据 JSON,gateway 组装)** | M | M2.1 | 三分支(直通/修复成功/失败)单测;**两段协议组装/边界(截断、场景缺失)单测** |
| M2.4 | AgentScope 集成:runtime 初始化、Agent 基类(注入 gateway+schema)、并发评审执行器(AgentScope 并发,G0 备选 asyncio) | L | M0.3, M2.3 | 5 评审并行冒烟;单评审失败不阻断(Spec §6 N5 策略) |
| M2.5 | 盲化/匿名化模块:候选稿→candidate_1/2;issue 集剥离 agent/model 字段;**盲化映射存入 N3 NodeRun 快照,解盲由代码执行**;单测覆盖"泄漏检测" | M | M1.1 | Judge 输入中断言不含任何 agent/model 标识;解盲 round-trip 单测 |
| M2.6 | 提示词 v1(YAML frontmatter 版本化):Writer / RedTeam / 4 Reviewer / Judge / Reviser / CanonCurator / 规划链(kernel三候选·角色卡·卷纲·单元·章纲场景卡) | L(可并行拆给多执行者) | M1.1 | 每份提示词引用 IO Schema;mock 下契约测试通过;**每个角色用真实模型做小样本冒烟(各≤5 次调用),验证结构化输出与中文 evidence 定位可用,不达标即改到达标** |
| M2.7 | 确定性 lint:n-gram 重复、格式、工程污染正则(JSON/提示词残留)、禁写词、Reviser 越权改动检测(diff 与 RevisionOrder 范围比对) | M | M1.1 | R4 样本被拦截;越权改动样本被拒 |

## M3 单章生产循环端到端

| ID | 任务 | 规模 | 依赖 | DoD |
|---|---|---|---|---|
| M3.1 | ContextBuilder:按 PRD §12.2 顺序组装 ChapterContextPackage,超预算裁剪策略 | M | M1.3 | 组装内容单测(含裁剪优先级);写前守卫 N1 |
| M3.2 | 规划链 CLI:`novel init`(kernel 三候选+人工选定)→角色卡→卷纲→单元→滚动章纲/场景卡,均落库+人工确认 | L | M2.2, M2.6, M1.3 | mock 下走通;产物入库可查 |
| M3.3 | 单章循环编排:N1→N9 全节点接 FSM(评审并行、无证据 issue 降权、Judge、两轮修订上限、HUMAN_REVIEW 升级) | L | M1.4-M1.7, M2.4-M2.7, M3.1 | mock 下:PASS 路径、REVISE_LOCAL 两轮路径、REPLAN 路径、两轮失败→HUMAN_REVIEW 路径各一条集成测试;**真实模型跑通单章一次(冒烟,不要求质量达标)** |
| M3.3b | REPLAN/退回编辑入口:`novel edit-outline <chapter>`(章纲/场景卡导出 YAML→人工改→导入校验→bump outline_ver→回 N1,旧谱系作废、轮次重置) | M | M3.3 | REPLAN 裁决后经 edit-outline 修改再续跑的集成测试 |
| M3.4 | 人工门禁 CLI:`novel review-batch`(逐章看稿+问题+裁决;批准/退回/段落指令重写标记[写 locked_ranges]) 、`novel approve` 触发 canon 提交 | M | M3.3, M3.3b | 批准后 chapter→CANON_LOCKED,canon 落库,git 检查点产生;退回路径进入 edit-outline 流程 |
| M3.5 | `novel write-batch`(3~5 章连跑,**批次内 provisional canon overlay,Spec D15**)+ `novel resume` + `novel export`(TXT/MD,Spec D13) | M | M3.3, M3.4 | mock 下 3 章连跑;中断恢复;导出文件正确;**退回第1章后第2/3章被置 STALE 的级联断言** |

## M4 阶段0 验收

| ID | 任务 | 规模 | 依赖 | DoD |
|---|---|---|---|---|
| M4.1 | 回归集落地:R1~R6 样本数据 + 断言脚本(Spec §8) | M | M3.3 | `pytest tests/regression` 全绿 |
| M4.2 | **真实模型验证**:配置真实四槽位(V3),完整跑一个微型项目→3 章待审稿;人工植入 R1~R3 缺陷验证 Judge 阻断 | L | M4.1, M0.4-V3 | Spec §1.3 五条退出条件逐条留证(输出/日志/DB 记录) |
| M4.3 | Judge 校准测试:R5(无证据不采纳)、R6(干净样本不误杀)、匿名化断言 | M | M4.1 | 校准套件通过;误杀/漏杀记录进 verification-report |
| M4.4 | 收尾:README(跑通指引)、`docs/verification-report.md` 定稿、依赖锁定、全套 `uv run pytest` + ruff + mypy 绿 | S | M4.2, M4.3 | 新机器按 README 可复现 mock 全链路 |

**门禁 G4(阶段0 退出评审)**:五条退出条件全过 → 冻结 tag `stage0`,再启动阶段1 详细规划;任何一条不过 → 按 autopilot QA 循环修复(≤5 轮,同错 3 现即停并上报)。

---

## QA 与验证映射(autopilot Phase 3/4)

- **Phase 3 QA 循环**:每里程碑收口跑 `ruff + mypy + pytest(unit/contract/workflow)`;M3 起加集成测试;M4 加回归集与真实模型冒烟。
- **Phase 4 多视角验证**(代码完成后):architect(对照 Spec §3/§6/§7 的边界与完整性)、security-reviewer(密钥/日志脱敏/Agent 零工具面/PRD §22.3 合规四条)、code-reviewer(质量)。三方全过才算完。

## 风险清单(建设期 Top5,应对已入任务)

| 风险 | 应对(任务锚点) |
|---|---|
| AgentScope API 与假设不符/版本动荡 | M0.3 先核验+适配层隔离;G0 备选 asyncio 编排 |
| 结构化输出不稳定(长中文正文+JSON) | **两段式输出协议(Spec D16)从传输层规避**;M2.3 修复重试;契约测试全 mock 先行;M2.6/M3.3 真实模型冒烟把风险前移 |
| Judge 校准不足(误放行/误杀) | M4.3 专项;R6 干净样本控误杀;不同模型族(Spec D8) |
| 单章循环成本失控 | M1.6 预算门禁先于真实模型接入;M4.2 前全程 mock |
| 幂等/恢复有隐蔽缺陷 | M1.5 杀进程测试进 CI;canon 幂等单独断言 |

## 需要用户输入的事项(不阻塞开工,但 M4.2 前必须落定)

1. **V3 模型槽位**:creative/review/judge/extract 四槽位各用什么供应商与型号(Judge 须与 creative 不同模型族)。
2. 阶段0 预算上限:单章最大调用次数与 Token 上限的初始值(可先用 Spec 默认:修订≤2 轮已定,建议单章≤25 次调用起步,跑 M4.2 后再调)。
3. **批次连跑语义确认(Spec D15)**:批次内后章读取前章 provisional canon、前章退回则后章级联置 STALE——此为领域决策默认值,开工前请确认或改为"严格串行(每章批准后才写下一章)"。

---

*本计划由 autopilot Phase 1 生成;已经独立对抗评审(APPROVE_WITH_FIXES)并逐条修订,冻结为 v1.0,作为 Phase 2 执行依据。*
