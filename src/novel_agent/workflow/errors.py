"""工作流异常。"""


class IllegalTransition(Exception):
    """非法章节状态转移。"""


class NodeFailed(Exception):
    """节点重试耗尽后仍失败。"""

    def __init__(self, node_name: str, message: str) -> None:
        self.node_name = node_name
        super().__init__(f"节点 {node_name} 失败: {message}")


class WorkflowPaused(Exception):
    """预算或人工门禁触发暂停(非错误,控制流信号)。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
