"""稿件契约:场景稿、候选稿(D16 两段式组装结果)。"""

from pydantic import Field

from novel_agent.domain.schemas.base import VersionedSchema
from novel_agent.domain.schemas.canon_delta import CanonDelta


class SceneDraft(VersionedSchema):
    """单场景正文(D16:传输时正文走纯文本通道,本对象为组装结果)。"""

    scene_id: str = Field(min_length=1)
    content: str = Field(min_length=1, description="场景正文纯文本")


class DraftCandidate(VersionedSchema):
    """候选稿(盲化):Writer 输出经 gateway 组装 + 应用层盲化后的形态。

    candidate_id 为盲化名(candidate_1/2);与 Writer 实体的映射只存 NodeRun 快照(D11)。
    正文与结构化元数据物理分离(D9):content 仅在 scenes[].content。
    """

    candidate_id: str = Field(min_length=1, pattern=r"^candidate_\d+$")
    chapter_key: str = Field(min_length=1)
    scenes: list[SceneDraft] = Field(min_length=1)
    chapter_summary: str = Field(min_length=1)
    canon_proposals: CanonDelta | None = Field(
        default=None, description="Writer 附带的状态变更提案(最终以 Canon Curator 抽取为准)"
    )
    deviation_notes: str = Field(default="", description="对章纲的偏离说明")

    def full_text(self) -> str:
        """合并全部场景正文(导出/评审用)。"""
        return "\n\n".join(s.content for s in self.scenes)
