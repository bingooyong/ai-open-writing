"""预算门禁(M1.6,PRD §8.11):节点入口检查,超限暂停等人工决定。"""

from novel_agent.config import Settings
from novel_agent.domain.repos.ops import OpsRepo


class BudgetExceeded(Exception):
    def __init__(self, chapter_key: str, calls: int, limit: int) -> None:
        self.chapter_key = chapter_key
        self.calls = calls
        self.limit = limit
        super().__init__(f"章 {chapter_key} 模型调用 {calls} 次,已达上限 {limit},工作流暂停")


def check_chapter_budget(
    ops: OpsRepo,
    chapter_key: str,
    settings: Settings,
    workflow_run_id: int | None = None,
) -> None:
    calls = ops.calls_for_chapter(chapter_key, workflow_run_id=workflow_run_id)
    if calls >= settings.max_calls_per_chapter:
        raise BudgetExceeded(chapter_key, calls, settings.max_calls_per_chapter)
