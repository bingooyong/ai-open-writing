"""生产链仓储:稿件版本/评审问题/裁决。"""

from sqlmodel import Session, select

from novel_agent.domain.models import DraftVersionRecord, JudgeVerdictRecord, ReviewIssueRecord
from novel_agent.domain.schemas import JudgeVerdict, ReviewIssue, VerdictType


class ProductionRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- 稿件 ----

    def create_draft(
        self,
        project_id: int,
        chapter_key: str,
        candidate_id: str,
        lineage_id: str,
        content_text: str,
        meta: dict,
        prompt_version: str,
        outline_version: int,
        revision_of: int | None = None,
        locked_ranges: list | None = None,
    ) -> DraftVersionRecord:
        rec = DraftVersionRecord(
            project_id=project_id,
            chapter_key=chapter_key,
            candidate_id=candidate_id,
            lineage_id=lineage_id,
            content_text=content_text,
            meta=meta,
            prompt_version=prompt_version,
            outline_version=outline_version,
            revision_of=revision_of,
            locked_ranges=locked_ranges or [],
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_draft(self, draft_id: int) -> DraftVersionRecord:
        return self.s.get_one(DraftVersionRecord, draft_id)

    def latest_draft(
        self, project_id: int, chapter_key: str, lineage_id: str, candidate_id: str
    ) -> DraftVersionRecord | None:
        return self.s.exec(
            select(DraftVersionRecord)
            .where(
                DraftVersionRecord.project_id == project_id,
                DraftVersionRecord.chapter_key == chapter_key,
                DraftVersionRecord.lineage_id == lineage_id,
                DraftVersionRecord.candidate_id == candidate_id,
            )
            .order_by(DraftVersionRecord.id.desc())  # type: ignore[union-attr]
        ).first()

    def set_locked_ranges(self, draft_id: int, locked_ranges: list) -> None:
        rec = self.get_draft(draft_id)
        rec.locked_ranges = locked_ranges
        self.s.add(rec)

    def latest_chapter_draft(
        self, project_id: int, chapter_key: str
    ) -> DraftVersionRecord | None:
        drafts = [
            rec
            for rec in self.list_drafts(project_id, chapter_key)
            if not (rec.meta or {}).get("voided")
            and not rec.lineage_id.startswith("voided:")
        ]
        return drafts[-1] if drafts else None

    def void_lineage(self, project_id: int, chapter_key: str) -> int:
        """REPLAN/STALE:作废该章全部 draft 谱系。"""
        n = 0
        for rec in self.list_drafts(project_id, chapter_key):
            if rec.lineage_id.startswith("voided:") or (rec.meta or {}).get("voided"):
                continue
            meta = dict(rec.meta or {})
            meta["voided"] = True
            rec.meta = meta
            rec.lineage_id = f"voided:{rec.lineage_id}"
            self.s.add(rec)
            n += 1
        return n

    # ---- 评审问题 ----

    def save_issues(self, draft_version_id: int, issues: list[ReviewIssue]) -> None:
        for issue in issues:
            self.s.add(
                ReviewIssueRecord(
                    draft_version_id=draft_version_id,
                    issue_id=issue.issue_id,
                    reviewer_role=issue.reviewer_role.value,
                    severity=issue.severity.value,
                    hard_gate=issue.hard_gate.value if issue.hard_gate else None,
                    downweighted=issue.downweighted,
                    payload=issue.model_dump(),
                )
            )

    def list_issues(self, draft_version_id: int) -> list[ReviewIssue]:
        recs = self.s.exec(
            select(ReviewIssueRecord).where(
                ReviewIssueRecord.draft_version_id == draft_version_id
            )
        ).all()
        return [ReviewIssue.model_validate(r.payload) for r in recs]

    def set_issue_status(self, draft_version_id: int, issue_id: str, status: str) -> None:
        rec = self.s.exec(
            select(ReviewIssueRecord).where(
                ReviewIssueRecord.draft_version_id == draft_version_id,
                ReviewIssueRecord.issue_id == issue_id,
            )
        ).one()
        rec.status = status
        self.s.add(rec)

    # ---- 裁决 ----

    def save_verdict(
        self,
        draft_version_id: int,
        chapter_key: str,
        verdict: JudgeVerdict,
        round_number: int,
    ) -> JudgeVerdictRecord:
        rec = JudgeVerdictRecord(
            draft_version_id=draft_version_id,
            chapter_key=chapter_key,
            verdict=verdict.verdict.value,
            round_number=round_number,
            payload=verdict.model_dump(),
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def list_drafts(
        self,
        project_id: int,
        chapter_key: str,
        lineage_id: str | None = None,
    ) -> list[DraftVersionRecord]:
        stmt = select(DraftVersionRecord).where(
            DraftVersionRecord.project_id == project_id,
            DraftVersionRecord.chapter_key == chapter_key,
        )
        if lineage_id is not None:
            stmt = stmt.where(DraftVersionRecord.lineage_id == lineage_id)
        return list(
            self.s.exec(stmt.order_by(DraftVersionRecord.id)).all()  # type: ignore[arg-type]
        )

    def latest_verdict_record(self, chapter_key: str) -> JudgeVerdictRecord | None:
        return self.s.exec(
            select(JudgeVerdictRecord)
            .where(JudgeVerdictRecord.chapter_key == chapter_key)
            .order_by(JudgeVerdictRecord.id.desc())  # type: ignore[union-attr]
        ).first()

    def latest_verdict(self, chapter_key: str) -> JudgeVerdict | None:
        rec = self.latest_verdict_record(chapter_key)
        return JudgeVerdict.model_validate(rec.payload) if rec else None

    def revise_local_rounds(self, chapter_key: str, lineage_draft_ids: list[int]) -> int:
        """谱系内 REVISE_LOCAL 裁决次数(Spec §6 N7 轮次语义的推导口径)。"""
        if not lineage_draft_ids:
            return 0
        recs = self.s.exec(
            select(JudgeVerdictRecord).where(
                JudgeVerdictRecord.chapter_key == chapter_key,
                JudgeVerdictRecord.draft_version_id.in_(lineage_draft_ids),  # type: ignore[attr-defined]
                JudgeVerdictRecord.verdict == VerdictType.REVISE_LOCAL.value,
            )
        ).all()
        return len(recs)
