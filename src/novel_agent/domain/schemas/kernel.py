"""故事内核与读者契约(PRD §2.5)。"""

from pydantic import Field

from novel_agent.domain.schemas.base import VersionedSchema


class StoryKernel(VersionedSchema):
    """故事内核卡:开书门禁 A/B 的确认对象,锁定后为全书硬约束。"""

    premise: str = Field(min_length=1, description="如果……会怎样")
    logline: str = Field(min_length=1, description="主角+目标+主要阻碍+独特反转")
    theme_question: str = Field(min_length=1, description="故事持续追问但不提前回答的问题")
    dramatic_question: str = Field(min_length=1, description="读者追到结局想知道的具体结果")
    value_shift: str = Field(min_length=1, description="核心价值从什么状态转向什么状态")
    ending_proof: str = Field(min_length=1, description="结局用哪个选择或结果回答主题")
    reader_promise: str = Field(min_length=1, description="本书稳定交付的阅读体验")
    expectation_debts: list[str] = Field(default_factory=list, description="已许诺未兑现项")
    do_not_write: list[str] = Field(default_factory=list, description="内容/风格/剧情边界")


class KernelCandidateSet(VersionedSchema):
    """规划链产出:三个差异化候选(PRD §8.1),供人工选定。"""

    candidates: list[StoryKernel] = Field(min_length=2, max_length=4)
    differentiation_notes: str = Field(min_length=1, description="候选间差异说明,不能只换人名背景")
