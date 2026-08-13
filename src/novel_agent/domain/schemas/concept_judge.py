"""规划链 Concept Judge 裁决(Stage 1:PASS / REVISE / REJECT)。"""

from enum import StrEnum

from pydantic import Field, model_validator

from novel_agent.domain.schemas.base import VersionedSchema


class ConceptJudgeDecision(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    REJECT = "REJECT"


class ConceptJudgeVerdict(VersionedSchema):
    """对内核/结构(或冲突引擎)的规划对抗裁决。"""

    verdict: ConceptJudgeDecision
    after_round: str = Field(pattern=r"^R[24]$")
    reasons: list[str] = Field(min_length=1)
    repair_notes: str = ""
    repair_attempted: bool = False

    @model_validator(mode="after")
    def _revise_needs_repair_notes(self) -> "ConceptJudgeVerdict":
        if self.verdict is ConceptJudgeDecision.REVISE and not self.repair_notes.strip():
            raise ValueError("REVISE 必须给出 repair_notes")
        return self
