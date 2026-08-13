"""规划链 Concept Judge 门禁:R2 结构后、R4 冲突引擎后各一次。"""

from __future__ import annotations

import json

from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import (
    ConceptJudgeDecision,
    ConceptJudgeVerdict,
    StoryBrief,
    StoryKernel,
)
from novel_agent.lint.bible import lint_bible
from novel_agent.planning.chain import PlanningError, _kernel_text
from novel_agent.runtime.agents import (
    AgentDeps,
    run_concept_judge,
    run_conflict_planner,
    run_payoff_planner,
    run_structure_planner,
)


def _dump(obj: object) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), ensure_ascii=False)
    return json.dumps(obj, ensure_ascii=False)


def _chapter_keys(volume_id: str, chapters_needed: int) -> list[str]:
    return [f"{volume_id}c{i:03d}" for i in range(1, chapters_needed + 1)]


class ConceptJudgeStopped(PlanningError):
    """REJECT 或修一轮后仍未 PASS:已完成轮次保留,后续轮次不入库。"""

    def __init__(self, verdict: ConceptJudgeVerdict) -> None:
        summary = "; ".join(verdict.reasons)
        super().__init__(
            f"Concept Judge {verdict.verdict.value} after {verdict.after_round}: {summary}"
        )
        self.verdict = verdict


def _blocked_by_verdict(verdict: ConceptJudgeVerdict | None) -> bool:
    return verdict is not None and verdict.verdict is not ConceptJudgeDecision.PASS


def judge_blocks_round(bible: BibleRepo, project_id: int, round_index: int) -> bool:
    if round_index == 3:
        return _blocked_by_verdict(bible.get_concept_judge(project_id, "R2"))
    if round_index == 5:
        return _blocked_by_verdict(bible.get_concept_judge(project_id, "R4"))
    return False


async def ensure_concept_judge(
    bible: BibleRepo,
    planning: PlanningRepo,
    deps: AgentDeps,
    project_id: int,
    after_round: str,
    *,
    skip: bool = False,
    volume_id: str = "v1",
    chapters_needed: int = 5,
) -> ConceptJudgeVerdict | None:
    if skip:
        return None
    existing = bible.get_concept_judge(project_id, after_round)
    if existing is not None:
        if existing.verdict is ConceptJudgeDecision.PASS:
            return existing
        raise ConceptJudgeStopped(existing)

    kernel = planning.get_approved_kernel(project_id)
    if kernel is None:
        raise PlanningError("Concept Judge 需要已确认内核")
    structure = bible.get_structure_map(project_id)
    if structure is None:
        raise PlanningError("Concept Judge 需要已确认结构图")
    brief = bible.get_brief(project_id)

    conflicts = bible.list_conflicts(project_id) if after_round == "R4" else None
    payoffs = bible.list_payoff_beats(project_id) if after_round == "R4" else None
    verdict = await run_concept_judge(
        deps,
        kernel=kernel,
        structure=structure,
        after_round=after_round,
        conflicts=conflicts,
        payoffs=payoffs,
    )
    if verdict.verdict is ConceptJudgeDecision.PASS:
        bible.save_concept_judge(project_id, verdict)
        bible.s.commit()
        return verdict
    if verdict.verdict is ConceptJudgeDecision.REJECT:
        bible.save_concept_judge(project_id, verdict)
        bible.s.commit()
        raise ConceptJudgeStopped(verdict)

    repaired = await _repair_once(
        bible,
        planning,
        deps,
        project_id,
        after_round,
        kernel,
        brief,
        verdict.repair_notes,
        volume_id=volume_id,
        chapters_needed=chapters_needed,
    )
    structure = bible.get_structure_map(project_id)
    if structure is None:
        raise PlanningError("修订后缺少结构图")
    conflicts = bible.list_conflicts(project_id) if after_round == "R4" else None
    payoffs = bible.list_payoff_beats(project_id) if after_round == "R4" else None
    second = await run_concept_judge(
        deps,
        kernel=kernel,
        structure=structure,
        after_round=after_round,
        conflicts=conflicts,
        payoffs=payoffs,
    )
    final = second.model_copy(
        update={
            "repair_attempted": True,
            "repair_notes": verdict.repair_notes or second.repair_notes,
            "after_round": after_round,
        }
    )
    if not repaired:
        final = final.model_copy(
            update={
                "verdict": ConceptJudgeDecision.REJECT,
                "reasons": [*final.reasons, "修订产物未通过 lint,停止后续轮次"],
            }
        )
    bible.save_concept_judge(project_id, final)
    bible.s.commit()
    if final.verdict is not ConceptJudgeDecision.PASS:
        raise ConceptJudgeStopped(final)
    return final


async def _repair_once(
    bible: BibleRepo,
    planning: PlanningRepo,
    deps: AgentDeps,
    project_id: int,
    after_round: str,
    kernel: StoryKernel,
    brief: StoryBrief | None,
    repair_notes: str,
    *,
    volume_id: str,
    chapters_needed: int,
) -> bool:
    brief_text = _dump(brief) if brief is not None else ""
    if after_round == "R2":
        smap = await run_structure_planner(
            deps, _kernel_text(kernel), brief_text, repair_notes=repair_notes
        )
        report = lint_bible(structure=smap)
        if not report.passed:
            return False
        bible.save_structure_map(project_id, smap)
        bible.s.commit()
        return True

    characters = planning.list_characters(project_id)
    keys = _chapter_keys(volume_id, chapters_needed)
    characters_text = json.dumps(
        [card.model_dump() for card in characters], ensure_ascii=False
    )
    conflicts = await run_conflict_planner(
        deps,
        _kernel_text(kernel),
        characters_text,
        keys,
        repair_notes=repair_notes,
    )
    beats = await run_payoff_planner(
        deps,
        _kernel_text(kernel),
        _dump([item.model_dump() for item in conflicts]),
        keys,
        repair_notes=repair_notes,
    )
    report = lint_bible(conflicts=conflicts, payoff_beats=beats, rolling_keys=keys)
    if not report.passed:
        return False
    bible.replace_conflicts(project_id, conflicts)
    bible.replace_payoff_beats(project_id, beats)
    bible.s.commit()
    return True
