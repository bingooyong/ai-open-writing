"""节点执行器:幂等命中→复用快照;失败→重试→NodeFailed(Spec §6 通用机制)。"""

from collections.abc import Awaitable, Callable

from novel_agent.domain.repos.ops import OpsRepo
from novel_agent.workflow.errors import NodeFailed, WorkflowPaused


def _begin_node(
    ops: OpsRepo,
    workflow_run_id: int,
    node_name: str,
    idempotency_key: str,
    budget_check: Callable[[], None] | None,
) -> dict | None:
    hit = ops.find_success_node(idempotency_key)
    if hit is not None:
        return hit.output_snapshot
    if budget_check is not None:
        budget_check()
    ops.update_workflow(workflow_run_id, current_node=node_name)
    return None


def _record_success(ops: OpsRepo, node_run_id: int, out: dict) -> dict:
    ops.finish_node(node_run_id, "succeeded", out)
    ops.s.commit()
    return out


def _record_failure(ops: OpsRepo, node_run_id: int, exc: BaseException) -> str:
    last_error = f"{type(exc).__name__}: {exc}"
    ops.finish_node(node_run_id, "failed", error=last_error)
    ops.s.commit()
    return last_error


def run_node(
    ops: OpsRepo,
    workflow_run_id: int,
    node_name: str,
    idempotency_key: str,
    input_snapshot: dict,
    fn: Callable[[], dict],
    *,
    sub_key: str = "",
    max_retries: int = 0,
    budget_check: Callable[[], None] | None = None,
) -> dict:
    """执行一个节点。

    - 幂等:同 idempotency_key 已成功 → 直接返回历史 output_snapshot,不执行 fn。
    - 预算:入口调用 budget_check(可抛 BudgetExceeded → 由调用方转 PAUSED)。
    - 失败:记录 failed NodeRun;重试 max_retries 次;耗尽抛 NodeFailed。
    - fn 返回 dict(可 JSON 序列化),作为 output_snapshot 落库。
    """
    cached = _begin_node(ops, workflow_run_id, node_name, idempotency_key, budget_check)
    if cached is not None:
        return cached

    last_error = ""
    for _attempt in range(max_retries + 1):
        rec = ops.start_node(
            workflow_run_id, node_name, idempotency_key, input_snapshot, sub_key=sub_key
        )
        assert rec.id is not None  # flush 后必有主键
        ops.s.commit()  # start 记录立即持久化:崩溃后 attempt 计数不丢
        try:
            out = fn()
        except WorkflowPaused:
            ops.finish_node(rec.id, "skipped", error="paused")
            ops.s.commit()
            raise
        except Exception as exc:  # noqa: BLE001 — 节点边界必须兜住任意失败
            last_error = _record_failure(ops, rec.id, exc)
            continue
        return _record_success(ops, rec.id, out)

    raise NodeFailed(node_name, last_error)


async def run_node_async(
    ops: OpsRepo,
    workflow_run_id: int,
    node_name: str,
    idempotency_key: str,
    input_snapshot: dict,
    fn: Callable[[], Awaitable[dict]],
    *,
    sub_key: str = "",
    max_retries: int = 0,
    budget_check: Callable[[], None] | None = None,
) -> dict:
    """run_node 的异步版:fn 为 coroutine,供单章循环里的模型节点使用。"""
    cached = _begin_node(ops, workflow_run_id, node_name, idempotency_key, budget_check)
    if cached is not None:
        return cached

    last_error = ""
    for _attempt in range(max_retries + 1):
        rec = ops.start_node(
            workflow_run_id, node_name, idempotency_key, input_snapshot, sub_key=sub_key
        )
        assert rec.id is not None
        ops.s.commit()
        try:
            out = await fn()
        except WorkflowPaused:
            ops.finish_node(rec.id, "skipped", error="paused")
            ops.s.commit()
            raise
        except Exception as exc:  # noqa: BLE001 — 节点边界必须兜住任意失败
            last_error = _record_failure(ops, rec.id, exc)
            continue
        return _record_success(ops, rec.id, out)

    raise NodeFailed(node_name, last_error)
