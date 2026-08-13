"""Bounded, auditable M2.6 real-model smoke run.

This module deliberately contains no automatic entrypoint. The CLI supplies the
explicit confirmation and positive USD budget before calling it.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, select

from novel_agent.config import Settings, SlotConfig
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.models import ModelRunRecord
from novel_agent.domain.schemas import (
    ChapterContextPackage,
    ReviewerRole,
    ReviewIssue,
    RevisionOrder,
)
from novel_agent.gateway.base import (
    ModelGateway,
    ModelRequest,
    ModelResponse,
    Provider,
    ResponsePolicyError,
    estimate_cost,
    slot_pricing,
)
from novel_agent.gateway.providers.real import (
    REAL_REQUEST_TIMEOUT_S,
    AnthropicProvider,
    OpenAICompatProvider,
)
from novel_agent.runtime.adapter import GatewayRuntimeAdapter
from novel_agent.runtime.agents import (
    EVIDENCE_REPAIR_MAX_TOKENS,
    AgentDeps,
    _evidence_locates,
    run_canon_curator,
    run_character_planner,
    run_judge,
    run_kernel_planner,
    run_outline_planner,
    run_reviewer,
    run_reviser,
    run_writer,
)
from novel_agent.runtime.prompts import load_prompt

PROMPT_ROLES = (
    "kernel_planner",
    "character_planner",
    "outline_planner",
    "writer",
    "red_team",
    "plot",
    "character",
    "continuity",
    "prose",
    "judge",
    "reviser",
    "canon_curator",
)
MAX_OUTPUT_TOKENS = {
    "kernel_planner": 8_000,
    "character_planner": 10_000,
    "outline_planner": 16_000,
    "writer": 16_000,
    "red_team": 8_000,
    "plot": 8_000,
    "character": 8_000,
    "continuity": 8_000,
    "prose": 8_000,
    "judge": 6_000,
    "reviser": 16_000,
    "canon_curator": 6_000,
}
# A UTF-8 byte count is a conservative token upper bound for supported APIs.
# The fixed allowance covers message framing and provider-side chat wrappers.
MAX_INPUT_TOKENS_PER_CALL = 64_000
MESSAGE_OVERHEAD_TOKENS = 1_024
ROLE_CALL_LIMIT = 2
REVIEWER_ROLE_CALL_LIMIT = 4
REVIEWER_PROMPT_ROLES = frozenset({"red_team", "plot", "character", "continuity", "prose"})


def _role_call_limit(prompt_role: str) -> int:
    return REVIEWER_ROLE_CALL_LIMIT if prompt_role in REVIEWER_PROMPT_ROLES else ROLE_CALL_LIMIT


def _role_preflight_output_bounds(prompt_role: str) -> tuple[int, ...]:
    if prompt_role in REVIEWER_PROMPT_ROLES:
        return (
            MAX_OUTPUT_TOKENS[prompt_role],
            MAX_OUTPUT_TOKENS[prompt_role],
            EVIDENCE_REPAIR_MAX_TOKENS,
            EVIDENCE_REPAIR_MAX_TOKENS,
        )
    return (MAX_OUTPUT_TOKENS[prompt_role],) * ROLE_CALL_LIMIT


class SmokeGateError(RuntimeError):
    """A pre-provider safety gate rejected the smoke run."""


class SmokeExecutionError(RuntimeError):
    """A smoke role failed after the durable redacted report was written."""

    def __init__(self, report_path: Path, error_kind: str) -> None:
        super().__init__(f"M2.6 smoke failed ({error_kind}); redacted report: {report_path}")
        self.report_path = report_path
        self.error_kind = error_kind


def _role_slot(role: str) -> str:
    return load_prompt(role).slot


def _price(slot: SlotConfig) -> tuple[float, float]:
    pricing = slot_pricing(slot)
    if pricing is None:
        raise SmokeGateError(
            f"model pricing unknown for {slot.model!r}; configure both explicit price overrides"
        )
    return pricing


def validate_m26_settings(settings: Settings, budget_usd: float) -> float:
    """Reject unsafe configuration and return the whole-run worst-case cost."""
    if budget_usd <= 0:
        raise SmokeGateError("--budget-usd must be positive")
    for name in ("creative", "review", "judge", "extract"):
        slot = getattr(settings, name)
        if slot.provider == "mock":
            raise SmokeGateError(f"slot {name} is mock; all four slots must be real")
        _price(slot)
    if settings.creative.family == settings.judge.family:
        raise SmokeGateError("judge.family must differ from creative.family")

    worst_case = 0.0
    for role in PROMPT_ROLES:
        slot = getattr(settings, _role_slot(role))
        for output_tokens in _role_preflight_output_bounds(role):
            worst_case += estimate_cost(
                slot.model,
                MAX_INPUT_TOKENS_PER_CALL,
                output_tokens,
                pricing=_price(slot),
            )
    worst_case = round(worst_case, 6)
    if worst_case > budget_usd:
        raise SmokeGateError(
            f"budget ${budget_usd:.6f} is below conservative preflight ${worst_case:.6f}"
        )
    return worst_case


@dataclass
class _BudgetLedger:
    budget_usd: float
    run_id: str
    session: Session
    calls: dict[str, int] = field(default_factory=dict)
    spent_usd: float = 0.0

    def before(self, slot: SlotConfig, req: ModelRequest, agent_role: str) -> str:
        prompt_role = "writer" if agent_role == "writer_a" else agent_role
        if prompt_role not in PROMPT_ROLES:
            raise SmokeGateError(f"unexpected smoke role: {agent_role}")
        limit = _role_call_limit(prompt_role)
        if self.calls.get(prompt_role, 0) >= limit:
            raise SmokeGateError(
                f"role {prompt_role} exceeded {limit} provider calls"
            )
        input_bound = len((req.system + req.user).encode("utf-8")) + MESSAGE_OVERHEAD_TOKENS
        if input_bound > MAX_INPUT_TOKENS_PER_CALL:
            raise SmokeGateError(f"role {prompt_role} input exceeds conservative bound")
        prior_runs = self.session.exec(select(ModelRunRecord)).all()
        self.spent_usd = round(
            sum(
                run.cost_estimate
                for run in prior_runs
                if run.input_ref.startswith(f"m26:{self.run_id}:")
            ),
            6,
        )
        projected = self.spent_usd + estimate_cost(
            slot.model, input_bound, req.max_tokens, pricing=_price(slot)
        )
        if projected > self.budget_usd:
            raise SmokeGateError(f"role {prompt_role} could exceed remaining hard budget")
        self.calls[prompt_role] = self.calls.get(prompt_role, 0) + 1
        return prompt_role

    def after(self, slot: SlotConfig, req: ModelRequest, response: ModelResponse) -> None:
        input_bound = len((req.system + req.user).encode("utf-8")) + MESSAGE_OVERHEAD_TOKENS
        if response.input_tokens <= 0 or response.output_tokens <= 0:
            raise SmokeGateError("provider did not return positive token usage")
        if response.input_tokens > input_bound or response.output_tokens > req.max_tokens:
            raise SmokeGateError("provider usage exceeded the pre-authorized token bound")
        self.spent_usd = round(
            self.spent_usd
            + estimate_cost(
                slot.model,
                response.input_tokens,
                response.output_tokens,
                pricing=_price(slot),
            ),
            6,
        )


@dataclass
class _GuardedProvider:
    provider: Provider
    ledger: _BudgetLedger

    async def complete(
        self, slot: SlotConfig, req: ModelRequest, agent_role: str
    ) -> ModelResponse:
        self.ledger.before(slot, req, agent_role)
        response = await self.provider.complete(slot, req, agent_role)
        try:
            self.ledger.after(slot, req, response)
        except SmokeGateError as exc:
            raise ResponsePolicyError(response, str(exc)) from exc
        return response


def _real_providers() -> dict[str, Provider]:
    return {
        "openai_compat": OpenAICompatProvider(),
        "anthropic": AnthropicProvider(),
    }


def _report_path(path: Path | None, run_id: str) -> Path:
    return path or Path("artifacts/verification") / f"m26-smoke-{run_id}.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _redacted_failure_detail(exc: Exception) -> dict[str, Any]:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValidationError):
            paths = []
            issues = []
            for error in current.errors():
                segments = [
                    str(item)
                    if isinstance(item, int)
                    or (
                        isinstance(item, str)
                        and item.isascii()
                        and item.isidentifier()
                        and len(item) <= 64
                    )
                    else "<redacted>"
                    for item in error["loc"]
                ]
                path = ".".join(segments)
                paths.append(path)
                error_type = error["type"]
                issues.append(
                    {
                        "field_path": path,
                        "error_type": error_type
                        if error_type.isascii()
                        and error_type.isidentifier()
                        and len(error_type) <= 64
                        else "<redacted>",
                    }
                )
            return {
                "category": "pydantic_validation",
                "field_paths": sorted(set(paths))[:20],
                "issues": sorted(
                    issues, key=lambda item: (item["field_path"], item["error_type"])
                )[:20],
            }
        if isinstance(current, json.JSONDecodeError):
            document_chars = len(current.doc)
            return {
                "category": "json_decode",
                "field_paths": [],
                "reason": current.msg
                if current.msg.isascii() and len(current.msg) <= 80
                else "<redacted>",
                "line": current.lineno,
                "column": current.colno,
                "error_offset": current.pos,
                "document_chars": document_chars,
                "at_end": current.pos >= max(document_chars - 1, 0),
            }
        current = current.__cause__ or current.__context__
    return {"category": "runtime_error", "field_paths": []}


def _run_entry(run: ModelRunRecord, settings: Settings, valid: bool | None) -> dict[str, Any]:
    prompt_role = "writer" if run.agent_role == "writer_a" else run.agent_role
    slot_name = _role_slot(prompt_role)
    slot = getattr(settings, slot_name)
    return {
        "prompt_role": prompt_role,
        "agent_role": run.agent_role,
        "slot": slot_name,
        "provider": run.provider,
        "model": run.model,
        "family": slot.family,
        "prompt_version": run.prompt_version,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "latency_ms": run.latency_ms,
        "cost_usd": run.cost_estimate,
        "status": run.status,
        "structured_output_valid": valid,
        "input_ref": run.input_ref,
        "output_ref": run.output_ref,
    }


def _run_entries(
    runs: list[ModelRunRecord], settings: Settings, valid: dict[str, bool]
) -> list[dict[str, Any]]:
    last_run_ids: dict[str, int | None] = {}
    for run in runs:
        role = "writer" if run.agent_role == "writer_a" else run.agent_role
        last_run_ids[role] = run.id

    entries = []
    for run in runs:
        role = "writer" if run.agent_role == "writer_a" else run.agent_role
        is_valid = valid.get(role)
        if is_valid and run.id != last_run_ids[role]:
            is_valid = False
        entries.append(_run_entry(run, settings, is_valid))
    return entries


def _synthetic_issue(draft_text: str, scene_id: str) -> ReviewIssue:
    quote = draft_text[: min(12, len(draft_text))]
    return ReviewIssue.model_validate(
        {
            "issue_id": "m26_revision_probe",
            "reviewer_role": "prose",
            "claim": "执行一次受限最小修订协议验证",
            "evidence": [{"scene_id": scene_id, "quote": quote}],
            "violated_rule": "M2.6 smoke protocol",
            "severity": "P2",
            "failure_consequence": "无法验证 reviser 结构化输出",
            "recommended_rollback_level": "prose",
            "confidence": 1.0,
        }
    )


async def run_m26_smoke(
    settings: Settings,
    *,
    budget_usd: float,
    report_path: Path | None = None,
    providers: Mapping[str, Provider] | None = None,
) -> Path:
    """Run all M2.6 prompt roles within bounded repair limits.

    ``providers`` exists solely as an offline test seam. The CLI never supplies it.
    """
    worst_case = validate_m26_settings(settings, budget_usd)
    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ")
    destination = _report_path(report_path, run_id)
    base_providers = dict(providers) if providers is not None else _real_providers()
    engine = build_engine(settings.db_path)
    create_all(engine)
    valid: dict[str, bool] = {}
    evidence: dict[str, dict[str, int]] = {}
    failure_kind: str | None = None
    failure_detail: dict[str, Any] | None = None
    evidence_failed = False

    with Session(engine) as session:
        ledger = _BudgetLedger(budget_usd, run_id, session)
        guarded: dict[str, Provider] = {
            name: _GuardedProvider(provider, ledger)
            for name, provider in base_providers.items()
        }
        gateway = ModelGateway(
            settings,
            session,
            guarded,
            max_retries=1,
            timeout_s=REAL_REQUEST_TIMEOUT_S,
        )
        deps = AgentDeps(
            gateway=gateway,
            runtime=GatewayRuntimeAdapter(gateway, repair_attempts=1),
            verification_run_id=run_id,
        )
        try:
            kernels = await run_kernel_planner(deps, "写一段中文架空悬疑小说验证样例")
            valid["kernel_planner"] = True
            kernel = kernels.candidates[0]
            characters = await run_character_planner(
                deps, kernel.model_dump_json(), "中文架空悬疑小说验证样例"
            )
            valid["character_planner"] = True
            unit, outlines, scene_map = await run_outline_planner(
                deps,
                kernel.model_dump_json(),
                json.dumps([item.model_dump() for item in characters], ensure_ascii=False),
                "v1",
                None,
                1,
            )
            valid["outline_planner"] = True
            outline = outlines[0]
            scenes = scene_map[outline.chapter_key]
            ctx = ChapterContextPackage(
                chapter_key=outline.chapter_key,
                canon_version="canon_v0",
                task_brief="写一个简短中文验证章节",
                outline=outline,
                scene_cards=scenes,
                kernel_summary=kernel.logline,
                volume_summary="第一卷验证样例",
                unit_card=unit,
                characters=characters,
            )
            draft = await run_writer(deps, ctx, writer_id="writer_a")
            valid["writer"] = True
            reports = []
            for role in (
                ReviewerRole.RED_TEAM,
                ReviewerRole.PLOT,
                ReviewerRole.CHARACTER,
                ReviewerRole.CONTINUITY,
                ReviewerRole.PROSE,
            ):
                review = await run_reviewer(deps, role, draft, ctx)
                locations = [_evidence_locates(issue, draft) for issue in review.issues]
                while (
                    locations
                    and not all(locations)
                    and ledger.calls.get(role.value, 0) < _role_call_limit(role.value)
                ):
                    review = await run_reviewer(
                        deps, role, draft, ctx, evidence_repair=True
                    )
                    locations = [_evidence_locates(issue, draft) for issue in review.issues]
                reports.append(review)
                valid[role.value] = True
                located = sum(locations)
                evidence[role.value] = {
                    "issues": len(review.issues),
                    "located": located,
                    "unlocated": len(review.issues) - located,
                }
                if not all(locations):
                    evidence_failed = True
            await run_judge(deps, [draft], reports, ctx, absent=[])
            valid["judge"] = True
            all_issues = [issue for report in reports for issue in report.issues]
            issue = all_issues[0] if all_issues else _synthetic_issue(
                draft.scenes[0].content, draft.scenes[0].scene_id
            )
            order = RevisionOrder(
                verdict_ref=f"m26:{run_id}:judge:output:v1",
                candidate_id=draft.candidate_id,
                issue_ids=[issue.issue_id],
                scope=[draft.scenes[0].scene_id],
                instructions="仅做最小必要调整；若无需调整则保持正文不变",
            )
            revised = await run_reviser(deps, draft, order, [issue], ctx)
            valid["reviser"] = True
            await run_canon_curator(deps, revised, ctx, "canon_v0")
            valid["canon_curator"] = True
        except Exception as exc:  # noqa: BLE001 - report boundary intentionally redacts details
            failure_kind = type(exc).__name__
            failure_detail = _redacted_failure_detail(exc)
        if failure_kind is None and evidence_failed:
            failure_kind = "SmokeGateError"
            failure_detail = {"category": "evidence_localization", "field_paths": []}

        runs = [
            run
            for run in session.exec(select(ModelRunRecord)).all()
            if run.input_ref.startswith(f"m26:{run_id}:")
        ]
        report = {
            "schema_version": "1.0",
            "verification": "M2.6-real-model-smoke",
            "run_id": run_id,
            "created_at": now.isoformat(),
            "status": "passed" if failure_kind is None else "failed",
            "failure_kind": failure_kind,
            "failure_detail": failure_detail,
            "budget": {
                "hard_limit_usd": budget_usd,
                "preflight_worst_case_usd": worst_case,
                "actual_cost_usd": round(sum(run.cost_estimate for run in runs), 6),
            },
            "role_call_limit": ROLE_CALL_LIMIT,
            "role_call_limits": {
                role: _role_call_limit(role) for role in PROMPT_ROLES
            },
            "calls": _run_entries(runs, settings, valid),
            "missing_roles": [role for role in PROMPT_ROLES if role not in valid],
            "chinese_evidence_location": evidence,
            "draft_fingerprint": {
                "sha256": _sha256(draft.full_text()) if "draft" in locals() else None,
                "utf8_bytes": len(draft.full_text().encode("utf-8")) if "draft" in locals() else 0,
            },
            "database": {"path": str(settings.db_path), "model_run_count": len(runs)},
        }
        _write_report(destination, report)

    if failure_kind is not None:
        raise SmokeExecutionError(destination, failure_kind)
    return destination
