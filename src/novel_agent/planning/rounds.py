"""写作台按轮生成/确认 Story Bible。CLI 的 run_bible_conversation 保持不变。"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import (
    ChapterOutline,
    CharacterCard,
    Conflict,
    PayoffBeat,
    PlotUnitCard,
    SceneCard,
    StoryBrief,
    StoryKernel,
    StructureMap,
)
from novel_agent.lint.bible import lint_bible, live_names_from_kernel
from novel_agent.planning.adversary import (
    ConceptJudgeStopped,
    ensure_concept_judge,
    judge_blocks_round,
)
from novel_agent.planning.chain import PlanningError, _kernel_text
from novel_agent.planning.conversation import (
    _dump,
    _lint_error,
    brief_from_spark,
    planned_chapter_keys,
)
from novel_agent.planning.settings import desk_settings
from novel_agent.runtime.agents import (
    AgentDeps,
    run_conflict_planner,
    run_kernel_planner,
    run_outline_planner,
    run_payoff_planner,
    run_people_planner,
    run_structure_planner,
)

ROUND_KINDS = ("R0", "R1", "R2", "R3", "R4", "R5")
ROUND_PROMPTS = {
    0: "确认创作简报(题材/受众可空,禁写项继承项目边界)?",
    1: "选定内核候选并写入?",
    2: "确认写入三幕图与黄金三章?",
    3: "确认写入角色卡与初始关系?",
    4: "确认写入冲突系统与爽点?",
    5: "确认写入卷纲、剧情单元与滚动章纲?",
}


def next_round_index(done: set[str]) -> int | None:
    for index, kind in enumerate(ROUND_KINDS):
        if kind not in done:
            return index
    return None


def _repos(session: Session) -> tuple[PlanningRepo, BibleRepo, CanonRepo]:
    return PlanningRepo(session), BibleRepo(session), CanonRepo(session)


def bible_snapshot(session: Session, project_id: int) -> dict[str, Any]:
    planning, bible, _canon = _repos(session)
    project = planning.get_project(project_id)
    done = sorted(bible.round_complete(project_id), key=lambda kind: ROUND_KINDS.index(kind))
    kernel = planning.get_approved_kernel(project_id)
    outlines = [
        planning.get_outline(project_id, chapter.chapter_key)
        for chapter in planning.list_chapters(project_id)
        if chapter.outline
    ]
    brief = bible.get_brief(project_id)
    structure = bible.get_structure_map(project_id)
    pending = bible.get_pending_round(project_id)
    return {
        "project_id": project_id,
        "title": project.title,
        "completed": done,
        "pending": pending,
        "brief": brief.model_dump(mode="json") if brief else None,
        "kernel": kernel.model_dump(mode="json") if kernel else None,
        "structure": structure.model_dump(mode="json") if structure else None,
        "characters": [
            card.model_dump(mode="json") for card in planning.list_characters(project_id)
        ],
        "conflicts": [item.model_dump(mode="json") for item in bible.list_conflicts(project_id)],
        "payoffs": [item.model_dump(mode="json") for item in bible.list_payoff_beats(project_id)],
        "outlines": [item.model_dump(mode="json") for item in outlines],
        "concept_judge": bible.concept_judge_state(project_id),
        "settings": desk_settings(project),
    }


async def generate_pending_round(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    spark: str,
    *,
    volume_id: str = "v1",
    chapters_needed: int = 5,
    round_index: int | None = None,
    skip_concept_judge: bool = False,
) -> dict[str, Any]:
    _planning, bible, _canon = _repos(session)
    done = bible.round_complete(project_id)
    expected = next_round_index(done)
    if expected is None:
        bible.set_pending_round(project_id, None)
        session.commit()
        return bible_snapshot(session, project_id)
    if not skip_concept_judge and judge_blocks_round(bible, project_id, expected):
        bible.set_pending_round(project_id, None)
        session.commit()
        return bible_snapshot(session, project_id)
    if round_index is not None and round_index != expected:
        raise PlanningError(f"当前应生成 R{expected}, 不是 R{round_index}")
    existing = bible.get_pending_round(project_id)
    if existing and int(existing.get("round", -1)) == expected:
        return bible_snapshot(session, project_id)
    artifact = await _generate_artifact(
        session, deps, project_id, spark, expected, volume_id, chapters_needed
    )
    bible.set_pending_round(
        project_id,
        {
            "round": expected,
            "kind": ROUND_KINDS[expected],
            "prompt": ROUND_PROMPTS[expected],
            "artifact": artifact,
        },
    )
    session.commit()
    return bible_snapshot(session, project_id)


async def confirm_round(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    round_index: int,
    spark: str,
    *,
    select: int = 1,
    volume_id: str = "v1",
    chapters_needed: int = 5,
    skip_concept_judge: bool = False,
) -> dict[str, Any]:
    if round_index < 0 or round_index > 5:
        raise PlanningError("轮次必须是 0–5")
    planning, bible, canon = _repos(session)
    done = bible.round_complete(project_id)
    kind = ROUND_KINDS[round_index]
    if kind in done:
        return await generate_pending_round(
            session,
            deps,
            project_id,
            spark,
            volume_id=volume_id,
            chapters_needed=chapters_needed,
            skip_concept_judge=skip_concept_judge,
        )
    pending = bible.get_pending_round(project_id)
    if pending is None or int(pending.get("round", -1)) != round_index:
        await generate_pending_round(
            session,
            deps,
            project_id,
            spark,
            volume_id=volume_id,
            chapters_needed=chapters_needed,
            round_index=round_index,
            skip_concept_judge=skip_concept_judge,
        )
        pending = bible.get_pending_round(project_id)
    if pending is None or int(pending.get("round", -1)) != round_index:
        raise PlanningError(f"没有可确认的 R{round_index} 产物")
    _persist_artifact(
        planning,
        bible,
        canon,
        project_id,
        round_index,
        pending["artifact"],
        select=select,
        volume_id=volume_id,
    )
    bible.set_pending_round(project_id, None)
    session.commit()
    if round_index in {2, 4} and not skip_concept_judge:
        try:
            await ensure_concept_judge(
                bible,
                planning,
                deps,
                project_id,
                f"R{round_index}",
                skip=False,
                volume_id=volume_id,
                chapters_needed=chapters_needed,
            )
        except ConceptJudgeStopped:
            session.commit()
            return bible_snapshot(session, project_id)
    return await generate_pending_round(
        session,
        deps,
        project_id,
        spark,
        volume_id=volume_id,
        chapters_needed=chapters_needed,
        skip_concept_judge=skip_concept_judge,
    )


async def _generate_artifact(
    session: Session,
    deps: AgentDeps,
    project_id: int,
    spark: str,
    round_index: int,
    volume_id: str,
    chapters_needed: int,
) -> dict[str, Any]:
    planning, bible, _canon = _repos(session)
    project = planning.get_project(project_id)
    if round_index == 0:
        text = spark.strip() or (project.spark or "").strip()
        if not text:
            raise PlanningError("火花不能为空")
        brief = brief_from_spark(text, list(project.boundaries or []))
        return brief.model_dump(mode="json")
    brief = _require_brief(bible, project_id, spark, project)
    kernel = planning.get_approved_kernel(project_id)
    if round_index == 1:
        candidates = await run_kernel_planner(deps, _dump(brief))
        return candidates.model_dump(mode="json")
    if kernel is None:
        raise PlanningError("尚未确认故事内核")
    if round_index == 2:
        keys = planned_chapter_keys(volume_id, chapters_needed)
        smap = await run_structure_planner(
            deps, _kernel_text(kernel), _dump(brief), chapter_keys=keys
        )
        report = lint_bible(structure=smap, live_names=live_names_from_kernel(kernel))
        if not report.passed:
            raise _lint_error(report)
        return smap.model_dump(mode="json")
    if round_index == 3:
        people = await run_people_planner(deps, _kernel_text(kernel), _dump(brief))
        if not people.characters:
            raise PlanningError("角色规划未返回任何角色卡")
        rel_report = lint_bible(relationship_proposals=people.relationship_proposals)
        if not rel_report.passed:
            raise _lint_error(rel_report)
        return {
            "characters": [card.model_dump(mode="json") for card in people.characters],
            "relationship_proposals": [
                item.model_dump(mode="json") for item in people.relationship_proposals
            ],
        }
    characters = planning.list_characters(project_id)
    keys = planned_chapter_keys(volume_id, chapters_needed)
    if round_index == 4:
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
        return {
            "conflicts": [item.model_dump(mode="json") for item in conflicts],
            "payoff_beats": [item.model_dump(mode="json") for item in beats],
        }
    if round_index == 5:
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
        outline_keys = [outline.chapter_key for outline in outlines]
        citations = [
            (outline.chapter_key, outline.cited_conflict_ids, outline.cited_beat_ids)
            for outline in outlines
        ]
        report = lint_bible(
            structure=bible.get_structure_map(project_id),
            conflicts=bible.list_conflicts(project_id),
            payoff_beats=bible.list_payoff_beats(project_id),
            rolling_keys=outline_keys,
            outline_citations=citations,
            live_names=live_names_from_kernel(kernel),
        )
        if not report.passed:
            raise _lint_error(report)
        return {
            "volume_id": volume_id,
            "unit": unit.model_dump(mode="json"),
            "outlines": [item.model_dump(mode="json") for item in outlines],
            "scenes": {
                key: [card.model_dump(mode="json") for card in cards]
                for key, cards in by_chapter.items()
            },
        }
    raise PlanningError(f"未知轮次 R{round_index}")


def _require_brief(
    bible: BibleRepo, project_id: int, spark: str, project: Any
) -> StoryBrief:
    existing = bible.get_brief(project_id)
    if existing is not None:
        return existing
    text = spark.strip() or (project.spark or "").strip()
    if not text:
        raise PlanningError("火花不能为空")
    return brief_from_spark(text, list(project.boundaries or []))


def _persist_artifact(
    planning: PlanningRepo,
    bible: BibleRepo,
    canon: CanonRepo,
    project_id: int,
    round_index: int,
    artifact: dict[str, Any],
    *,
    select: int,
    volume_id: str,
) -> None:
    if round_index == 0:
        bible.save_brief(project_id, StoryBrief.model_validate(artifact))
        return
    if round_index == 1:
        candidates = [StoryKernel.model_validate(item) for item in artifact["candidates"]]
        index = select - 1
        if index < 0 or index >= len(candidates):
            raise PlanningError(f"内核候选编号越界: {select}(共 {len(candidates)} 个)")
        versions: list[int] = []
        for candidate in candidates:
            rec = planning.save_kernel(project_id, candidate)
            versions.append(rec.version)
        planning.approve_kernel(project_id, versions[index])
        return
    if round_index == 2:
        bible.save_structure_map(project_id, StructureMap.model_validate(artifact))
        return
    if round_index == 3:
        characters = [CharacterCard.model_validate(item) for item in artifact["characters"]]
        for card in characters:
            planning.upsert_character(project_id, card)
        for proposal in artifact.get("relationship_proposals") or []:
            canon.upsert_relationship(
                project_id,
                proposal["parties"][0],
                proposal["parties"][1],
                proposal["state"],
                evidence=proposal.get("evidence") or "",
                source_chapter="planning",
                provisional=True,
            )
        return
    if round_index == 4:
        conflicts = [Conflict.model_validate(item) for item in artifact["conflicts"]]
        beats = [PayoffBeat.model_validate(item) for item in artifact["payoff_beats"]]
        bible.replace_conflicts(project_id, conflicts)
        bible.replace_payoff_beats(project_id, beats)
        return
    if round_index == 5:
        unit = PlotUnitCard.model_validate(artifact["unit"])
        outlines = [ChapterOutline.model_validate(item) for item in artifact["outlines"]]
        by_chapter = {
            key: [SceneCard.model_validate(item) for item in cards]
            for key, cards in artifact["scenes"].items()
        }
        vol = artifact.get("volume_id") or volume_id
        brief = bible.get_brief(project_id)
        keys = [outline.chapter_key for outline in outlines]
        volume = planning.save_volume(
            project_id,
            vol,
            {
                "goal": unit.promise_or_debt,
                "position": unit.position_in_volume,
                "trigger": unit.trigger,
                "climax": unit.climax,
                "payoff": unit.payoff,
                "canon_constraints": unit.canon_constraints,
                "unit_ids": [unit.unit_id],
                "chapter_keys": keys,
                "brief": brief.spark if brief else "",
            },
            title=unit.position_in_volume,
        )
        volume.status = "confirmed"
        unit_rec = planning.save_unit(project_id, vol, unit)
        unit_rec.status = "confirmed"
        for order, outline in enumerate(outlines, start=1):
            aligned = outline.model_copy(update={"volume_id": vol, "unit_id": unit.unit_id})
            planning.create_chapter(project_id, aligned, order_index=order)
            planning.save_scene_cards(
                project_id, aligned.chapter_key, by_chapter[outline.chapter_key]
            )
        return
    raise PlanningError(f"未知轮次 R{round_index}")
