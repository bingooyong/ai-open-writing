"""大纲层 Schema:剧情单元卡与章纲(PRD §2.7/§2.9)。"""

from pydantic import Field

from novel_agent.domain.schemas.base import VersionedSchema


class PlotUnitCard(VersionedSchema):
    """剧情单元:5~15 章的局部戏剧闭环(PRD §2.7 YAML 全字段)。"""

    unit_id: str = Field(min_length=1)
    position_in_volume: str = Field(min_length=1)
    promise_or_debt: str = Field(min_length=1, description="本单元兑现的承诺或期待债务")
    trigger: str = Field(min_length=1)
    protagonist_goal: str = Field(min_length=1)
    opposition: str = Field(min_length=1)
    escalation_beats: list[str] = Field(min_length=1, description="升级节拍")
    midpoint_change: str = Field(min_length=1)
    irreversible_choice: str = Field(min_length=1, description="不可撤销的选择")
    climax: str = Field(min_length=1)
    payoff: str = Field(min_length=1)
    aftermath: str = ""
    new_debt: str = Field(default="", description="产生的新期待债务")
    character_arc_delta: str = ""
    relationship_delta: str = ""
    canon_constraints: list[str] = Field(default_factory=list, description="禁释边界等硬约束")


class LineDeltas(VersionedSchema):
    """五线增量(PRD §2.7 全书蓝图五线 → 章级增量)。"""

    main_plot: str = ""
    protagonist_arc: str = ""
    relationship: str = ""
    information: str = ""
    foreshadowing: str = ""


class ChapterOutline(VersionedSchema):
    """章纲:回答"这一章为什么存在"(PRD §2.9)。写前守卫 N1 的校验对象。"""

    chapter_key: str = Field(min_length=1, description="业务键,如 v1c003")
    volume_id: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    title: str = ""
    core_event: str = Field(min_length=1)
    pov: str = Field(min_length=1)
    time_location: str = Field(min_length=1)
    protagonist_goal: str = Field(min_length=1)
    key_choice: str = Field(min_length=1)
    start_state: str = Field(min_length=1)
    end_state: str = Field(min_length=1)
    emotion_shift: str = Field(min_length=1, description="目标情绪 前态→后态")
    line_deltas: LineDeltas = Field(default_factory=LineDeltas)
    reveal_allowed: list[str] = Field(default_factory=list)
    reveal_forbidden: list[str] = Field(default_factory=list)
    entry_point: str = Field(min_length=1, description="章首进入点")
    exit_hook: str = Field(min_length=1, description="章尾推动力")
    target_words: int = Field(gt=0)
    cited_conflict_ids: list[str] = Field(default_factory=list)
    cited_beat_ids: list[str] = Field(default_factory=list)
