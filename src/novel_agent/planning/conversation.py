"""Story Bible 对话编排:R0→R5 单轮生成 + 人工确认,记忆为已确认产物。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from novel_agent.domain.models import ProjectRecord
from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import CharacterCard, StoryBrief, StoryKernel
from novel_agent.lint import LintReport
from novel_agent.lint.bible import lint_bible
from novel_agent.planning.chain import (
    PlanningAborted,
    PlanningError,
    PlanningGates,
    _ensure_kernel,
    _kernel_text,
)
from novel_agent.runtime.agents import (
    AgentDeps,
    run_conflict_planner,
    run_outline_planner,
    run_payoff_planner,
    run_people_planner,
    run_structure_planner,
)


@dataclass
class BibleResult:
    project_id: int
    kernel_version: int
    character_ids: list[str]
    volume_id: str
    unit_id: str
    chapter_keys: list[str]
    skipped: list[str] = field(default_factory=list)


def planned_chapter_keys(volume_id: str, chapters_needed: int) -> list[str]:
    return [f"{volume_id}c{i:03d}" for i in range(1, chapters_needed + 1)]


def brief_from_spark(spark: str, boundaries: list[str]) -> StoryBrief:
    return StoryBrief(
        spark=spark.strip(),
        genre="",
        audience="",
        do_not_write=list(boundaries),
    )


def _dump(obj: object) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), ensure_ascii=False)
    return json.dumps(obj, ensure_ascii=False)


def _lint_error(report: LintReport) -> PlanningError:
    messages = "; ".join(f.message for f in report.findings)
    return PlanningError(f"Story Bible lint 未通过: {messages}")


async def run_bible_conversation(
    planning: PlanningRepo,
    bible: BibleRepo,
    canon: CanonRepo,
    deps: AgentDeps,
    spark: str,
    gates: PlanningGates,
    *,
    volume_id: str = "v1",
    chapters_needed: int = 5,
) -> BibleResult:
    """R0 简报 → R1 内核 → R2 结构 → R3 人物关系 → R4 冲突爽点 → R5 滚动章纲。

    已完成轮次跳过。每轮确认后立即 commit。R5 lint 失败不入库章纲。
    """
    project_id = deps.project_id
    if project_id is None:
        raise PlanningError("Story Bible 对话需要 project_id")
    if chapters_needed < 1:
        raise PlanningError("滚动章纲数量必须 >= 1")

    skipped: list[str] = []
    done = bible.round_complete(project_id)
    project = planning.get_project(project_id)
    brief = await _ensure_r0(
        planning, bible, project_id, project, spark, gates, done, skipped
    )
    kernel, kernel_version = await _ensure_kernel(
        planning, deps, _dump(brief), gates, project_id, skipped
    )
    if "kernel" in skipped:
        skipped[skipped.index("kernel")] = "R1"
    await _ensure_r2(bible, deps, project_id, kernel, brief, gates, skipped)
    characters = await _ensure_r3(
        planning, bible, canon, deps, project_id, kernel, brief, gates, skipped
    )
    keys = planned_chapter_keys(volume_id, chapters_needed)
    await _ensure_r4(
        bible, deps, project_id, kernel, characters, keys, gates, skipped
    )
    unit_id, chapter_keys = await _ensure_r5(
        planning,
        bible,
        deps,
        project_id,
        kernel,
        characters,
        brief,
        volume_id,
        chapters_needed,
        gates,
        skipped,
    )
    return BibleResult(
        project_id=project_id,
        kernel_version=kernel_version,
        character_ids=[card.character_id for card in characters],
        volume_id=volume_id,
        unit_id=unit_id,
        chapter_keys=chapter_keys,
        skipped=skipped,
    )


async def _ensure_r0(
    planning: PlanningRepo,
    bible: BibleRepo,
    project_id: int,
    project: ProjectRecord,
    spark: str,
    gates: PlanningGates,
    done: set[str],
    skipped: list[str],
) -> StoryBrief:
    existing = bible.get_brief(project_id)
    if "R0" in done and existing is not None:
        skipped.append("R0")
        return existing

    text = spark.strip() or (project.spark or "").strip()
    if not text and existing is not None:
        text = existing.spark
    if not text:
        raise PlanningError("火花不能为空")
    boundaries = list(project.boundaries or [])
    brief = brief_from_spark(text, boundaries)
    if not gates.confirm("确认创作简报(题材/受众可空,禁写项继承项目边界)?"):
        raise PlanningAborted("R0", project_id)
    bible.save_brief(project_id, brief)
    planning.s.commit()
    return brief


async def _ensure_r2(
    bible: BibleRepo,
    deps: AgentDeps,
    project_id: int,
    kernel: StoryKernel,
    brief: StoryBrief,
    gates: PlanningGates,
    skipped: list[str],
) -> None:
    if bible.get_structure_map(project_id) is not None:
        skipped.append("R2")
        return
    smap = await run_structure_planner(deps, _kernel_text(kernel), _dump(brief))
    report = lint_bible(structure=smap)
    if not report.passed:
        raise _lint_error(report)
    if not gates.confirm("确认写入三幕图与黄金三章?"):
        raise PlanningAborted("R2", project_id)
    bible.save_structure_map(project_id, smap)
    bible.s.commit()


async def _ensure_r3(
    planning: PlanningRepo,
    bible: BibleRepo,
    canon: CanonRepo,
    deps: AgentDeps,
    project_id: int,
    kernel: StoryKernel,
    brief: StoryBrief,
    gates: PlanningGates,
    skipped: list[str],
) -> list[CharacterCard]:
    existing = planning.list_characters(project_id)
    if existing:
        skipped.append("R3")
        return existing
    people = await run_people_planner(deps, _kernel_text(kernel), _dump(brief))
    if not people.characters:
        raise PlanningError("角色规划未返回任何角色卡")
    rel_report = lint_bible(relationship_proposals=people.relationship_proposals)
    if not rel_report.passed:
        raise _lint_error(rel_report)
    names = ", ".join(f"{card.name}({card.character_id})" for card in people.characters)
    if not gates.confirm(f"确认写入以上角色卡与初始关系? {names}"):
        raise PlanningAborted("R3", project_id)
    for card in people.characters:
        planning.upsert_character(project_id, card)
    for proposal in people.relationship_proposals:
        canon.upsert_relationship(
            project_id,
            proposal.parties[0],
            proposal.parties[1],
            proposal.state,
            evidence=proposal.evidence,
            source_chapter="planning",
            provisional=True,
        )
    planning.s.commit()
    return people.characters


async def _ensure_r4(
    bible: BibleRepo,
    deps: AgentDeps,
    project_id: int,
    kernel: StoryKernel,
    characters: list[CharacterCard],
    keys: list[str],
    gates: PlanningGates,
    skipped: list[str],
) -> None:
    if bible.list_conflicts(project_id) and bible.list_payoff_beats(project_id):
        skipped.append("R4")
        return
    characters_text = json.dumps(
        [card.model_dump() for card in characters], ensure_ascii=False
    )
    conflicts = await run_conflict_planner(
        deps, _kernel_text(kernel), characters_text, keys
    )
    beats = await run_payoff_planner(
        deps, _kernel_text(kernel), _dump([c.model_dump() for c in conflicts]), keys
    )
    report = lint_bible(conflicts=conflicts, payoff_beats=beats, rolling_keys=keys)
    if not report.passed:
        raise _lint_error(report)
    if not gates.confirm(f"确认写入冲突系统与爽点(计划章节 {', '.join(keys)})?"):
        raise PlanningAborted("R4", project_id)
    bible.replace_conflicts(project_id, conflicts)
    bible.replace_payoff_beats(project_id, beats)
    bible.s.commit()


async def _ensure_r5(
    planning: PlanningRepo,
    bible: BibleRepo,
    deps: AgentDeps,
    project_id: int,
    kernel: StoryKernel,
    characters: list[CharacterCard],
    brief: StoryBrief,
    volume_id: str,
    chapters_needed: int,
    gates: PlanningGates,
    skipped: list[str],
) -> tuple[str, list[str]]:
    existing = planning.list_chapters(project_id)
    if existing:
        skipped.append("R5")
        return existing[0].unit_id, [chapter.chapter_key for chapter in existing]

    characters_text = json.dumps(
        [card.model_dump() for card in characters], ensure_ascii=False
    )
    unit, outlines, by_chapter = await run_outline_planner(
        deps,
        _kernel_text(kernel),
        f"{_dump(brief)}\n{characters_text}",
        volume_id,
        None,
        chapters_needed,
    )
    if len(outlines) < chapters_needed:
        raise PlanningError(f"章纲数量不足: 需要 {chapters_needed}, 得到 {len(outlines)}")
    missing_scenes = [
        outline.chapter_key
        for outline in outlines
        if not by_chapter.get(outline.chapter_key)
    ]
    if missing_scenes:
        raise PlanningError(f"以下章节缺少场景卡: {missing_scenes}")

    keys = [outline.chapter_key for outline in outlines]
    citations = [
        (outline.chapter_key, outline.cited_conflict_ids, outline.cited_beat_ids)
        for outline in outlines
    ]
    report = lint_bible(
        structure=bible.get_structure_map(project_id),
        conflicts=bible.list_conflicts(project_id),
        payoff_beats=bible.list_payoff_beats(project_id),
        rolling_keys=keys,
        outline_citations=citations,
    )
    if not report.passed:
        raise _lint_error(report)

    prompt = (
        f"确认写入卷纲 {volume_id}、剧情单元 {unit.unit_id} "
        f"与滚动章纲/场景卡 {', '.join(keys)}?"
    )
    if not gates.confirm(prompt):
        raise PlanningAborted("R5", project_id)

    volume = planning.save_volume(
        project_id,
        volume_id,
        {
            "goal": unit.promise_or_debt,
            "position": unit.position_in_volume,
            "trigger": unit.trigger,
            "climax": unit.climax,
            "payoff": unit.payoff,
            "canon_constraints": unit.canon_constraints,
            "unit_ids": [unit.unit_id],
            "chapter_keys": keys,
            "brief": brief.spark,
        },
        title=unit.position_in_volume,
    )
    volume.status = "confirmed"
    unit_rec = planning.save_unit(project_id, volume_id, unit)
    unit_rec.status = "confirmed"
    for order, outline in enumerate(outlines, start=1):
        aligned = outline.model_copy(
            update={"volume_id": volume_id, "unit_id": unit.unit_id}
        )
        planning.create_chapter(project_id, aligned, order_index=order)
        planning.save_scene_cards(
            project_id, aligned.chapter_key, by_chapter[outline.chapter_key]
        )
    planning.s.commit()
    return unit.unit_id, keys
