"""跨 Agent 交换契约(Spec §5)。所有 Schema 携带 schema_version。"""

from novel_agent.domain.schemas.base import (
    ChapterStatus,
    EntityStateType,
    HardGate,
    ReviewerRole,
    RollbackLevel,
    Severity,
    VerdictType,
    VersionedSchema,
)
from novel_agent.domain.schemas.canon_delta import (
    CanonDelta,
    EntityStateChange,
    RelationshipChange,
    ThreadUpdate,
)
from novel_agent.domain.schemas.character import CharacterCard, VoiceProfile
from novel_agent.domain.schemas.context_package import (
    CanonFact,
    ChapterContextPackage,
    ThreadStatus,
)
from novel_agent.domain.schemas.draft import DraftCandidate, SceneDraft
from novel_agent.domain.schemas.judge_verdict import IssueRuling, JudgeVerdict, RevisionOrder
from novel_agent.domain.schemas.kernel import KernelCandidateSet, StoryKernel
from novel_agent.domain.schemas.outline import ChapterOutline, LineDeltas, PlotUnitCard
from novel_agent.domain.schemas.review_issue import EvidenceRef, ReviewIssue, ReviewReport
from novel_agent.domain.schemas.scene import SceneCard
from novel_agent.domain.schemas.structure import (
    Conflict,
    ConflictKind,
    ConflictTemperature,
    GoldenThreeChapter,
    IdentityAlias,
    MustAffect,
    PayoffBeat,
    PayoffScale,
    RelationshipProposal,
    StoryBrief,
    StructureBeat,
    StructureMap,
)

__all__ = [
    "CanonDelta",
    "CanonFact",
    "ChapterContextPackage",
    "ChapterOutline",
    "ChapterStatus",
    "CharacterCard",
    "Conflict",
    "ConflictKind",
    "ConflictTemperature",
    "DraftCandidate",
    "EntityStateChange",
    "EntityStateType",
    "EvidenceRef",
    "GoldenThreeChapter",
    "HardGate",
    "IdentityAlias",
    "IssueRuling",
    "JudgeVerdict",
    "KernelCandidateSet",
    "LineDeltas",
    "MustAffect",
    "PayoffBeat",
    "PayoffScale",
    "PlotUnitCard",
    "RelationshipChange",
    "RelationshipProposal",
    "ReviewIssue",
    "ReviewReport",
    "ReviewerRole",
    "RevisionOrder",
    "RollbackLevel",
    "SceneCard",
    "SceneDraft",
    "Severity",
    "StoryBrief",
    "StoryKernel",
    "StructureBeat",
    "StructureMap",
    "ThreadStatus",
    "ThreadUpdate",
    "VerdictType",
    "VersionedSchema",
    "VoiceProfile",
]
