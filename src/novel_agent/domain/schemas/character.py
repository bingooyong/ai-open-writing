"""角色档案(PRD §2.6 六层信息 + 档案字段)。"""

from pydantic import Field

from novel_agent.domain.schemas.base import VersionedSchema


class VoiceProfile(VersionedSchema):
    """对白画像:不只记录口头禅(PRD §2.6)。"""

    vocabulary: str = ""
    sentence_style: str = ""
    avoidance: str = Field(default="", description="回避方式")
    address_habits: str = Field(default="", description="称呼习惯")
    lying_pattern: str = Field(default="", description="撒谎方式")
    under_pressure: str = Field(default="", description="压力下的语言变化")


class CharacterCard(VersionedSchema):
    """主要角色档案(PRD §2.6 YAML 全字段)。"""

    character_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    identity: str = Field(min_length=1)
    story_function: str = Field(min_length=1, description="主角/对手/盟友/镜像/导师等功能位")
    external_goal: str = Field(min_length=1)
    internal_need: str = Field(min_length=1)
    motivation: str = Field(min_length=1)
    fear: str = Field(min_length=1)
    misbelief: str = Field(default="", description="错误认知(弧线起点)")
    strengths: list[str] = Field(default_factory=list)
    flaws: list[str] = Field(default_factory=list)
    red_lines: list[str] = Field(default_factory=list, description="绝不会做的事")
    decision_pattern: str = ""
    voice_profile: VoiceProfile = Field(default_factory=VoiceProfile)
    knowledge_state: list[str] = Field(default_factory=list, description="当前已知信息")
    secret_state: list[str] = Field(default_factory=list, description="持有的秘密")
    resources: list[str] = Field(default_factory=list)
    reputation: str = ""
    start_state: str = Field(min_length=1, description="弧线起点状态")
    turning_points: list[str] = Field(default_factory=list)
    end_state: str = Field(min_length=1, description="弧线终点状态(结局承诺)")
