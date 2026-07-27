"""工作流层:显式状态机、节点执行器、预算门禁(Spec §6)。"""

from novel_agent.workflow.budget import BudgetExceeded, check_chapter_budget
from novel_agent.workflow.errors import IllegalTransition, NodeFailed, WorkflowPaused
from novel_agent.workflow.runner import run_node
from novel_agent.workflow.state_machine import assert_transition, transition

__all__ = [
    "BudgetExceeded",
    "IllegalTransition",
    "NodeFailed",
    "WorkflowPaused",
    "assert_transition",
    "check_chapter_budget",
    "run_node",
    "transition",
]
