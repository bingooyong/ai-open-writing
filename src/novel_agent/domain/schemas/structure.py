"""Story Bible 结构层 Schema:简报、三幕图、冲突、爽点、异名。"""

from enum import StrEnum

from pydantic import Field, model_validator

from novel_agent.domain.schemas.base import VersionedSchema


class ConflictKind(StrEnum):
    INTEREST = "interest"
    VALUE = "value"
    EMOTION = "emotion"
    IDENTITY = "identity"
    TIME = "time"


class ConflictTemperature(StrEnum):
    SETUP = "setup"
    RISING = "rising"
    PEAK = "peak"
    PAID = "paid"


class MustAffect(StrEnum):
    PLOT = "plot"
    RELATIONSHIP = "relationship"
    BOTH = "both"


class PayoffScale(StrEnum):
    MICRO = "micro"
    SMALL = "small"
    LARGE = "large"


class StoryBrief(VersionedSchema):
    """R0 归一化火花:题材/受众可空;禁写项继承项目 boundaries。"""

    spark: str = Field(min_length=1)
    genre: str = ""
    audience: str = ""
    do_not_write: list[str] = Field(default_factory=list)


class StructureBeat(VersionedSchema):
    summary: str = Field(min_length=1)
    volume_id: str = ""
    chapter_key: str = ""


class GoldenThreeChapter(VersionedSchema):
    """黄金三章单章契约:承诺 / 加压 / 小闭环或钩子。"""

    promise: str = Field(min_length=1)
    escalation: str = Field(min_length=1)
    payoff_or_hook: str = Field(min_length=1)


class StructureMap(VersionedSchema):
    """全书三幕图 + 黄金三章(恰好三章)。"""

    template: str = "three_act"
    inciting_incident: StructureBeat
    commitment: StructureBeat
    midpoint: StructureBeat
    all_is_lost: StructureBeat
    climax: StructureBeat
    resolution: StructureBeat
    golden_three: list[GoldenThreeChapter] = Field(min_length=3, max_length=3)


class Conflict(VersionedSchema):
    conflict_id: str = Field(min_length=1)
    kind: ConflictKind
    parties: list[str] = Field(min_length=1)
    stake: str = Field(min_length=1)
    temperature: ConflictTemperature
    must_affect: MustAffect
    payoff_chapter_key: str = ""


class PayoffBeat(VersionedSchema):
    beat_id: str = Field(min_length=1)
    scale: PayoffScale
    kind: str = Field(min_length=1)
    pressure_before: str
    hit: str = Field(min_length=1)
    chapter_key: str = ""
    unit_id: str = ""
    order_index: int = 0

    @model_validator(mode="after")
    def _require_target(self) -> "PayoffBeat":
        if not self.chapter_key.strip() and not self.unit_id.strip():
            raise ValueError("PayoffBeat 需要 chapter_key 或 unit_id")
        return self


class IdentityAlias(VersionedSchema):
    canonical_character_id: str = Field(min_length=1)
    alias: str = Field(min_length=1)


class RelationshipProposal(VersionedSchema):
    """规划期关系提案;确认后写入 relationship_state(provisional)。"""

    parties: list[str] = Field(min_length=2, max_length=2)
    state: str = Field(min_length=1)
    evidence: str = ""
