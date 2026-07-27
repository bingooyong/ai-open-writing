# 对抗评审记录 — spec.md + autopilot-impl.md

> 日期:2026-07-27
> 评审方式:原定 architect + critic 双盲并行评审,因 API 限流(429)三次失败;降级为**单个独立 general-purpose 评审 agent 合并双视角**执行(独立上下文,通读 PRD/Spec/Plan 三份文档)。此为单评审员结论,弱于双盲评审一档。
> 裁决:**APPROVE_WITH_FIXES** — 全部 P1/P2 已于同日逐条修订进两份文档。

## 修复对照表

| 级别 | 发现 | 修复落点 |
|---|---|---|
| P1 | 批次连跑与"未批准内容不污染后续上下文"冲突,机制缺失 | Spec 新增 D15(provisional canon overlay + STALE 级联);§6 批次连跑语义段;Plan M3.5 DoD 级联断言;用户输入事项 #3 |
| P1 | NEEDS_REPLAN/人工退回后无修改入口(流程死角) | Spec §6 REPLAN 处理段(`novel edit-outline` 流程);Plan 新增 M3.3b,M3.4 依赖更新 |
| P1 | 两轮修订计数语义歧义且无持久化落点 | Spec §6 N7 重写(谱系内 REVISE_LOCAL 计数,REPLAN 重置,chapter.revision_round);Plan M1.5 DoD 加"轮次不因重启归零" |
| P1 | 长中文正文进 JSON 的风险应对误引 D9(存储分离≠传输分离) | Spec 新增 D16(两段式输出协议)+ §7 例外条款;Plan M2.3 任务与 DoD、风险表修正 |
| P1 | 提示词真实效果验证全部压在 M4.2 单点 | Plan M2.6 DoD 加"每角色真实模型小样本冒烟(≤5 次)";M3.3 DoD 加"真实模型单章冒烟" |
| P2 | CanonDelta 字段→表落点未定义 | Spec §5 新增映射表(timeline_events 阶段0 仅存原始记录不参与校验) |
| P2 | evidence 定位格式未决;进 Judge 前静默过滤过严 | Spec §5 定位结构(scene_id+引文+归一化模糊匹配);§7 改为降权标记仍进 Judge |
| P2 | Git 检查点粒度自相矛盾(D12 批次 vs N9 逐章) | Spec D12 拍板:逐章 canon 检查点+批次导出检查点;git 失败仅告警不回滚 |
| P2 | N5 缺席策略欠明(关键评审未区分、恢复粒度未定) | Spec §6 N5 重写:Continuity/RedTeam 不可缺席;缺席清单入 Judge;按 reviewer 子记录续跑 |
| P2 | 退出条件1"三章连贯"无客观判据 | Spec §1.3 条1 补四项客观清单 |
| P2 | M3.2 依赖漏 M2.2;盲化映射与锁定段落无数据落点 | Plan M3.2 依赖补齐;Spec §5 补 draft_version.locked_ranges、盲化映射入 NodeRun 快照;Plan M2.5 同步 |
| P2 | M2.1 DoD 未断言 ModelRun 字段完整性 | Plan M2.1 DoD 逐字段非空断言 |

## 评审原文摘录(裁决理由)

> 收敛方向正确:五条退出条件均能在 Spec/Plan 中找到主承接,D1~D14 除 D9 被 Plan 误引、D12 与 N9 粒度矛盾外无不可行项,"不建"清单的裁剪基本安全。但存在三处会在实现中期强制停工拍板的 FSM 级空洞——批次内 canon 时序与退回级联、REPLAN/退回后的修改入口、两轮计数语义——它们都不在"需要用户输入的事项"清单里,属于计划自行假设掉的领域决策;加上真实模型风险全部后置到 M4.2 单点,按现状开工大概率在 M3.5/M4.2 处返工。上述 P1 五条以文字级修订即可关闭(无需重构架构),修完即可冻结开工。
