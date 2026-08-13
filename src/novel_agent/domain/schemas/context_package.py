"""章节上下文包(PRD §2.10 清单 + §12.2 组装顺序 + D15 provisional 区分)。"""

from pydantic import Field

from novel_agent.domain.schemas.base import VersionedSchema
from novel_agent.domain.schemas.character import CharacterCard
from novel_agent.domain.schemas.outline import ChapterOutline, PlotUnitCard
from novel_agent.domain.schemas.scene import SceneCard


class CanonFact(VersionedSchema):
    """注入上下文的单条正史事实,带 provisional 标记(D15)。"""

    content: str = Field(min_length=1)
    provisional: bool = Field(
        default=False, description="True=来自批次内未批准前章的提案态 canon"
    )
    source_chapter: str = Field(default="", description="来源章节业务键")


class ThreadStatus(VersionedSchema):
    """待推进/回收的伏笔状态摘要。"""

    thread_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    status: str = Field(min_length=1)


class ChapterContextPackage(VersionedSchema):
    """单章生产的唯一输入(PRD §2.10:只包含"不知道就会写错"的信息)。

    组装顺序与裁剪优先级见 PRD §12.2:超预算时优先保留硬约束/章纲/实体状态,
    压缩早期原文与低相关片段(由 ContextBuilder 实现,M3.1)。
    """

    chapter_key: str = Field(min_length=1)
    canon_version: str = Field(min_length=1, description="构建所基于的 canon 快照版本")
    task_brief: str = Field(min_length=1, description="本章任务说明")
    hard_constraints: list[CanonFact] = Field(default_factory=list, description="相关正史硬约束")
    kernel_summary: str = Field(min_length=1, description="故事内核+读者契约摘要")
    volume_summary: str = Field(min_length=1)
    unit_card: PlotUnitCard
    outline: ChapterOutline
    scene_cards: list[SceneCard] = Field(min_length=1)
    previous_ending: str = Field(default="", description="上一章结尾原文窗口")
    earlier_summaries: list[str] = Field(default_factory=list, description="更早章节分层摘要")
    retrieval_facts: list[str] = Field(
        default_factory=list, description="与本章实体和伏笔相关的检索片段"
    )
    characters: list[CharacterCard] = Field(default_factory=list, description="本章出场角色")
    entity_states: list[CanonFact] = Field(default_factory=list, description="出场实体动态状态")
    active_threads: list[ThreadStatus] = Field(default_factory=list)
    style_rules: str = Field(default="", description="作者批准的风格规则")
    prior_feedback: str = Field(default="", description="上一轮审校意见(修订时)")
    boundaries: list[str] = Field(default_factory=list, description="do_not_write 等内容边界")

    def has_provisional(self) -> bool:
        """是否依赖了提案态 canon(D15:用于 STALE 级联判定)。"""
        return any(f.provisional for f in [*self.hard_constraints, *self.entity_states])
