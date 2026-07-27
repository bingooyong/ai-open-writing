"""Schema 基类与领域枚举(Spec §5/§6)。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class VersionedSchema(BaseModel):
    """所有跨 Agent 契约的基类:禁未知字段,带 schema_version。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"


class Severity(StrEnum):
    """问题等级(PRD §8.5)。"""

    P0 = "P0"  # 硬冲突,必须修复
    P1 = "P1"  # 读者可察觉,原则上修复
    P2 = "P2"  # 建议,由 Judge 决定采纳


class RollbackLevel(StrEnum):
    """回退层级(PRD §9.3 硬门禁表)。"""

    PROSE = "prose"  # 正文局部
    SCENE_CARD = "scene_card"
    CHAPTER_OUTLINE = "chapter_outline"
    PLOT_UNIT = "plot_unit"
    HUMAN = "human"  # 升级人工


class VerdictType(StrEnum):
    """裁决五枚举(PRD §9.4)。"""

    PASS = "PASS"
    REVISE_LOCAL = "REVISE_LOCAL"
    REPLAN_SCENE = "REPLAN_SCENE"
    REPLAN_CHAPTER = "REPLAN_CHAPTER"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class HardGate(StrEnum):
    """硬门禁类别(PRD §9.3)。"""

    CANON_CONFLICT = "canon_conflict"  # 正史冲突
    INFO_VIOLATION = "info_violation"  # 信息越权
    CAUSALITY_BREAK = "causality_break"  # 因果断裂
    CORE_CONSTRAINT = "core_constraint"  # 核心约束违背(提前揭示等)
    SOURCE_RISK = "source_risk"  # 来源风险
    CONTENT_BOUNDARY = "content_boundary"  # 内容边界(禁写项)
    ENGINEERING_LEAK = "engineering_leak"  # 工程污染


class ChapterStatus(StrEnum):
    """章节状态机(PRD §8.9 + Spec D15 的 STALE)。"""

    PLANNED = "PLANNED"
    DRAFTING = "DRAFTING"
    ADVERSARIAL_REVIEW = "ADVERSARIAL_REVIEW"
    JUDGING = "JUDGING"
    NEEDS_REVISION = "NEEDS_REVISION"
    NEEDS_REPLAN = "NEEDS_REPLAN"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPROVED = "APPROVED"
    CANON_LOCKED = "CANON_LOCKED"
    EXPORTED = "EXPORTED"
    STALE = "STALE"  # D15:前章被退回,本章基于 provisional 事实作废


class ReviewerRole(StrEnum):
    """阶段0 评审阵容(Spec §7)。"""

    RED_TEAM = "red_team"
    PLOT = "plot"
    CHARACTER = "character"
    CONTINUITY = "continuity"
    PROSE = "prose"


class EntityStateType(StrEnum):
    """entity_state.state_type 约定(Spec §5 CanonDelta 映射表)。"""

    POSITION = "position"
    ABILITY = "ability"
    RESOURCE = "resource"
    KNOWLEDGE = "knowledge"
    FACT = "fact"
    STATUS = "status"  # 身体/名誉等

