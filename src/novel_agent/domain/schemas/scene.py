"""场景卡(PRD §2.9 YAML 全字段):可直接写成正文的最小戏剧单元。"""

from pydantic import Field

from novel_agent.domain.schemas.base import VersionedSchema


class SceneCard(VersionedSchema):
    scene_id: str = Field(min_length=1)
    chapter_key: str = Field(min_length=1)
    pov: str = Field(min_length=1)
    time: str = Field(min_length=1)
    location: str = Field(min_length=1)
    entry_state: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    obstacle: str = Field(min_length=1)
    stakes: str = Field(min_length=1)
    turning_point: str = Field(min_length=1)
    choice: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    emotional_shift: str = Field(min_length=1)
    information_revealed: list[str] = Field(default_factory=list)
    information_withheld: list[str] = Field(default_factory=list)
    relationship_shift: str = ""
    canon_delta_expected: str = Field(default="", description="预期状态变化摘要")
    exit_hook: str = ""
    word_budget: int = Field(gt=0)
