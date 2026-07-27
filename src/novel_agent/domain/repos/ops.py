"""运行态仓储:审批/模型调用/工作流与节点(幂等、租约、恢复)。"""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from novel_agent.domain.models import (
    ApprovalRecord,
    ModelRunRecord,
    NodeRunRecord,
    WorkflowRunRecord,
)


class OpsRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- 审批 ----

    def save_approval(
        self,
        project_id: int,
        target_type: str,
        target_key: str,
        decision: str,
        note: str = "",
        target_version: str = "",
    ) -> ApprovalRecord:
        rec = ApprovalRecord(
            project_id=project_id,
            target_type=target_type,
            target_key=target_key,
            target_version=target_version,
            decision=decision,
            note=note,
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def has_approval(self, project_id: int, target_type: str, target_key: str) -> bool:
        rec = self.s.exec(
            select(ApprovalRecord)
            .where(
                ApprovalRecord.project_id == project_id,
                ApprovalRecord.target_type == target_type,
                ApprovalRecord.target_key == target_key,
            )
            .order_by(ApprovalRecord.id.desc())  # type: ignore[union-attr]
        ).first()
        return bool(rec and rec.decision == "approved")

    # ---- 模型调用(PRD §8.11) ----

    def record_model_run(self, **kwargs: object) -> ModelRunRecord:
        rec = ModelRunRecord(**kwargs)  # type: ignore[arg-type]
        self.s.add(rec)
        self.s.flush()
        return rec

    def calls_for_chapter(self, chapter_key: str) -> int:
        return len(
            self.s.exec(
                select(ModelRunRecord).where(ModelRunRecord.chapter_key == chapter_key)
            ).all()
        )

    # ---- 工作流 ----

    def create_workflow_run(
        self, project_id: int, kind: str, chapter_key: str = "", batch_id: str = ""
    ) -> WorkflowRunRecord:
        rec = WorkflowRunRecord(
            project_id=project_id, kind=kind, chapter_key=chapter_key, batch_id=batch_id
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_workflow_run(self, run_id: int) -> WorkflowRunRecord:
        return self.s.get_one(WorkflowRunRecord, run_id)

    def find_resumable_run(
        self, project_id: int, kind: str, chapter_key: str = ""
    ) -> WorkflowRunRecord | None:
        stmt = select(WorkflowRunRecord).where(
            WorkflowRunRecord.project_id == project_id,
            WorkflowRunRecord.kind == kind,
            WorkflowRunRecord.status.in_(["running", "paused"]),  # type: ignore[attr-defined]
        )
        if chapter_key:
            stmt = stmt.where(WorkflowRunRecord.chapter_key == chapter_key)
        return self.s.exec(stmt.order_by(WorkflowRunRecord.id.desc())).first()  # type: ignore[union-attr]

    def update_workflow(
        self, run_id: int, status: str | None = None, current_node: str | None = None
    ) -> None:
        rec = self.get_workflow_run(run_id)
        if status:
            rec.status = status
        if current_node is not None:
            rec.current_node = current_node
        rec.updated_at = datetime.now(UTC)
        self.s.add(rec)

    # ---- 节点(幂等/快照/租约,Spec §6 通用机制) ----

    def find_success_node(self, idempotency_key: str) -> NodeRunRecord | None:
        """幂等命中:同 key 已成功 → 直接复用 output_snapshot,不重跑。"""
        return self.s.exec(
            select(NodeRunRecord).where(
                NodeRunRecord.idempotency_key == idempotency_key,
                NodeRunRecord.status == "succeeded",
            )
        ).first()

    def start_node(
        self,
        workflow_run_id: int,
        node_name: str,
        idempotency_key: str,
        input_snapshot: dict,
        sub_key: str = "",
        lease_minutes: int = 30,
    ) -> NodeRunRecord:
        prev_attempts = self.s.exec(
            select(NodeRunRecord).where(NodeRunRecord.idempotency_key == idempotency_key)
        ).all()
        rec = NodeRunRecord(
            workflow_run_id=workflow_run_id,
            node_name=node_name,
            sub_key=sub_key,
            attempt=len(prev_attempts) + 1,
            idempotency_key=idempotency_key,
            input_snapshot=input_snapshot,
            lease_until=datetime.now(UTC) + timedelta(minutes=lease_minutes),
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def finish_node(
        self, node_run_id: int, status: str, output_snapshot: dict | None = None, error: str = ""
    ) -> None:
        rec = self.s.get_one(NodeRunRecord, node_run_id)
        rec.status = status
        rec.output_snapshot = output_snapshot or {}
        rec.error = error
        rec.updated_at = datetime.now(UTC)
        self.s.add(rec)

    def node_history(self, workflow_run_id: int) -> list[NodeRunRecord]:
        return list(
            self.s.exec(
                select(NodeRunRecord)
                .where(NodeRunRecord.workflow_run_id == workflow_run_id)
                .order_by(NodeRunRecord.id)  # type: ignore[arg-type]
            ).all()
        )
