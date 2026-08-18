"""百万字卷工厂:滚动窗口续规划、卷翻转、批次选章。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from novel_agent.domain.models import ChapterRecord
from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import (
    ChapterOutline,
    ChapterStatus,
    CharacterCard,
    Conflict,
    PayoffBeat,
    PlotUnitCard,
    SceneCard,
    StoryKernel,
)
from novel_agent.lint.bible import (
    _clean_token_list,
    lint_bible,
    live_names_from_kernel,
    sanitize_outline,
)
from novel_agent.memory.factory import memory_retrieval_for_session
from novel_agent.planning.chain import PlanningAborted, PlanningError, PlanningGates, _kernel_text
from novel_agent.planning.conversation import _dump, _lint_error
from novel_agent.runtime.agents import (
    AgentDeps,
    run_conflict_planner,
    run_outline_planner,
    run_payoff_planner,
)

DEFAULT_WINDOW = 5
_DONE = frozenset({ChapterStatus.CANON_LOCKED, ChapterStatus.EXPORTED})
_CHAPTER_KEY = re.compile(r"^(v\d+)c(\d+)$")
_UNIT_ID = re.compile(r"^u(\d+)$")
_VOLUME_ID = re.compile(r"^v(\d+)$")


class PlanMoreError(PlanningError):
    """续规划失败(窗口参数、圣经未就绪、产物不足)。"""


@dataclass
class PlanMoreResult:
    project_id: int
    volume_id: str
    unit_id: str
    chapter_keys: list[str]
    opened_new_volume: bool = False
    skipped: list[str] = field(default_factory=list)


def planned_ahead(chapters: Sequence[ChapterRecord]) -> list[ChapterRecord]:
    return [chapter for chapter in chapters if chapter.status not in _DONE]


def window_deficit(chapters: Sequence[ChapterRecord], window: int = DEFAULT_WINDOW) -> int:
    if window < 1:
        raise PlanMoreError("滚动窗口必须 >= 1")
    return max(0, window - len(planned_ahead(chapters)))


def select_write_batch_keys(
    planning: PlanningRepo,
    project_id: int,
    chapter_count: int,
    *,
    from_chapter: str | None = None,
) -> list[str]:
    """跳过已锁定章,从指定章或最早未完成章起取 N 个。"""
    ordered = planning.list_chapters(project_id)
    if from_chapter:
        keys = [chapter.chapter_key for chapter in ordered]
        if from_chapter not in keys:
            raise PlanMoreError(f"章节不存在: {from_chapter}")
        ordered = ordered[keys.index(from_chapter) :]
    return [
        chapter.chapter_key for chapter in ordered if chapter.status not in _DONE
    ][:chapter_count]


def next_volume_id(volume_id: str) -> str:
    match = _VOLUME_ID.fullmatch(volume_id)
    if not match:
        raise PlanMoreError(f"无法递增卷号: {volume_id}")
    return f"v{int(match.group(1)) + 1}"


def next_unit_id(existing: Sequence[str]) -> str:
    best = 0
    for unit_id in existing:
        match = _UNIT_ID.fullmatch(unit_id)
        if match:
            best = max(best, int(match.group(1)))
    return f"u{best + 1}"


def chapter_seq(chapter_key: str) -> int:
    match = _CHAPTER_KEY.fullmatch(chapter_key)
    return int(match.group(2)) if match else 0


def volume_of(chapter_key: str) -> str:
    match = _CHAPTER_KEY.fullmatch(chapter_key)
    return match.group(1) if match else ""


def planned_chapter_keys(volume_id: str, count: int, *, start: int = 1) -> list[str]:
    if count < 1:
        return []
    return [f"{volume_id}c{i:03d}" for i in range(start, start + count)]


def volume_arc_paid_off(
    planning: PlanningRepo, bible: BibleRepo, project_id: int
) -> bool:
    """当前剧情单元已标记 locked 时视为应付下一卷。"""
    chapters = planning.list_chapters(project_id)
    if not chapters:
        return False
    latest = chapters[-1]
    unit_rec = next(
        (
            rec
            for rec in planning.list_unit_records(project_id)
            if rec.unit_id == latest.unit_id
        ),
        None,
    )
    if unit_rec is None or unit_rec.status != "locked":
        return False
    return bible.get_structure_map(project_id) is not None


def collect_spoiler_state(
    outlines: Sequence[ChapterOutline],
) -> tuple[list[str], list[str]]:
    forbidden: list[str] = []
    allowed: list[str] = []
    seen_f: set[str] = set()
    seen_a: set[str] = set()
    for outline in outlines:
        for item in outline.reveal_forbidden:
            if item and item not in seen_f:
                seen_f.add(item)
                forbidden.append(item)
        for item in outline.reveal_allowed:
            if item and item not in seen_a:
                seen_a.add(item)
                allowed.append(item)
    remaining = [item for item in forbidden if item not in seen_a]
    return remaining, allowed


def apply_inherited_spoilers(
    outlines: Sequence[ChapterOutline], remaining_forbidden: Sequence[str]
) -> list[ChapterOutline]:
    updated: list[ChapterOutline] = []
    remaining = _clean_token_list(remaining_forbidden)
    for outline in outlines:
        forbidden = _clean_token_list([*remaining, *outline.reveal_forbidden])
        allowed = [item for item in outline.reveal_allowed if item not in remaining]
        updated.append(
            outline.model_copy(update={"reveal_forbidden": forbidden, "reveal_allowed": allowed})
        )
    return updated


def _canon_notes(canon: CanonRepo, project_id: int) -> str:
    states = canon.latest_entity_states(project_id, include_provisional=True)
    if not states:
        return "(尚无正史实体状态)"
    lines = []
    for (entity_id, state_type), rec in sorted(states.items()):
        flag = "provisional" if rec.provisional else "committed"
        lines.append(
            f"{entity_id}.{state_type}={rec.value} ({flag} {rec.source_chapter})"
        )
    return "\n".join(lines)


def _existing_outlines(planning: PlanningRepo, project_id: int) -> list[ChapterOutline]:
    outlines: list[ChapterOutline] = []
    for chapter in planning.list_chapters(project_id):
        if chapter.outline:
            outlines.append(planning.get_outline(project_id, chapter.chapter_key))
    return outlines


def _merge_by_id(existing: list, incoming: list, attr: str) -> list:
    by_id = {getattr(item, attr): item for item in existing}
    for item in incoming:
        key = getattr(item, attr)
        if key not in by_id:
            by_id[key] = item
    return list(by_id.values())


def _align_slice(
    outlines: list[ChapterOutline],
    by_chapter: dict[str, list[SceneCard]],
    chapter_keys: list[str],
    volume_id: str,
    unit_id: str,
) -> tuple[list[ChapterOutline], dict[str, list[SceneCard]]]:
    if len(outlines) < len(chapter_keys):
        raise PlanMoreError(
            f"章纲数量不足: 需要 {len(chapter_keys)}, 得到 {len(outlines)}"
        )
    returned = {outline.chapter_key: outline for outline in outlines}
    aligned: list[ChapterOutline] = []
    scenes: dict[str, list[SceneCard]] = {}
    for index, key in enumerate(chapter_keys):
        source = returned.get(key, outlines[index])
        cards = by_chapter.get(source.chapter_key) or by_chapter.get(key) or []
        if not cards:
            raise PlanMoreError(f"以下章节缺少场景卡: {key}")
        aligned.append(
            source.model_copy(
                update={"chapter_key": key, "volume_id": volume_id, "unit_id": unit_id}
            )
        )
        remapped: list[SceneCard] = []
        for order, card in enumerate(cards, start=1):
            scene_id = card.scene_id
            if not scene_id.startswith(f"{key}_"):
                scene_id = f"{key}_s{order}"
            remapped.append(card.model_copy(update={"chapter_key": key, "scene_id": scene_id}))
        scenes[key] = remapped
    return aligned, scenes


async def plan_more(
    planning: PlanningRepo,
    bible: BibleRepo,
    canon: CanonRepo,
    deps: AgentDeps,
    project_id: int,
    gates: PlanningGates,
    *,
    window: int = DEFAULT_WINDOW,
    chapters: int | None = None,
    open_volume: bool | None = None,
) -> PlanMoreResult:
    """在已有 Story Bible 上生成下一截滚动章纲,不重跑 R0–R5。"""
    if project_id != deps.project_id and deps.project_id is not None:
        raise PlanMoreError("project_id 与 AgentDeps 不一致")
    kernel = planning.get_approved_kernel(project_id)
    if kernel is None:
        raise PlanMoreError("续规划需要已批准的故事内核")
    characters = planning.list_characters(project_id)
    if not characters:
        raise PlanMoreError("续规划需要已确认的角色卡")
    existing = planning.list_chapters(project_id)
    if not existing:
        raise PlanMoreError("续规划需要先完成开书滚动章纲")

    count = chapters if chapters is not None else window_deficit(existing, window)
    if count < 1:
        latest = existing[-1]
        return PlanMoreResult(
            project_id=project_id,
            volume_id=latest.volume_id,
            unit_id=latest.unit_id,
            chapter_keys=[],
            skipped=["window_full"],
        )

    current_volume = existing[-1].volume_id
    current_unit_id = existing[-1].unit_id
    unit_chapters = [chapter for chapter in existing if chapter.unit_id == current_unit_id]
    unit_fully_locked = bool(unit_chapters) and all(
        chapter.status in _DONE for chapter in unit_chapters
    )
    open_next = open_volume if open_volume is not None else volume_arc_paid_off(
        planning, bible, project_id
    )

    if open_next:
        volume_id = next_volume_id(current_volume)
        unit_id = next_unit_id([rec.unit_id for rec in planning.list_unit_records(project_id)])
        keys = planned_chapter_keys(volume_id, count, start=1)
        reuse_unit = False
    else:
        volume_id = current_volume
        volume_chapters = [chapter for chapter in existing if chapter.volume_id == volume_id]
        seqs = (chapter_seq(chapter.chapter_key) for chapter in volume_chapters)
        start = max(seqs, default=0) + 1
        keys = planned_chapter_keys(volume_id, count, start=start)
        if unit_fully_locked:
            unit_id = next_unit_id(
                [rec.unit_id for rec in planning.list_unit_records(project_id)]
            )
            reuse_unit = False
        else:
            unit_id = current_unit_id
            reuse_unit = True

    previous_outlines = [
        sanitize_outline(outline) for outline in _existing_outlines(planning, project_id)
    ]
    remaining_forbidden, _allowed = collect_spoiler_state(previous_outlines)
    spoiler_notes = "\n".join(f"- {item}" for item in remaining_forbidden) or "(无)"
    current_unit = planning.get_unit(project_id, current_unit_id) if reuse_unit else None

    conflicts, beats = await _extend_bible_slice(
        bible, deps, project_id, kernel, characters, keys
    )
    all_keys = [chapter.chapter_key for chapter in existing] + keys
    unit, outlines, by_chapter = await run_outline_planner(
        deps,
        _kernel_text(kernel),
        _characters_text(characters, bible.get_brief(project_id)),
        volume_id,
        current_unit,
        len(keys),
        chapter_keys=keys,
        unit_id=unit_id,
        spoiler_notes=spoiler_notes,
        canon_notes=_canon_notes(canon, project_id),
    )
    aligned, scenes = _align_slice(outlines, by_chapter, keys, volume_id, unit_id)
    aligned = apply_inherited_spoilers(aligned, remaining_forbidden)
    aligned = [sanitize_outline(outline) for outline in aligned]
    citations = [
        (outline.chapter_key, outline.cited_conflict_ids, outline.cited_beat_ids)
        for outline in [*previous_outlines, *aligned]
    ]
    report = lint_bible(
        structure=bible.get_structure_map(project_id),
        conflicts=conflicts,
        payoff_beats=beats,
        rolling_keys=all_keys,
        outline_citations=citations,
        previous_outlines=previous_outlines,
        new_outlines=aligned,
        live_names=live_names_from_kernel(kernel),
    )
    if not report.passed:
        raise _lint_error(report)

    prompt = (
        f"确认写入{'新卷 ' + volume_id if open_next else '续规划 ' + volume_id}、"
        f"剧情单元 {unit_id} 与滚动章纲 {', '.join(keys)}?"
    )
    if not gates.confirm(prompt):
        raise PlanningAborted("plan_more", project_id)

    _persist_slice(
        planning,
        project_id,
        volume_id,
        unit.model_copy(update={"unit_id": unit_id}) if not reuse_unit else unit,
        aligned,
        scenes,
        keys,
        reuse_unit=reuse_unit,
        opened_new_volume=open_next,
    )
    if open_next:
        _lock_unit(planning, project_id, current_unit_id)
    from novel_agent.annals.skeleton import extend_annals_for_outlines
    from novel_agent.domain.repos.annals import AnnalsRepo

    extend_annals_for_outlines(planning, AnnalsRepo(planning.s), project_id)
    planning.s.commit()
    memory_retrieval_for_session(planning.s).reindex(project_id)
    return PlanMoreResult(
        project_id=project_id,
        volume_id=volume_id,
        unit_id=unit_id,
        chapter_keys=keys,
        opened_new_volume=open_next,
    )


def _characters_text(characters: list[CharacterCard], brief: object) -> str:
    blob = json.dumps([card.model_dump() for card in characters], ensure_ascii=False)
    if brief is not None:
        return f"{_dump(brief)}\n{blob}"
    return blob


async def _extend_bible_slice(
    bible: BibleRepo,
    deps: AgentDeps,
    project_id: int,
    kernel: StoryKernel,
    characters: list[CharacterCard],
    keys: list[str],
) -> tuple[list[Conflict], list[PayoffBeat]]:
    characters_text = json.dumps(
        [card.model_dump() for card in characters], ensure_ascii=False
    )
    incoming_conflicts = await run_conflict_planner(
        deps, _kernel_text(kernel), characters_text, keys
    )
    existing_conflicts = bible.list_conflicts(project_id)
    conflicts = _merge_by_id(existing_conflicts, incoming_conflicts, "conflict_id")
    incoming_beats = await run_payoff_planner(
        deps,
        _kernel_text(kernel),
        _dump([item.model_dump() for item in incoming_conflicts]),
        keys,
    )
    existing_beats = bible.list_payoff_beats(project_id)
    max_order = max((beat.order_index for beat in existing_beats), default=0)
    shifted: list[PayoffBeat] = []
    for offset, beat in enumerate(incoming_beats, start=1):
        if beat.beat_id in {item.beat_id for item in existing_beats}:
            continue
        order = beat.order_index if beat.order_index > max_order else max_order + offset
        shifted.append(beat.model_copy(update={"order_index": order}))
    beats = existing_beats + shifted
    bible.replace_conflicts(project_id, conflicts)
    bible.replace_payoff_beats(project_id, beats)
    bible.s.flush()
    return conflicts, beats


def _lock_unit(planning: PlanningRepo, project_id: int, unit_id: str) -> None:
    rec = next(
        (
            row
            for row in planning.list_unit_records(project_id)
            if row.unit_id == unit_id
        ),
        None,
    )
    if rec is not None:
        rec.status = "locked"
        planning.s.add(rec)


def _persist_slice(
    planning: PlanningRepo,
    project_id: int,
    volume_id: str,
    unit: PlotUnitCard,
    outlines: list[ChapterOutline],
    scenes: dict[str, list[SceneCard]],
    keys: list[str],
    *,
    reuse_unit: bool,
    opened_new_volume: bool,
) -> None:
    volumes = {rec.volume_id: rec for rec in planning.list_volumes(project_id)}
    if opened_new_volume or volume_id not in volumes:
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
            },
            title=unit.position_in_volume,
        )
        volume.status = "confirmed"
        planning.s.add(volume)
    else:
        rec = volumes[volume_id]
        payload = dict(rec.payload or {})
        chapter_keys = list(payload.get("chapter_keys") or [])
        for key in keys:
            if key not in chapter_keys:
                chapter_keys.append(key)
        payload["chapter_keys"] = chapter_keys
        unit_ids = list(payload.get("unit_ids") or [])
        if unit.unit_id not in unit_ids:
            unit_ids.append(unit.unit_id)
        payload["unit_ids"] = unit_ids
        rec.payload = payload
        planning.s.add(rec)

    if not reuse_unit:
        unit_rec = planning.save_unit(project_id, volume_id, unit)
        unit_rec.status = "confirmed"
        planning.s.add(unit_rec)

    next_order = max(
        (chapter.order_index for chapter in planning.list_chapters(project_id)),
        default=0,
    )
    for offset, outline in enumerate(outlines, start=1):
        planning.create_chapter(project_id, outline, order_index=next_order + offset)
        planning.save_scene_cards(project_id, outline.chapter_key, scenes[outline.chapter_key])
