"""单章循环编排:N1→N9 接表驱动 FSM(Spec §6)。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import assert_never

from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.context.context_builder import ContextBuilder
from novel_agent.memory.factory import memory_retrieval_for_session
from novel_agent.domain.canon_writer import CanonWriter
from novel_agent.domain.models import DraftVersionRecord
from novel_agent.domain.repos import CanonRepo, OpsRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import (
    CanonDelta,
    ChapterContextPackage,
    ChapterStatus,
    DraftCandidate,
    JudgeVerdict,
    ReviewerRole,
    ReviewIssue,
    ReviewReport,
    RevisionOrder,
    SceneDraft,
    VerdictType,
)
from novel_agent.gateway.structured import StructuredOutputError
from novel_agent.lint import lint_draft
from novel_agent.planning.settings import desk_settings, review_roles_for
from novel_agent.runtime.agents import (
    CRITICAL_REVIEWERS,
    AgentDeps,
    new_lineage_id,
    run_canon_curator,
    run_judge,
    run_reviewer,
    run_reviser,
    run_writer,
)
from novel_agent.runtime.blinding import blind_candidates
from novel_agent.runtime.prompts import load_prompt
from novel_agent.workflow import (
    BudgetExceeded,
    NodeFailed,
    WorkflowPaused,
    check_chapter_budget,
    run_node,
    run_node_async,
    transition,
)


class ChapterLoopError(Exception):
    """单章循环硬失败(缺项目/非法状态/写前守卫)。"""


@dataclass(frozen=True)
class ChapterLoopPreview:
    project_id: int
    chapter_key: str
    verdict: VerdictType | None
    draft_id: int | None


@dataclass(frozen=True)
class ChapterLoopGates:
    """N8 人工门禁:仅 PASS 裁决后才会询问。"""

    approve: Callable[[ChapterLoopPreview], bool]

    @staticmethod
    def auto() -> ChapterLoopGates:
        return ChapterLoopGates(approve=lambda _preview: True)

    @staticmethod
    def hold() -> ChapterLoopGates:
        return ChapterLoopGates(approve=lambda _preview: False)


@dataclass
class ChapterLoopResult:
    project_id: int
    chapter_key: str
    status: ChapterStatus
    verdict: VerdictType | None
    revision_round: int
    workflow_run_id: int
    draft_id: int | None
    lineage_id: str
    stopped_at: str
    reason: str = ""


@dataclass
class _LoopState:
    lineage_id: str
    draft_id: int | None = None
    draft_ids: list[int] = field(default_factory=list)
    workflow_run_id: int = 0
    outline_ver: int = 1


def draft_from_record(rec: DraftVersionRecord) -> DraftCandidate:
    meta = rec.meta or {}
    scenes = [SceneDraft.model_validate(item) for item in meta["scenes"]]
    return DraftCandidate(
        candidate_id=rec.candidate_id,
        chapter_key=rec.chapter_key,
        scenes=scenes,
        chapter_summary=str(meta.get("chapter_summary") or "摘要"),
        deviation_notes=str(meta.get("deviation_notes") or ""),
    )


def sanitize_verdict(verdict: JudgeVerdict, issues: list[ReviewIssue]) -> JudgeVerdict:
    """无证据 issue 不得作为阻断项(Spec §7):强制驳回并剔除仅由其支撑的硬门禁。"""
    downweighted = {issue.issue_id for issue in issues if issue.downweighted}
    rulings = []
    for ruling in verdict.rulings:
        if ruling.issue_id in downweighted and ruling.accepted:
            rulings.append(
                ruling.model_copy(
                    update={
                        "accepted": False,
                        "reason": f"{ruling.reason}（无证据降权,不得作为阻断依据）",
                    }
                )
            )
        else:
            rulings.append(ruling)

    cleaned_gates = []
    for gate in verdict.hard_gate_failures:
        supporting = [issue for issue in issues if issue.hard_gate is gate]
        if supporting and all(issue.downweighted for issue in supporting):
            continue
        cleaned_gates.append(gate)
    updates: dict[str, object] = {"rulings": rulings, "hard_gate_failures": cleaned_gates}
    remaining_accepted = [item for item in rulings if item.accepted]
    if (
        verdict.verdict
        in {VerdictType.REVISE_LOCAL, VerdictType.REPLAN_SCENE, VerdictType.REPLAN_CHAPTER}
        and not cleaned_gates
        and not remaining_accepted
    ):
        updates.update(
            {
                "verdict": VerdictType.PASS,
                "rollback_target": None,
                "revision_scope": [],
                "reasoning_summary": (
                    f"{verdict.reasoning_summary}（无证据项已降权,不得作为阻断）"
                ),
            }
        )
    return verdict.model_copy(update=updates)


def _review_set_hash(issues: list[ReviewIssue], absent: list[str]) -> str:
    payload = json.dumps(
        {
            "issue_ids": sorted(issue.issue_id for issue in issues),
            "downweighted": sorted(issue.issue_id for issue in issues if issue.downweighted),
            "absent": sorted(absent),
        },
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _volume_summary(planning: PlanningRepo, project_id: int, volume_id: str) -> str:
    for volume in planning.list_volumes(project_id):
        if volume.volume_id == volume_id:
            goal = ""
            if isinstance(volume.payload, dict):
                goal = str(volume.payload.get("goal") or "")
            title = volume.title or volume_id
            return f"{title}: {goal}".rstrip(": ")
    return volume_id


async def run_chapter_loop(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
    *,
    gates: ChapterLoopGates | None = None,
    settings: Settings | None = None,
    git_root: Path | None = None,
    include_provisional: bool = False,
) -> ChapterLoopResult:
    """驱动一章走完 N1→N9;PASS 且批准后提交正史,其余路径在门禁处停下。"""
    gates = gates or ChapterLoopGates.hold()
    if settings is None:
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
    if deps.project_id is None:
        deps.project_id = project_id

    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    ops = OpsRepo(session)
    canon = CanonRepo(session)
    builder = ContextBuilder(planning, canon, retrieval=memory_retrieval_for_session(session))

    try:
        planning.get_project(project_id)
        chapter = planning.get_chapter(project_id, chapter_key)
    except Exception as exc:
        raise ChapterLoopError(f"项目或章节不存在: {project_id}/{chapter_key}") from exc

    if chapter.status is ChapterStatus.EXPORTED:
        raise ChapterLoopError("章节已导出,单章循环不再推进")

    run = ops.find_resumable_run(project_id, "chapter_loop", chapter_key)
    if run is None:
        run = ops.create_workflow_run(project_id, "chapter_loop", chapter_key)
    assert run.id is not None
    session.commit()

    state = _LoopState(
        lineage_id=new_lineage_id(),
        workflow_run_id=run.id,
        outline_ver=chapter.outline_version,
    )
    _restore_state(ops, production, project_id, chapter_key, state)

    def budget() -> None:
        check_chapter_budget(ops, chapter_key, settings)

    def ctx(*, prior_feedback: str = "") -> ChapterContextPackage:
        outline = planning.get_outline(project_id, chapter_key)
        package = builder.build(
            project_id,
            chapter_key,
            task_brief=f"撰写{chapter.title or chapter_key}：{outline.core_event}",
            volume_summary=_volume_summary(planning, project_id, outline.volume_id),
            prior_feedback=prior_feedback,
            include_provisional=include_provisional,
        )
        if package.has_provisional():
            planning.set_built_on_provisional(project_id, chapter_key, True)
        return package

    try:
        stopped_at, reason = await _advance(
            session,
            deps,
            planning,
            production,
            ops,
            project_id,
            chapter_key,
            state,
            gates,
            settings,
            git_root,
            budget,
            ctx,
        )
    except BudgetExceeded as exc:
        ops.update_workflow(state.workflow_run_id, status="paused", current_node="budget")
        session.commit()
        raise WorkflowPaused(str(exc)) from exc

    chapter = planning.get_chapter(project_id, chapter_key)
    latest = production.latest_verdict(chapter_key)
    if chapter.status is ChapterStatus.CANON_LOCKED:
        ops.update_workflow(state.workflow_run_id, status="succeeded", current_node=stopped_at)
    elif chapter.status in {ChapterStatus.HUMAN_REVIEW, ChapterStatus.NEEDS_REPLAN} or (
        stopped_at == "n4_lint"
    ):
        ops.update_workflow(state.workflow_run_id, status="paused", current_node=stopped_at)
    session.commit()
    return ChapterLoopResult(
        project_id=project_id,
        chapter_key=chapter_key,
        status=chapter.status,
        verdict=latest.verdict if latest else None,
        revision_round=chapter.revision_round,
        workflow_run_id=state.workflow_run_id,
        draft_id=state.draft_id,
        lineage_id=state.lineage_id,
        stopped_at=stopped_at,
        reason=reason,
    )


def _restore_state(
    ops: OpsRepo,
    production: ProductionRepo,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
) -> None:
    n3 = ops.find_success_node(f"{chapter_key}|{state.outline_ver}|1|n3")
    if n3 is None:
        return
    state.lineage_id = str(n3.output_snapshot.get("lineage_id") or state.lineage_id)
    raw_ids = n3.output_snapshot.get("draft_ids") or []
    state.draft_ids = [int(item) for item in raw_ids]
    drafts = production.list_drafts(project_id, chapter_key, state.lineage_id)
    if drafts:
        state.draft_id = drafts[-1].id
        if drafts[-1].revision_of is not None and drafts[-1].id is not None:
            state.draft_ids = [drafts[-1].id]
        elif not state.draft_ids:
            state.draft_ids = [row.id for row in drafts if row.id is not None]


async def _advance(
    session: Session,
    deps: AgentDeps,
    planning: PlanningRepo,
    production: ProductionRepo,
    ops: OpsRepo,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    gates: ChapterLoopGates,
    settings: Settings,
    git_root: Path | None,
    budget: Callable[[], None],
    ctx_factory: Callable[..., ChapterContextPackage],
) -> tuple[str, str]:
    for _step in range(32):
        chapter = planning.get_chapter(project_id, chapter_key)
        status = chapter.status

        if status is ChapterStatus.PLANNED:
            _n1(ops, planning, project_id, chapter_key, state)
            continue
        if status is ChapterStatus.DRAFTING:
            _n2(ops, project_id, chapter_key, state, ctx_factory)
            await _n3(ops, production, deps, project_id, chapter_key, state, budget, ctx_factory)
            if planning.get_chapter(project_id, chapter_key).status is ChapterStatus.DRAFTING:
                transition(planning, project_id, chapter_key, ChapterStatus.ADVERSARIAL_REVIEW)
                session.commit()
            continue
        if status is ChapterStatus.ADVERSARIAL_REVIEW:
            lint_out = _n4(
                ops, planning, production, project_id, chapter_key, state, ctx_factory
            )
            if not lint_out.get("passed"):
                return "n4_lint", "lint 拦截,不消耗评审"
            await _n5(
                ops, production, deps, project_id, chapter_key, state, budget, ctx_factory
            )
            if (
                planning.get_chapter(project_id, chapter_key).status
                is ChapterStatus.ADVERSARIAL_REVIEW
            ):
                transition(planning, project_id, chapter_key, ChapterStatus.JUDGING)
                session.commit()
            continue
        if status is ChapterStatus.JUDGING:
            try:
                await _n6(
                    ops, production, deps, project_id, chapter_key, state, budget, ctx_factory
                )
            except NodeFailed as exc:
                if "StructuredOutputError" not in str(exc):
                    raise
                transition(planning, project_id, chapter_key, ChapterStatus.HUMAN_REVIEW)
                session.commit()
                return "n6_judge", "Judge Schema 非法,升级人工"
            if planning.get_chapter(project_id, chapter_key).status is ChapterStatus.JUDGING:
                _apply_verdict(planning, production, project_id, chapter_key, settings)
                session.commit()
            continue
        if status is ChapterStatus.NEEDS_REVISION:
            await _n7(ops, production, deps, project_id, chapter_key, state, budget, ctx_factory)
            if planning.get_chapter(project_id, chapter_key).status is ChapterStatus.NEEDS_REVISION:
                transition(planning, project_id, chapter_key, ChapterStatus.ADVERSARIAL_REVIEW)
                session.commit()
            continue
        if status is ChapterStatus.NEEDS_REPLAN:
            return "n6_judge", "REPLAN 升级人工,等待 edit-outline"
        if status is ChapterStatus.STALE:
            transition(planning, project_id, chapter_key, ChapterStatus.DRAFTING)
            session.commit()
            continue
        if status is ChapterStatus.HUMAN_REVIEW:
            latest = production.latest_verdict(chapter_key)
            if latest is None or latest.verdict is not VerdictType.PASS:
                return "n6_judge", "硬门禁未过或非 PASS,停留人工审阅"
            preview = ChapterLoopPreview(project_id, chapter_key, latest.verdict, state.draft_id)
            if not gates.approve(preview):
                return "n8_human_gate", "等待人工批准"
            _n8(ops, project_id, chapter_key, state)
            if planning.get_chapter(project_id, chapter_key).status is ChapterStatus.HUMAN_REVIEW:
                transition(planning, project_id, chapter_key, ChapterStatus.APPROVED)
                session.commit()
            continue
        if status is ChapterStatus.APPROVED:
            await _n9(
                ops,
                production,
                deps,
                project_id,
                chapter_key,
                state,
                budget,
                ctx_factory,
                git_root,
            )
            if planning.get_chapter(project_id, chapter_key).status is ChapterStatus.APPROVED:
                transition(planning, project_id, chapter_key, ChapterStatus.CANON_LOCKED)
                session.commit()
            continue
        if status is ChapterStatus.CANON_LOCKED:
            return "n9_canon_commit", "正史已提交"
        raise ChapterLoopError(f"单章循环不处理状态 {status}")
    raise ChapterLoopError("单章循环超过步数上限")


def _n1(
    ops: OpsRepo,
    planning: PlanningRepo,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
) -> dict:
    key = f"{chapter_key}|{state.outline_ver}|n1"

    def fn() -> dict:
        transition(planning, project_id, chapter_key, ChapterStatus.DRAFTING)
        return {"outline_ver": state.outline_ver}

    return run_node(
        ops, state.workflow_run_id, "n1_validate_outline", key, {"chapter_key": chapter_key}, fn
    )


def _n2(
    ops: OpsRepo,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    ctx_factory: Callable[..., ChapterContextPackage],
) -> dict:
    package = ctx_factory()
    key = f"{chapter_key}|{package.canon_version}|n2"

    def fn() -> dict:
        built = ctx_factory()
        return {"canon_ver": built.canon_version, "chapter_key": built.chapter_key}

    return run_node(
        ops,
        state.workflow_run_id,
        "n2_build_context",
        key,
        {"project_id": project_id, "chapter_key": chapter_key, "canon_ver": package.canon_version},
        fn,
        max_retries=3,
    )


async def _n3(
    ops: OpsRepo,
    production: ProductionRepo,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    budget: Callable[[], None],
    ctx_factory: Callable[..., ChapterContextPackage],
) -> dict:
    key = f"{chapter_key}|{state.outline_ver}|1|n3"

    async def fn() -> dict:
        package = ctx_factory()
        project = PlanningRepo(ops.s).get_project(project_id)
        writer_ids = ["writer_a"]
        if desk_settings(project)["enable_writer_b"]:
            writer_ids.append("writer_b")
        gathered = await asyncio.gather(
            *[run_writer(deps, package, writer_id=wid) for wid in writer_ids],
            return_exceptions=True,
        )
        pairs: list[tuple[str, DraftCandidate]] = []
        for writer_id, result in zip(writer_ids, gathered, strict=True):
            if isinstance(result, BaseException):
                if writer_id == "writer_a":
                    raise result
                continue
            pairs.append((writer_id, result))
        blinded, mapping = blind_candidates(pairs)
        candidate_drafts: dict[str, int] = {}
        draft_ids: list[int] = []
        prompt_ver = load_prompt("writer").prompt_version
        for draft in blinded:
            rec = production.create_draft(
                project_id,
                chapter_key,
                draft.candidate_id,
                state.lineage_id,
                draft.full_text(),
                {
                    "scenes": [scene.model_dump() for scene in draft.scenes],
                    "chapter_summary": draft.chapter_summary,
                    "deviation_notes": draft.deviation_notes,
                },
                prompt_ver,
                state.outline_ver,
            )
            assert rec.id is not None
            candidate_drafts[draft.candidate_id] = rec.id
            draft_ids.append(rec.id)
        state.draft_id = draft_ids[0]
        state.draft_ids = draft_ids
        return {
            "draft_id": draft_ids[0],
            "draft_ids": draft_ids,
            "candidate_id": blinded[0].candidate_id,
            "candidate_drafts": candidate_drafts,
            "lineage_id": state.lineage_id,
            "blind_map": mapping,
        }

    out = await run_node_async(
        ops,
        state.workflow_run_id,
        "n3_draft",
        key,
        {"chapter_key": chapter_key, "outline_ver": state.outline_ver, "attempt": 1},
        fn,
        max_retries=2,
        budget_check=budget,
    )
    state.draft_id = int(out["draft_id"])
    state.draft_ids = [int(item) for item in out.get("draft_ids") or [state.draft_id]]
    state.lineage_id = str(out["lineage_id"])
    return out


def _n4(
    ops: OpsRepo,
    planning: PlanningRepo,
    production: ProductionRepo,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    ctx_factory: Callable[..., ChapterContextPackage],
) -> dict:
    if state.draft_id is None:
        raise ChapterLoopError("N4 缺少 draft_id")
    primary_id = state.draft_id
    key = f"{primary_id}|n4"

    def fn() -> dict:
        ids = state.draft_ids or [primary_id]
        package = ctx_factory()
        passed_ids: list[int] = []
        last_findings: list[str] = []
        last_codes: list[str] = []
        for draft_id in ids:
            rec = production.get_draft(draft_id)
            draft = draft_from_record(rec)
            cards = planning.list_scene_cards(project_id, chapter_key)
            original = None
            order = None
            if rec.revision_of is not None:
                original = draft_from_record(production.get_draft(rec.revision_of))
                raw_order = rec.meta.get("revision_order")
                if raw_order:
                    order = RevisionOrder.model_validate(raw_order)
            report = lint_draft(
                draft, cards, package.boundaries, original=original, order=order
            )
            last_findings = [item.message for item in report.findings]
            last_codes = [item.code for item in report.blocking]
            if report.passed:
                passed_ids.append(draft_id)
        if not passed_ids:
            return {
                "passed": False,
                "findings": last_findings,
                "blocking_codes": last_codes,
            }
        state.draft_ids = passed_ids
        state.draft_id = passed_ids[0]
        return {
            "passed": True,
            "findings": last_findings,
            "blocking_codes": [],
            "draft_ids": passed_ids,
            "draft_id": passed_ids[0],
        }

    out = run_node(
        ops,
        state.workflow_run_id,
        "n4_lint",
        key,
        {"draft_id": state.draft_id},
        fn,
        max_retries=1,
    )
    if out.get("passed") and out.get("draft_ids"):
        state.draft_ids = [int(item) for item in out["draft_ids"]]
        state.draft_id = int(out["draft_id"])
    return out


async def _n5(
    ops: OpsRepo,
    production: ProductionRepo,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    budget: Callable[[], None],
    ctx_factory: Callable[..., ChapterContextPackage],
) -> dict:
    if state.draft_id is None:
        raise ChapterLoopError("N5 缺少 draft_id")
    rec = production.get_draft(state.draft_id)
    draft = draft_from_record(rec)
    package = ctx_factory()
    project = PlanningRepo(ops.s).get_project(project_id)
    roles = review_roles_for(ops.s, project)
    pending = [
        role
        for role in roles
        if ops.find_success_node(f"{state.draft_id}|n5|{role.value}") is None
    ]
    gathered: list[ReviewReport | BaseException] = []
    if pending:
        budget()
        raw = await asyncio.gather(
            *(run_reviewer(deps, role, draft, package) for role in pending),
            return_exceptions=True,
        )
        gathered = list(raw)

    reports: list[ReviewReport] = []
    absent: list[str] = []
    critical_error: BaseException | None = None
    for role, result in zip(pending, gathered, strict=True):
        node_key = f"{state.draft_id}|n5|{role.value}"

        def persist(
            result: ReviewReport | BaseException = result, role: ReviewerRole = role
        ) -> dict:
            if isinstance(result, BaseException):
                if role in CRITICAL_REVIEWERS:
                    raise result
                return {"absent": True, "role": role.value}
            existing = {issue.issue_id for issue in production.list_issues(state.draft_id or 0)}
            fresh = [issue for issue in result.issues if issue.issue_id not in existing]
            if fresh:
                production.save_issues(state.draft_id or 0, fresh)
            return result.model_dump()

        out = run_node(
            ops,
            state.workflow_run_id,
            "n5_parallel_review",
            node_key,
            {"draft_id": state.draft_id, "role": role.value},
            persist,
            sub_key=role.value,
        )
        if out.get("absent"):
            absent.append(role.value)
        else:
            reports.append(ReviewReport.model_validate(out))
        if isinstance(result, BaseException) and role in CRITICAL_REVIEWERS:
            critical_error = result

    for role in roles:
        hit = ops.find_success_node(f"{state.draft_id}|n5|{role.value}")
        if hit is None or role in pending:
            continue
        if hit.output_snapshot.get("absent"):
            if role.value not in absent:
                absent.append(role.value)
        else:
            loaded = ReviewReport.model_validate(hit.output_snapshot)
            if all(item.reviewer_role != loaded.reviewer_role for item in reports):
                reports.append(loaded)

    if critical_error is not None:
        raise NodeFailed("n5_parallel_review", f"{type(critical_error).__name__}: {critical_error}")
    return {
        "reports": [item.model_dump() for item in reports],
        "absent": absent,
    }


async def _n6(
    ops: OpsRepo,
    production: ProductionRepo,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    budget: Callable[[], None],
    ctx_factory: Callable[..., ChapterContextPackage],
) -> dict:
    if state.draft_id is None:
        raise ChapterLoopError("N6 缺少 draft_id")
    primary_id = state.draft_id
    reports, absent = _load_review_round(ops, primary_id)
    issues = [issue for report in reports for issue in report.issues]
    review_hash = _review_set_hash(issues, absent)
    key = f"{primary_id}|{review_hash}|n6"

    async def fn() -> dict:
        ids = state.draft_ids or [primary_id]
        candidates = [draft_from_record(production.get_draft(item)) for item in ids]
        package = ctx_factory()
        try:
            raw = await run_judge(deps, candidates, reports, package, absent=absent)
        except StructuredOutputError:
            raise
        verdict = sanitize_verdict(raw, issues)
        n3 = ops.find_success_node(f"{chapter_key}|{state.outline_ver}|1|n3")
        mapping = (n3.output_snapshot.get("candidate_drafts") or {}) if n3 else {}
        picked = mapping.get(verdict.selected_candidate)
        selected_id = int(picked) if picked else state.draft_id
        if selected_id not in {int(item) for item in ids}:
            selected_id = state.draft_id
        chapter = PlanningRepo(ops.s).get_chapter(project_id, chapter_key)
        rec = production.save_verdict(
            selected_id,  # type: ignore[arg-type]
            chapter_key,
            verdict,
            chapter.revision_round + 1,
        )
        assert rec.id is not None
        return {
            "verdict_id": rec.id,
            "verdict": verdict.model_dump(),
            "draft_id": selected_id,
        }

    out = await run_node_async(
        ops,
        state.workflow_run_id,
        "n6_judge",
        key,
        {"draft_id": state.draft_id, "review_set_hash": review_hash},
        fn,
        max_retries=1,
        budget_check=budget,
    )
    if out.get("draft_id"):
        state.draft_id = int(out["draft_id"])
        state.draft_ids = [state.draft_id]
    return out


def _apply_verdict(
    planning: PlanningRepo,
    production: ProductionRepo,
    project_id: int,
    chapter_key: str,
    settings: Settings,
) -> None:
    verdict = production.latest_verdict(chapter_key)
    if verdict is None:
        raise ChapterLoopError("N6 完成后缺少裁决")
    kind = verdict.verdict
    if kind is VerdictType.PASS:
        transition(planning, project_id, chapter_key, ChapterStatus.HUMAN_REVIEW)
        return
    if kind is VerdictType.HUMAN_REVIEW:
        transition(planning, project_id, chapter_key, ChapterStatus.HUMAN_REVIEW)
        return
    if kind in {VerdictType.REPLAN_SCENE, VerdictType.REPLAN_CHAPTER}:
        transition(planning, project_id, chapter_key, ChapterStatus.NEEDS_REPLAN)
        return
    if kind is VerdictType.REVISE_LOCAL:
        chapter = planning.get_chapter(project_id, chapter_key)
        if chapter.revision_round >= settings.max_revision_rounds:
            transition(planning, project_id, chapter_key, ChapterStatus.HUMAN_REVIEW)
            return
        planning.increment_revision_round(project_id, chapter_key)
        transition(planning, project_id, chapter_key, ChapterStatus.NEEDS_REVISION)
        return
    assert_never(kind)


async def _n7(
    ops: OpsRepo,
    production: ProductionRepo,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    budget: Callable[[], None],
    ctx_factory: Callable[..., ChapterContextPackage],
) -> dict:
    record = production.latest_verdict_record(chapter_key)
    if record is None or record.id is None:
        raise ChapterLoopError("N7 缺少裁决")
    verdict = JudgeVerdict.model_validate(record.payload)
    key = f"{record.id}|n7"

    async def fn() -> dict:
        if state.draft_id is None:
            raise ChapterLoopError("N7 缺少 draft_id")
        original_rec = production.get_draft(state.draft_id)
        original = draft_from_record(original_rec)
        issues = production.list_issues(state.draft_id)
        accepted = [ruling.issue_id for ruling in verdict.rulings if ruling.accepted]
        if not accepted:
            accepted = [issue.issue_id for issue in issues if not issue.downweighted]
        if not accepted:
            raise ChapterLoopError("REVISE_LOCAL 没有可执行的 issue")
        order = RevisionOrder(
            verdict_ref=f"verdict_{record.id}",
            candidate_id=verdict.selected_candidate,
            issue_ids=accepted,
            scope=verdict.revision_scope,
            locked_strengths=verdict.locked_strengths,
            instructions=verdict.reasoning_summary,
        )
        package = ctx_factory(prior_feedback=verdict.reasoning_summary)
        revised = await run_reviser(deps, original, order, issues, package)
        rec = production.create_draft(
            project_id,
            chapter_key,
            revised.candidate_id,
            state.lineage_id,
            revised.full_text(),
            {
                "scenes": [scene.model_dump() for scene in revised.scenes],
                "chapter_summary": revised.chapter_summary,
                "deviation_notes": revised.deviation_notes,
                "revision_order": order.model_dump(),
            },
            load_prompt("reviser").prompt_version,
            state.outline_ver,
            revision_of=state.draft_id,
        )
        assert rec.id is not None
        state.draft_id = rec.id
        state.draft_ids = [rec.id]
        return {"draft_id": rec.id, "verdict_id": record.id}

    out = await run_node_async(
        ops,
        state.workflow_run_id,
        "n7_revise",
        key,
        {"verdict_id": record.id},
        fn,
        budget_check=budget,
    )
    state.draft_id = int(out["draft_id"])
    state.draft_ids = [state.draft_id]
    return out


def _n8(ops: OpsRepo, project_id: int, chapter_key: str, state: _LoopState) -> dict:
    key = f"{chapter_key}|{state.draft_id}|n8"

    def fn() -> dict:
        ops.save_approval(project_id, "chapter", chapter_key, "approved", note="chapter-loop N8")
        return {"decision": "approved"}

    return run_node(
        ops,
        state.workflow_run_id,
        "n8_human_gate",
        key,
        {"chapter_key": chapter_key, "draft_id": state.draft_id},
        fn,
    )


async def _n9(
    ops: OpsRepo,
    production: ProductionRepo,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
    state: _LoopState,
    budget: Callable[[], None],
    ctx_factory: Callable[..., ChapterContextPackage],
    git_root: Path | None,
) -> dict:
    if state.draft_id is None:
        raise ChapterLoopError("N9 缺少 draft_id")
    key = f"canon|{chapter_key}|{state.draft_id}"

    async def fn() -> dict:
        canon_repo = CanonRepo(ops.s)
        existing = canon_repo.get_by_idempotency_key(key)
        writer = CanonWriter(ops.s, project_id, git_root=git_root)
        if existing is not None and existing.provisional:
            delta = CanonDelta.model_validate(existing.payload)
            rec = writer.finalize(delta, key, chapter_key)
            return {"delta_id": rec.id, "idempotency_key": key}
        draft = draft_from_record(production.get_draft(state.draft_id))  # type: ignore[arg-type]
        package = ctx_factory()
        canon_ver = canon_repo.current_canon_version(project_id)
        delta = await run_canon_curator(deps, draft, package, canon_ver)
        rec = writer.finalize(delta, key, chapter_key)
        return {"delta_id": rec.id, "idempotency_key": key}

    return await run_node_async(
        ops,
        state.workflow_run_id,
        "n9_canon_commit",
        key,
        {"chapter_key": chapter_key, "draft_id": state.draft_id},
        fn,
        budget_check=budget,
    )


def _load_review_round(ops: OpsRepo, draft_id: int) -> tuple[list[ReviewReport], list[str]]:
    reports: list[ReviewReport] = []
    absent: list[str] = []
    for role in ReviewerRole:
        hit = ops.find_success_node(f"{draft_id}|n5|{role.value}")
        if hit is None:
            continue
        if hit.output_snapshot.get("absent"):
            absent.append(role.value)
        else:
            reports.append(ReviewReport.model_validate(hit.output_snapshot))
    return reports, absent


async def stage_chapter_overlay(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    chapter_key: str,
) -> None:
    """批次连跑:在 HUMAN_REVIEW 停下后注入 provisional canon(D15)。"""
    planning = PlanningRepo(session)
    production = ProductionRepo(session)
    canon = CanonRepo(session)
    builder = ContextBuilder(planning, canon, retrieval=memory_retrieval_for_session(session))
    draft_rec = production.latest_chapter_draft(project_id, chapter_key)
    if draft_rec is None or draft_rec.id is None:
        return
    key = f"canon|{chapter_key}|{draft_rec.id}"
    if canon.get_by_idempotency_key(key) is not None:
        return
    draft = draft_from_record(draft_rec)
    outline = planning.get_outline(project_id, chapter_key)
    chapter = planning.get_chapter(project_id, chapter_key)
    package = builder.build(
        project_id,
        chapter_key,
        task_brief=f"撰写{chapter.title or chapter_key}：{outline.core_event}",
        volume_summary=_volume_summary(planning, project_id, outline.volume_id),
        include_provisional=True,
    )
    canon_ver = canon.current_canon_version(project_id)
    delta = await run_canon_curator(deps, draft, package, canon_ver)
    CanonWriter(session, project_id).stage_provisional(delta, key)
