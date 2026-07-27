"""评审问题报告(PRD §9.3 红队输出 YAML + Spec §5 evidence 定位结构)。"""

from pydantic import Field

from novel_agent.domain.schemas.base import (
    HardGate,
    ReviewerRole,
    RollbackLevel,
    Severity,
    VersionedSchema,
)


class EvidenceRef(VersionedSchema):
    """证据定位:scene_id + 原文引文;匹配用归一化模糊阈值(Spec §5)。"""

    scene_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, description="正文原文引文(允许非逐字节精确)")
    note: str = ""


class ReviewIssue(VersionedSchema):
    """单条评审问题(PRD §9.3 全字段)。

    reviewer_role 仅供应用层记录与统计;进入 Judge 前由盲化模块剥离(Spec D11)。
    downweighted 由代码设置(evidence 缺失/定位失败),Judge 不得将其采纳为阻断项。
    """

    issue_id: str = Field(min_length=1)
    reviewer_role: ReviewerRole
    claim: str = Field(min_length=1, description="问题断言")
    evidence: list[EvidenceRef] = Field(default_factory=list)
    violated_rule: str = Field(min_length=1, description="违反的约束/规则来源")
    hard_gate: HardGate | None = Field(default=None, description="命中的硬门禁类别,软问题为 None")
    severity: Severity
    failure_consequence: str = Field(min_length=1, description="不修复的后果")
    recommended_rollback_level: RollbackLevel
    confidence: float = Field(ge=0.0, le=1.0)
    downweighted: bool = Field(default=False, description="无证据降权标记(代码设置)")


class ReviewReport(VersionedSchema):
    """单个评审 Agent 的完整输出。"""

    reviewer_role: ReviewerRole
    candidate_id: str = Field(min_length=1, description="盲化候选名,如 candidate_1")
    issues: list[ReviewIssue] = Field(default_factory=list)
    overall_note: str = ""
