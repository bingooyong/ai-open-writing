"""规划链编排:复用 runtime 规划 Agent + PlanningRepo,单轮生成+人工确认。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import CharacterCard, StoryKernel
from novel_agent.runtime.agents import (
    AgentDeps,
    run_character_planner,
    run_kernel_planner,
    run_outline_planner,
)


class PlanningError(Exception):
    """规划链硬失败(输出不足、编号越界、项目未就绪)。"""


class PlanningAborted(Exception):
    """人工门禁拒绝继续。已确认阶段保持入库。"""

    def __init__(self, stage: str, project_id: int) -> None:
        super().__init__(stage)
        self.stage = stage
        self.project_id = project_id


@dataclass(frozen=True)
class PlanningGates:
    """人工门禁注入点:CLI 交互或 --yes / 测试夹具。"""

    select_kernel: Callable[[list[StoryKernel]], int]
    confirm: Callable[[str], bool]

    @staticmethod
    def auto(select_index: int = 0) -> PlanningGates:
        return PlanningGates(
            select_kernel=lambda _candidates: select_index,
            confirm=lambda _prompt: True,
        )


@dataclass
class PlanningResult:
    project_id: int
    kernel_version: int
    character_ids: list[str]
    volume_id: str
    unit_id: str
    chapter_keys: list[str]
    skipped: list[str] = field(default_factory=list)


def _kernel_text(kernel: StoryKernel) -> str:
    return json.dumps(kernel.model_dump(), ensure_ascii=False)


async def run_planning_chain(
    repo: PlanningRepo,
    deps: AgentDeps,
    brief: str,
    gates: PlanningGates,
    *,
    volume_id: str = "v1",
    chapters_needed: int = 5,
) -> PlanningResult:
    """开书规划链:三候选内核→角色卡→卷纲/单元→滚动章纲+场景卡。

    已完成阶段跳过(供 `novel plan` 续跑)。每阶段在人工确认后立即 commit。
    """
    project_id = deps.project_id
    if project_id is None:
        raise PlanningError("规划链需要 project_id")
    if chapters_needed < 1:
        raise PlanningError("滚动章纲数量必须 >= 1")
    if not brief.strip():
        raise PlanningError("创作简报不能为空")

    skipped: list[str] = []
    kernel, kernel_version = await _ensure_kernel(repo, deps, brief, gates, project_id, skipped)
    characters = await _ensure_characters(
        repo, deps, brief, gates, project_id, kernel, skipped
    )
    unit_id, chapter_keys = await _ensure_outline(
        repo,
        deps,
        brief,
        gates,
        project_id,
        kernel,
        characters,
        volume_id,
        chapters_needed,
        skipped,
    )
    from novel_agent.annals.skeleton import ensure_annals_cover
    from novel_agent.domain.repos.annals import AnnalsRepo

    ensure_annals_cover(
        repo, AnnalsRepo(repo.s), project_id, auto_not_applicable_only=True
    )
    return PlanningResult(
        project_id=project_id,
        kernel_version=kernel_version,
        character_ids=[card.character_id for card in characters],
        volume_id=volume_id,
        unit_id=unit_id,
        chapter_keys=chapter_keys,
        skipped=skipped,
    )


async def _ensure_kernel(
    repo: PlanningRepo,
    deps: AgentDeps,
    brief: str,
    gates: PlanningGates,
    project_id: int,
    skipped: list[str],
) -> tuple[StoryKernel, int]:
    existing = repo.get_approved_kernel(project_id)
    if existing is not None:
        skipped.append("kernel")
        approved = next(rec for rec in repo.list_kernels(project_id) if rec.approved)
        return existing, approved.version

    candidate_set = await run_kernel_planner(deps, brief)
    candidates = list(candidate_set.candidates)
    index = gates.select_kernel(candidates)
    if index < 0 or index >= len(candidates):
        raise PlanningError(f"内核候选编号越界: {index + 1}(共 {len(candidates)} 个)")

    versions: list[int] = []
    for candidate in candidates:
        rec = repo.save_kernel(project_id, candidate)
        versions.append(rec.version)
    selected_version = versions[index]
    repo.approve_kernel(project_id, selected_version)
    repo.s.commit()
    return candidates[index], selected_version


async def _ensure_characters(
    repo: PlanningRepo,
    deps: AgentDeps,
    brief: str,
    gates: PlanningGates,
    project_id: int,
    kernel: StoryKernel,
    skipped: list[str],
) -> list[CharacterCard]:
    existing = repo.list_characters(project_id)
    if existing:
        skipped.append("characters")
        return existing

    generated = await run_character_planner(deps, _kernel_text(kernel), brief)
    if not generated:
        raise PlanningError("角色规划未返回任何角色卡")
    names = ", ".join(f"{card.name}({card.character_id})" for card in generated)
    if not gates.confirm(f"确认写入以上角色卡? {names}"):
        raise PlanningAborted("characters", project_id)
    for card in generated:
        repo.upsert_character(project_id, card)
    repo.s.commit()
    return generated


async def _ensure_outline(
    repo: PlanningRepo,
    deps: AgentDeps,
    brief: str,
    gates: PlanningGates,
    project_id: int,
    kernel: StoryKernel,
    characters: list[CharacterCard],
    volume_id: str,
    chapters_needed: int,
    skipped: list[str],
) -> tuple[str, list[str]]:
    existing = repo.list_chapters(project_id)
    if existing:
        skipped.append("outline")
        return existing[0].unit_id, [chapter.chapter_key for chapter in existing]

    characters_text = json.dumps(
        [card.model_dump() for card in characters], ensure_ascii=False
    )
    unit, outlines, by_chapter = await run_outline_planner(
        deps,
        _kernel_text(kernel),
        f"{brief}\n{characters_text}",
        volume_id,
        None,
        chapters_needed,
    )
    if len(outlines) < chapters_needed:
        raise PlanningError(
            f"章纲数量不足: 需要 {chapters_needed}, 得到 {len(outlines)}"
        )
    missing_scenes = [
        outline.chapter_key
        for outline in outlines
        if not by_chapter.get(outline.chapter_key)
    ]
    if missing_scenes:
        raise PlanningError(f"以下章节缺少场景卡: {missing_scenes}")

    keys = [outline.chapter_key for outline in outlines]
    prompt = (
        f"确认写入卷纲 {volume_id}、剧情单元 {unit.unit_id} "
        f"与滚动章纲/场景卡 {', '.join(keys)}?"
    )
    if not gates.confirm(prompt):
        raise PlanningAborted("outline", project_id)

    volume = repo.save_volume(
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
            "brief": brief,
        },
        title=unit.position_in_volume,
    )
    volume.status = "confirmed"
    unit_rec = repo.save_unit(project_id, volume_id, unit)
    unit_rec.status = "confirmed"
    for order, outline in enumerate(outlines, start=1):
        aligned = outline.model_copy(
            update={"volume_id": volume_id, "unit_id": unit.unit_id}
        )
        repo.create_chapter(project_id, aligned, order_index=order)
        repo.save_scene_cards(project_id, aligned.chapter_key, by_chapter[outline.chapter_key])
    repo.s.commit()
    return unit.unit_id, keys
