"""全部数据表(Spec §5 建表清单,阶段0)。

设计约定:
- 可查询/可约束字段 → 标量列(业务键、状态、版本、外键、计数)。
- 文档型载荷(Pydantic Schema 序列化)→ payload JSON 列,读写由仓储层负责。
- reader_contract 并入 story_kernel 载荷(StoryKernel Schema 本身含读者契约字段,
  与 PRD §2.5 YAML 一致),不设独立表。
- 时间戳统一 UTC。
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from novel_agent.domain.schemas.base import ChapterStatus


def _now() -> datetime:
    return datetime.now(UTC)


class ProjectRecord(SQLModel, table=True):
    __tablename__ = "project"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    genre: str = ""
    status: str = Field(default="active", index=True)
    world_rules: dict = Field(default_factory=dict, sa_column=Column(JSON))
    boundaries: list = Field(default_factory=list, sa_column=Column(JSON))
    channel_profile: dict = Field(default_factory=dict, sa_column=Column(JSON))
    spark: str = ""
    brief: str = ""
    bible_pending: dict = Field(default_factory=dict, sa_column=Column(JSON))
    concept_judge: dict = Field(default_factory=dict, sa_column=Column(JSON))
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class StoryKernelRecord(SQLModel, table=True):
    __tablename__ = "story_kernel"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    version: int = 1
    approved: bool = Field(default=False, index=True)
    payload: dict = Field(sa_column=Column(JSON))  # StoryKernel(含读者契约)
    created_at: datetime = Field(default_factory=_now)


class CharacterRecord(SQLModel, table=True):
    __tablename__ = "character"
    __table_args__ = (UniqueConstraint("project_id", "character_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    character_id: str = Field(index=True)  # 业务键,如 ch_su
    name: str = ""
    payload: dict = Field(sa_column=Column(JSON))  # CharacterCard
    version: int = 1
    created_at: datetime = Field(default_factory=_now)


class CharacterArcRecord(SQLModel, table=True):
    """人物弧检查点(弧线定义在 CharacterCard 内;此表记录逐章推进)。"""

    __tablename__ = "character_arc"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    character_id: str = Field(index=True)
    chapter_key: str = Field(index=True)
    arc_note: str  # 本章弧线增量
    created_at: datetime = Field(default_factory=_now)


class RelationshipStateRecord(SQLModel, table=True):
    """动态关系当前态(PRD §2.6 关系状态机;历史靠 canon_delta 追溯)。"""

    __tablename__ = "relationship_state"
    __table_args__ = (UniqueConstraint("project_id", "party_a", "party_b"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    party_a: str = Field(index=True)
    party_b: str = Field(index=True)
    state: str
    evidence: str = ""
    source_chapter: str = ""
    provisional: bool = Field(default=False, index=True)  # D15
    updated_at: datetime = Field(default_factory=_now)


class StructureMapRecord(SQLModel, table=True):
    """全书三幕图 + 黄金三章(每项目可多版本,取最新)。"""

    __tablename__ = "structure_map"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    version: int = 1
    payload: dict = Field(sa_column=Column(JSON))  # StructureMap
    created_at: datetime = Field(default_factory=_now)


class ConflictRecord(SQLModel, table=True):
    __tablename__ = "conflict"
    __table_args__ = (UniqueConstraint("project_id", "conflict_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    conflict_id: str = Field(index=True)
    payload: dict = Field(sa_column=Column(JSON))  # Conflict
    created_at: datetime = Field(default_factory=_now)


class PayoffBeatRecord(SQLModel, table=True):
    __tablename__ = "payoff_beat"
    __table_args__ = (UniqueConstraint("project_id", "beat_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    beat_id: str = Field(index=True)
    order_index: int = Field(default=0, index=True)
    payload: dict = Field(sa_column=Column(JSON))  # PayoffBeat
    created_at: datetime = Field(default_factory=_now)


class AnnalsCardRecord(SQLModel, table=True):
    __tablename__ = "annals_card"
    __table_args__ = (UniqueConstraint("project_id", "kind", "card_key"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str = Field(index=True)
    card_key: str = Field(index=True)
    year: int | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    payload: dict = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class IdentityAliasRecord(SQLModel, table=True):
    __tablename__ = "identity_alias"
    __table_args__ = (UniqueConstraint("project_id", "alias"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    canonical_character_id: str = Field(index=True)
    alias: str
    created_at: datetime = Field(default_factory=_now)


class VolumeRecord(SQLModel, table=True):
    __tablename__ = "volume"
    __table_args__ = (UniqueConstraint("project_id", "volume_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    volume_id: str = Field(index=True)  # 业务键,如 v1
    title: str = ""
    status: str = Field(default="draft", index=True)  # draft/confirmed/locked
    payload: dict = Field(sa_column=Column(JSON))  # 卷目标/起止状态/高潮/阶段债务
    created_at: datetime = Field(default_factory=_now)


class PlotUnitRecord(SQLModel, table=True):
    __tablename__ = "plot_unit"
    __table_args__ = (UniqueConstraint("project_id", "unit_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    unit_id: str = Field(index=True)
    volume_id: str = Field(index=True)
    status: str = Field(default="draft", index=True)  # draft/confirmed/locked
    payload: dict = Field(sa_column=Column(JSON))  # PlotUnitCard
    created_at: datetime = Field(default_factory=_now)


class ChapterRecord(SQLModel, table=True):
    __tablename__ = "chapter"
    __table_args__ = (UniqueConstraint("project_id", "chapter_key"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    chapter_key: str = Field(index=True)  # 业务键,如 v1c001
    volume_id: str = Field(index=True)
    unit_id: str = Field(index=True)
    order_index: int = Field(index=True)
    title: str = ""
    status: ChapterStatus = Field(default=ChapterStatus.PLANNED, index=True)
    revision_round: int = Field(default=0)  # Spec §6 N7:谱系内 REVISE_LOCAL 计数,重启不归零
    outline_version: int = Field(default=1)  # bump 触发 N1 重校验(M3.3b)
    outline: dict = Field(default_factory=dict, sa_column=Column(JSON))  # ChapterOutline 载荷
    target_words: int = 0
    built_on_provisional: bool = Field(default=False)  # D15:STALE 级联判定
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class SceneRecord(SQLModel, table=True):
    __tablename__ = "scene"
    __table_args__ = (UniqueConstraint("project_id", "scene_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    chapter_key: str = Field(index=True)
    scene_id: str = Field(index=True)
    order_index: int = 0
    payload: dict = Field(sa_column=Column(JSON))  # SceneCard
    version: int = 1
    created_at: datetime = Field(default_factory=_now)


class DraftVersionRecord(SQLModel, table=True):
    """候选/修订稿。lineage_id 标识 draft 谱系(REPLAN 产生新谱系,轮次重置)。"""

    __tablename__ = "draft_version"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    chapter_key: str = Field(index=True)
    candidate_id: str = Field(index=True)  # 盲化名 candidate_N
    lineage_id: str = Field(index=True)  # 谱系键(Spec §6 N7 轮次语义)
    revision_of: int | None = Field(default=None, foreign_key="draft_version.id")
    content_text: str  # 正文纯文本(D9:与元数据物理分离)
    meta: dict = Field(default_factory=dict, sa_column=Column(JSON))  # 摘要/偏离/提案
    locked_ranges: list = Field(default_factory=list, sa_column=Column(JSON))  # Spec §5
    prompt_version: str = ""
    outline_version: int = 1
    created_at: datetime = Field(default_factory=_now)


class ReviewIssueRecord(SQLModel, table=True):
    __tablename__ = "review_issue"
    __table_args__ = (UniqueConstraint("draft_version_id", "issue_id"),)

    id: int | None = Field(default=None, primary_key=True)
    draft_version_id: int = Field(foreign_key="draft_version.id", index=True)
    issue_id: str
    reviewer_role: str = Field(index=True)
    severity: str = Field(index=True)
    hard_gate: str | None = Field(default=None, index=True)
    downweighted: bool = False
    status: str = Field(default="open", index=True)  # open/accepted/rejected/resolved
    payload: dict = Field(sa_column=Column(JSON))  # ReviewIssue
    created_at: datetime = Field(default_factory=_now)


class JudgeVerdictRecord(SQLModel, table=True):
    __tablename__ = "judge_verdict"

    id: int | None = Field(default=None, primary_key=True)
    draft_version_id: int = Field(foreign_key="draft_version.id", index=True)
    chapter_key: str = Field(index=True)
    verdict: str = Field(index=True)
    round_number: int = 1  # 本谱系第几轮裁决
    payload: dict = Field(sa_column=Column(JSON))  # JudgeVerdict
    created_at: datetime = Field(default_factory=_now)


class CanonDeltaRecord(SQLModel, table=True):
    """正史增量。idempotency_key 保证 canon 不重复提交(Spec §6 N9)。"""

    __tablename__ = "canon_delta"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    chapter_key: str = Field(index=True)
    base_canon_version: str
    status: str = Field(default="proposed", index=True)  # proposed/committed/rolled_back
    provisional: bool = Field(default=False, index=True)  # D15:批次内提案态
    idempotency_key: str
    payload: dict = Field(sa_column=Column(JSON))  # CanonDelta
    committed_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class EntityStateRecord(SQLModel, table=True):
    """章节边界实体状态(PRD §13.1;CanonDelta 提交后的当前态)。"""

    __tablename__ = "entity_state"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    entity_id: str = Field(index=True)
    state_type: str = Field(index=True)
    value: str
    reason: str = ""
    source_chapter: str = Field(index=True)
    provisional: bool = Field(default=False, index=True)  # D15
    created_at: datetime = Field(default_factory=_now)


class PlotThreadRecord(SQLModel, table=True):
    __tablename__ = "plot_thread"
    __table_args__ = (UniqueConstraint("project_id", "thread_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    thread_id: str = Field(index=True)
    kind: str = Field(default="foreshadowing", index=True)  # main/sub/foreshadowing
    status: str = Field(default="setup", index=True)  # setup/progressing/resolved
    setup: str = ""
    planned_payoff: str = ""
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=_now)


class ApprovalRecord(SQLModel, table=True):
    """人工门禁记录(PRD §13.1 Approval)。"""

    __tablename__ = "approval"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    target_type: str = Field(index=True)  # kernel/volume/unit/chapter/canon_delta
    target_key: str = Field(index=True)
    target_version: str = ""
    decision: str = Field(index=True)  # approved/rejected
    note: str = ""
    created_at: datetime = Field(default_factory=_now)


class ModelRunRecord(SQLModel, table=True):
    """每次模型调用(PRD §8.11 全字段;M2.1 DoD 断言非空)。"""

    __tablename__ = "model_run"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int | None = Field(default=None, index=True)
    chapter_key: str = Field(default="", index=True)
    agent_role: str = Field(index=True)
    provider: str
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    retries: int = 0
    cost_estimate: float = 0.0
    status: str = Field(default="ok", index=True)  # ok/error
    error: str = ""
    input_ref: str = ""  # 关联输入版本
    output_ref: str = ""  # 关联输出版本
    created_at: datetime = Field(default_factory=_now)


class WorkflowRunRecord(SQLModel, table=True):
    __tablename__ = "workflow_run"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str = Field(index=True)  # planning/chapter_loop/batch
    chapter_key: str = Field(default="", index=True)
    batch_id: str = Field(default="", index=True)
    status: str = Field(default="running", index=True)  # running/paused/succeeded/failed
    current_node: str = ""
    budget_spent: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class NodeRunRecord(SQLModel, table=True):
    """节点执行记录(Spec §6:快照/幂等/租约;N5 按 reviewer 用 sub_key 子记录)。"""

    __tablename__ = "node_run"
    __table_args__ = (UniqueConstraint("idempotency_key", "attempt"),)

    id: int | None = Field(default=None, primary_key=True)
    workflow_run_id: int = Field(foreign_key="workflow_run.id", index=True)
    node_name: str = Field(index=True)
    sub_key: str = Field(default="", index=True)  # 如 reviewer 名
    attempt: int = 1
    status: str = Field(default="running", index=True)  # running/succeeded/failed/skipped
    idempotency_key: str = Field(index=True)
    input_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    output_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    lease_until: datetime | None = None
    budget_spent: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
