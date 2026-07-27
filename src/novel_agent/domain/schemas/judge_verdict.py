"""裁判裁决(PRD §9.4 YAML 全字段)。"""

from pydantic import Field, model_validator

from novel_agent.domain.schemas.base import HardGate, RollbackLevel, VerdictType, VersionedSchema


class IssueRuling(VersionedSchema):
    """裁判对单条评审意见的逐项处理(PRD §9.4 规则3)。"""

    issue_id: str = Field(min_length=1)
    accepted: bool
    reason: str = Field(min_length=1, description="接受/驳回的证据说明")


class JudgeVerdict(VersionedSchema):
    verdict: VerdictType
    selected_candidate: str = Field(min_length=1, description="盲化候选名")
    hard_gate_failures: list[HardGate] = Field(default_factory=list)
    rulings: list[IssueRuling] = Field(default_factory=list, description="逐项接受/驳回")
    conflicting_reviews: list[str] = Field(default_factory=list, description="互相冲突的意见组说明")
    revision_scope: list[str] = Field(
        default_factory=list, description="REVISE_LOCAL 时的授权范围(scene_id/段落)"
    )
    locked_strengths: list[str] = Field(default_factory=list, description="修订不得破坏的优点")
    rollback_target: RollbackLevel | None = None
    recheck_requirements: list[str] = Field(default_factory=list, description="复检要求")
    reasoning_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistency(self) -> "JudgeVerdict":
        """裁决内部一致性(PRD §9.4 规则1/5;硬门禁不可被 PASS)。"""
        if self.verdict == VerdictType.PASS and self.hard_gate_failures:
            raise ValueError("存在硬门禁失败时不得裁 PASS(PRD §9.4 规则1)")
        if self.verdict == VerdictType.REVISE_LOCAL and not self.revision_scope:
            raise ValueError("REVISE_LOCAL 必须给出 revision_scope(PRD §9.4 规则5)")
        if (
            self.verdict in (VerdictType.REPLAN_SCENE, VerdictType.REPLAN_CHAPTER)
            and self.rollback_target is None
        ):
            raise ValueError("REPLAN_* 必须给出 rollback_target")
        return self


class RevisionOrder(VersionedSchema):
    """Judge → Reviser 的授权工单(Spec §5)。由代码从 JudgeVerdict 生成。"""

    verdict_ref: str = Field(min_length=1, description="来源裁决标识")
    candidate_id: str = Field(min_length=1)
    issue_ids: list[str] = Field(min_length=1, description="仅处理这些问题")
    scope: list[str] = Field(min_length=1, description="允许修改的 scene_id/段落范围")
    locked_strengths: list[str] = Field(default_factory=list)
    locked_ranges: list[str] = Field(default_factory=list, description="人工锁定段落,不得修改")
    instructions: str = Field(min_length=1, description="最小修改说明")
