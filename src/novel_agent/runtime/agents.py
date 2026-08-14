"""Agent 层(M2.4):七类认知任务 Agent + 并发评审执行器。

设计(Spec §7 + 核验报告 M2.4 结论):
- 每个 Agent = 单次调用、独立上下文、严格 IO Schema;不持久、不自主循环;
- 全部模型调用经 ModelGateway(D7),角色-槽位路由由提示词 frontmatter 声明;
- 并发评审 asyncio.gather 自管(G0 fallback);Continuity/RedTeam 不可缺席(Spec §6 N5);
- 写手不审自己/评审不改稿/裁判不写正文/修订者不新增问题 —— 由类型边界与 lint 强制。
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Generic, TypeVar, assert_never

from pydantic import BaseModel, ConfigDict, Field

from novel_agent.domain.schemas import (
    CanonDelta,
    ChapterContextPackage,
    ChapterOutline,
    CharacterCard,
    ConceptJudgeVerdict,
    Conflict,
    DraftCandidate,
    JudgeVerdict,
    KernelCandidateSet,
    PayoffBeat,
    PlotUnitCard,
    RelationshipProposal,
    ReviewerRole,
    ReviewIssue,
    ReviewReport,
    RevisionOrder,
    SceneCard,
    SceneDraft,
    StoryKernel,
    StructureMap,
)
from novel_agent.domain.window_scope import scope_structure_for_judge
from novel_agent.gateway.base import ModelGateway, ModelRequest
from novel_agent.gateway.structured import TWO_PART_FORMAT_INSTRUCTIONS, StructuredOutputError
from novel_agent.runtime.adapter import CognitiveRuntime, GatewayRuntimeAdapter, RuntimeCall
from novel_agent.runtime.blinding import (
    DEFAULT_FORBIDDEN,
    anonymize_absent,
    anonymize_issues_with_mapping,
    assert_no_leak,
)
from novel_agent.runtime.prompts import PromptSpec, load_prompt

# 不可缺席评审(Spec §6 N5)
CRITICAL_REVIEWERS = frozenset({ReviewerRole.CONTINUITY, ReviewerRole.RED_TEAM})
EVIDENCE_FUZZY_THRESHOLD = 0.80
EVIDENCE_REPAIR_MAX_TOKENS = 4_000
OUTLINE_PLANNER_MAX_TOKENS = 32_768
PEOPLE_PLANNER_MAX_TOKENS = 16_384
STRUCTURE_PLANNER_MAX_TOKENS = 16_384
EVIDENCE_REPAIR_INSTRUCTIONS = (
    "连续正文引文修复要求：每条 evidence.quote 必须从对应场景复制连续的正文原文，"
    "至少12个汉字，不得概括、改写、拼接或引用场景卡；无法逐字定位的问题请删除。"
)
OutputT = TypeVar("OutputT", bound=BaseModel)


class _ConflictList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conflicts: list[Conflict]


class _PayoffBeatList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beats: list[PayoffBeat]


class _PeoplePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    characters: list[CharacterCard]
    relationship_proposals: list[RelationshipProposal] = Field(default_factory=list)


class CognitiveTask(StrEnum):
    """The seven bounded cognitive task families used in stage 0."""

    PLANNING = "planning"
    WRITING = "writing"
    RED_TEAM = "red_team"
    REVIEW = "review"
    JUDGING = "judging"
    REVISION = "revision"
    CANON_CURATING = "canon_curating"


def _ctx_text(ctx: ChapterContextPackage) -> str:
    """上下文包 → 注入文本(顺序对齐 PRD §12.2)。"""
    parts = [
        f"# 任务\n{ctx.task_brief}",
        f"# 故事内核与读者契约\n{ctx.kernel_summary}",
        "# 硬约束(不可违背)\n"
        + "\n".join(
            f"- {'[提案态] ' if f.provisional else ''}{f.content}" for f in ctx.hard_constraints
        ),
        f"# 本卷\n{ctx.volume_summary}",
        f"# 剧情单元\n{json.dumps(ctx.unit_card.model_dump(), ensure_ascii=False)}",
        f"# 章纲\n{json.dumps(ctx.outline.model_dump(), ensure_ascii=False)}",
        "# 场景卡\n"
        + "\n".join(json.dumps(c.model_dump(), ensure_ascii=False) for c in ctx.scene_cards),
    ]
    if ctx.retrieval_facts:
        parts.append(
            "# 检索到的相关事实\n" + "\n".join(f"- {item}" for item in ctx.retrieval_facts)
        )
    if ctx.previous_ending:
        parts.append(f"# 上一章结尾\n{ctx.previous_ending}")
    if ctx.earlier_summaries:
        parts.append("# 更早章节摘要\n" + "\n".join(ctx.earlier_summaries))
    if ctx.characters:
        parts.append(
            "# 出场角色档案\n"
            + "\n".join(json.dumps(c.model_dump(), ensure_ascii=False) for c in ctx.characters)
        )
    if ctx.entity_states:
        parts.append(
            "# 实体当前状态\n"
            + "\n".join(
                f"- {'[提案态] ' if f.provisional else ''}{f.content}" for f in ctx.entity_states
            )
        )
    if ctx.active_threads:
        parts.append(
            "# 相关伏笔\n"
            + "\n".join(f"- {t.thread_id}: {t.summary}({t.status})" for t in ctx.active_threads)
        )
    if ctx.style_rules:
        parts.append(f"# 风格规则\n{ctx.style_rules}")
    if ctx.boundaries:
        parts.append("# 禁写项\n" + "\n".join(f"- {b}" for b in ctx.boundaries))
    if ctx.prior_feedback:
        parts.append(f"# 上一轮审校意见\n{ctx.prior_feedback}")
    return "\n\n".join(parts)


def _review_ctx_text(role: ReviewerRole, ctx: ChapterContextPackage) -> str:
    """Return the minimum role-specific context required by Spec section 7."""
    task = f"# 任务\n{ctx.task_brief}"
    hard_constraints = "# 硬约束\n" + "\n".join(
        f"- {'[提案态] ' if fact.provisional else ''}{fact.content}"
        for fact in ctx.hard_constraints
    )
    boundaries = "# 禁写项\n" + "\n".join(f"- {item}" for item in ctx.boundaries)
    outline = f"# 章纲\n{json.dumps(ctx.outline.model_dump(), ensure_ascii=False)}"
    scenes = "# 场景卡\n" + "\n".join(
        json.dumps(card.model_dump(), ensure_ascii=False) for card in ctx.scene_cards
    )

    match role:
        case ReviewerRole.RED_TEAM:
            return _ctx_text(ctx)
        case ReviewerRole.PLOT:
            return "\n\n".join(
                [
                    task,
                    hard_constraints,
                    f"# 剧情单元\n{json.dumps(ctx.unit_card.model_dump(), ensure_ascii=False)}",
                    outline,
                    scenes,
                    boundaries,
                ]
            )
        case ReviewerRole.CHARACTER:
            characters = "# 出场角色档案\n" + "\n".join(
                json.dumps(character.model_dump(), ensure_ascii=False)
                for character in ctx.characters
            )
            return "\n\n".join(
                [task, hard_constraints, outline, scenes, characters, boundaries]
            )
        case ReviewerRole.CONTINUITY:
            parts = [task, hard_constraints, outline, scenes]
            if ctx.retrieval_facts:
                parts.append(
                    "# 检索到的相关事实\n"
                    + "\n".join(f"- {item}" for item in ctx.retrieval_facts)
                )
            if ctx.previous_ending:
                parts.append(f"# 上一章结尾\n{ctx.previous_ending}")
            if ctx.earlier_summaries:
                parts.append("# 更早章节摘要\n" + "\n".join(ctx.earlier_summaries))
            if ctx.characters:
                parts.append(
                    "# 出场角色档案\n"
                    + "\n".join(
                        json.dumps(character.model_dump(), ensure_ascii=False)
                        for character in ctx.characters
                    )
                )
            if ctx.entity_states:
                parts.append(
                    "# 实体当前状态\n"
                    + "\n".join(
                        f"- {'[提案态] ' if fact.provisional else ''}{fact.content}"
                        for fact in ctx.entity_states
                    )
                )
            if ctx.active_threads:
                parts.append(
                    "# 相关伏笔\n"
                    + "\n".join(
                        f"- {thread.thread_id}: {thread.summary}({thread.status})"
                        for thread in ctx.active_threads
                    )
                )
            parts.append(boundaries)
            return "\n\n".join(parts)
        case ReviewerRole.PROSE:
            return "\n\n".join(
                [task, f"# 风格规则\n{ctx.style_rules}", boundaries]
            )
        case ReviewerRole.READER_ADVOCATE:
            return "\n\n".join(
                [
                    task,
                    f"# 故事内核与读者契约\n{ctx.kernel_summary}",
                    f"# 本卷\n{ctx.volume_summary}",
                    outline,
                    scenes,
                    "# 读者体验焦点\n黄金三章承诺、爽点节奏、章尾 exit_hook、无聊段与信息负担",
                    boundaries,
                ]
            )
        case ReviewerRole.SOURCE:
            return "\n\n".join([_ctx_text(ctx), "# 来源合规\n仅依据上下文包中的边界与正文举证"])
        case _:
            assert_never(role)


@dataclass
class AgentDeps:
    gateway: ModelGateway
    prompts_dir: Path | None = None
    project_id: int | None = None
    runtime: CognitiveRuntime | None = None
    verification_run_id: str = ""

    def __post_init__(self) -> None:
        if self.runtime is None:
            self.runtime = GatewayRuntimeAdapter(self.gateway)

    def prompt(self, role: str) -> PromptSpec:
        return load_prompt(role, self.prompts_dir)

    def version_refs(self, role: str) -> tuple[str, str]:
        if not self.verification_run_id:
            return "", ""
        base = f"m26:{self.verification_run_id}:{role}"
        return f"{base}:input:v1", f"{base}:output:v1"


@dataclass(frozen=True)
class CognitiveAgent(Generic[OutputT]):
    """Base for one-shot, tool-free cognitive tasks with a strict output schema."""

    deps: AgentDeps
    role: str
    task: CognitiveTask
    output_schema: type[OutputT]

    async def run(
        self,
        request: ModelRequest,
        *,
        chapter_key: str = "",
        repair_instructions: str | None = None,
    ) -> OutputT:
        spec = self.deps.prompt(self.role)
        input_ref, output_ref = self.deps.version_refs(self.role)
        runtime = self.deps.runtime
        if runtime is None:  # narrowed defensively for static type checkers
            raise RuntimeError("认知任务 runtime 未初始化")
        return await runtime.structured(
            spec.slot,
            request,
            self.output_schema,
            RuntimeCall(
                agent_role=self.role,
                prompt_version=spec.prompt_version,
                project_id=self.deps.project_id,
                chapter_key=chapter_key,
                input_ref=input_ref,
                output_ref=output_ref,
            ),
            repair_instructions=repair_instructions,
        )


# ---------- Writer ----------


async def run_writer(
    deps: AgentDeps, ctx: ChapterContextPackage, writer_id: str = "writer_a"
) -> DraftCandidate:
    """两段式输出(D16)→ 组装 DraftCandidate(candidate_id 临时用 writer_id,盲化在调度层)。"""
    spec = deps.prompt("writer")
    scene_ids = [c.scene_id for c in ctx.scene_cards]
    user = _ctx_text(ctx)
    if writer_id == "writer_b":
        user = (
            "# 差异化指令\n你是第二写手。在遵守全部硬约束的前提下,给出与主候选不同切入的正文"
            "(节奏、场面选择或对白策略不同),不得更换故事事实。\n\n"
            + user
        )
    req = ModelRequest(
        system=spec.render(format_instructions=TWO_PART_FORMAT_INSTRUCTIONS),
        user=user,
        max_tokens=16000,
    )
    runtime = deps.runtime
    if runtime is None:
        raise RuntimeError("认知任务 runtime 未初始化")
    input_ref, output_ref = deps.version_refs("writer")
    scenes, meta = await runtime.two_part(
        spec.slot,
        req,
        scene_ids,
        RuntimeCall(
            agent_role=writer_id,
            prompt_version=spec.prompt_version,
            project_id=deps.project_id,
            chapter_key=ctx.chapter_key,
            input_ref=input_ref,
            output_ref=output_ref,
        ),
    )
    return DraftCandidate(
        candidate_id="candidate_1",  # 占位;盲化调度层统一重排(M2.5)
        chapter_key=ctx.chapter_key,
        scenes=[SceneDraft(scene_id=sid, content=scenes[sid]) for sid in scene_ids],
        chapter_summary=str(meta.get("chapter_summary", "")) or "(缺摘要)",
        deviation_notes=str(meta.get("deviation_notes", "")),
    )


# ---------- Reviewer(含红队) ----------


def _evidence_locates(issue: ReviewIssue, draft: DraftCandidate) -> bool:
    """所有 evidence span 归一化后均必须能在对应场景定位。"""
    import difflib
    import unicodedata

    def norm(t: str) -> str:
        normalized = unicodedata.normalize("NFKC", t)
        return "".join(
            char
            for char in normalized
            if not char.isspace() and not unicodedata.category(char).startswith("P")
        )

    def locates(quote: str, body: str) -> bool:
        if quote in body:
            return True
        if len(quote) < 8:
            return False
        for width in range(max(1, len(quote) - 2), min(len(body), len(quote) + 2) + 1):
            for start in range(len(body) - width + 1):
                candidate = body[start : start + width]
                if difflib.SequenceMatcher(
                    None, quote, candidate, autojunk=False
                ).ratio() >= EVIDENCE_FUZZY_THRESHOLD:
                    return True
        return False

    scene_texts = {s.scene_id: norm(s.content) for s in draft.scenes}
    if not issue.evidence:
        return False
    for ev in issue.evidence:
        body = scene_texts.get(ev.scene_id, "")
        quote = norm(ev.quote)
        if not body or not quote or not locates(quote, body):
            return False
    return True


async def run_reviewer(
    deps: AgentDeps,
    role: ReviewerRole,
    draft: DraftCandidate,
    ctx: ChapterContextPackage,
    *,
    evidence_repair: bool = False,
) -> ReviewReport:
    """单评审:独立上下文;无证据/定位失败的 issue 降权标记(不过滤,Spec §7)。"""
    spec = deps.prompt(role.value)
    issue_schema = json.dumps(ReviewIssue.model_json_schema(), ensure_ascii=False)
    user = (
        f"{_review_ctx_text(role, ctx)}\n\n# 待审正文(候选 {draft.candidate_id})\n"
        + "\n\n".join(f"[场景 {s.scene_id}]\n{s.content}" for s in draft.scenes)
    )
    if evidence_repair:
        user = (
            "# 证据修复轮\n"
            "上一轮评审包含无法在正文定位的引文。请重新检查全部问题：每条 evidence.quote "
            "必须从对应场景复制连续的正文原文，至少12个汉字，不得概括、改写、拼接或引用场景卡；"
            "无法逐字定位的问题请删除，不要为了保留问题而编造引文。\n\n"
            + user
        )
    req = ModelRequest(
        system=spec.render(issue_schema=issue_schema, candidate_id=draft.candidate_id),
        user=user,
        max_tokens=EVIDENCE_REPAIR_MAX_TOKENS if evidence_repair else 8_000,
        temperature=0.3,
    )
    task = CognitiveTask.RED_TEAM if role is ReviewerRole.RED_TEAM else CognitiveTask.REVIEW
    report = await CognitiveAgent(deps, role.value, task, ReviewReport).run(
        req,
        chapter_key=ctx.chapter_key,
        repair_instructions=EVIDENCE_REPAIR_INSTRUCTIONS,
    )
    # 强制归位:role/candidate 以调度方为准;证据定位失败 → 降权
    fixed_issues = []
    for i, issue in enumerate(report.issues):
        updates: dict = {"reviewer_role": role, "issue_id": f"{role.value}_{i + 1}"}
        if not issue.evidence or not _evidence_locates(issue, draft):
            updates["downweighted"] = True
        fixed_issues.append(issue.model_copy(update=updates))
    return report.model_copy(
        update={"reviewer_role": role, "candidate_id": draft.candidate_id, "issues": fixed_issues}
    )


@dataclass
class ReviewRoundResult:
    reports: list[ReviewReport]
    absent: list[str]  # 缺席评审(已重试仍失败)


async def run_review_round(
    deps: AgentDeps,
    draft: DraftCandidate,
    ctx: ChapterContextPackage,
    roles: list[ReviewerRole] | None = None,
) -> ReviewRoundResult:
    """并发评审(G0 fallback:asyncio.gather)。

    失败策略(Spec §6 N5):Continuity/RedTeam 失败 → 整体节点失败(抛出);
    其余单缺席不阻断,缺席角色名留在结果/快照;Judge 只收匿名席位数。
    """
    roles = roles or [
        ReviewerRole.RED_TEAM,
        ReviewerRole.PLOT,
        ReviewerRole.CHARACTER,
        ReviewerRole.CONTINUITY,
        ReviewerRole.PROSE,
    ]
    results = await asyncio.gather(
        *(run_reviewer(deps, r, draft, ctx) for r in roles), return_exceptions=True
    )
    reports: list[ReviewReport] = []
    absent: list[str] = []
    for role, res in zip(roles, results, strict=True):
        if isinstance(res, BaseException):
            if role in CRITICAL_REVIEWERS:
                raise RuntimeError(f"关键评审 {role.value} 失败,节点失败(N5): {res}") from res
            absent.append(role.value)
        else:
            reports.append(res)
    return ReviewRoundResult(reports=reports, absent=absent)


# ---------- Judge ----------


async def run_judge(
    deps: AgentDeps,
    candidates: list[DraftCandidate],
    reports: list[ReviewReport],
    ctx: ChapterContextPackage,
    absent: list[str] | None = None,
) -> JudgeVerdict:
    """裁判:输入为盲化候选 + 匿名化意见集 + 匿名缺席席位;泄漏断言在调用前执行(D11)。"""
    spec = deps.prompt("judge")
    all_issues: list[ReviewIssue] = [i for r in reports for i in r.issues]
    anon, issue_id_mapping = anonymize_issues_with_mapping(all_issues)
    verdict_schema = json.dumps(JudgeVerdict.model_json_schema(), ensure_ascii=False)

    user = "\n\n".join(
        [
            _review_ctx_text(ReviewerRole.PLOT, ctx),
            "# 候选稿\n"
            + "\n\n".join(
                f"[{c.candidate_id}]\n" + c.full_text() for c in candidates
            ),
            f"# 评审意见集(匿名,downweighted=true 表示证据定位失败,不得作为阻断依据)\n"
            f"{json.dumps(anon, ensure_ascii=False)}",
            f"# 缺席评审\n{anonymize_absent(absent)}",
        ]
    )
    assert_no_leak(user, DEFAULT_FORBIDDEN)
    req = ModelRequest(
        system=spec.render(verdict_schema=verdict_schema),
        user=user,
        max_tokens=6000,
        temperature=0.2,
    )
    verdict = await CognitiveAgent(deps, "judge", CognitiveTask.JUDGING, JudgeVerdict).run(
        req, chapter_key=ctx.chapter_key
    )
    original_ids = set(issue_id_mapping.values())
    restored_rulings = []
    for ruling in verdict.rulings:
        if ruling.issue_id in issue_id_mapping:
            restored_rulings.append(
                ruling.model_copy(update={"issue_id": issue_id_mapping[ruling.issue_id]})
            )
        elif ruling.issue_id in original_ids:
            # Compatibility for deterministic fixtures recorded before ID blinding.
            restored_rulings.append(ruling)
        else:
            raise StructuredOutputError(
                f"Judge 返回未知匿名 issue_id: {ruling.issue_id}"
            )
    return verdict.model_copy(update={"rulings": restored_rulings})


async def run_concept_judge(
    deps: AgentDeps,
    *,
    kernel: StoryKernel,
    structure: StructureMap,
    after_round: str,
    conflicts: list[Conflict] | None = None,
    payoffs: list[PayoffBeat] | None = None,
    rolling_keys: list[str] | None = None,
) -> ConceptJudgeVerdict:
    """规划对抗裁判:对内核/结构(及可选冲突引擎)给出 PASS/REVISE/REJECT。"""
    spec = deps.prompt("concept_judge")
    verdict_schema = json.dumps(ConceptJudgeVerdict.model_json_schema(), ensure_ascii=False)
    keys = list(rolling_keys or [])
    scoped = scope_structure_for_judge(structure, keys) if keys else structure.model_dump()
    parts = [f"# 裁决节点\n{after_round}"]
    if keys:
        parts.append(f"# 滚动窗口\n{','.join(keys)}")
        parts.append(
            "# 裁决范围\n"
            "冲突与爽点只需覆盖滚动窗口与黄金三章。"
            "结构图中 named_key_status=sketch 的拍是全书草图,不是冲突合同;"
            "不要因为窗口外章节号缺少冲突条目而 REVISE。"
        )
    parts.extend(
        [
            f"# 故事内核\n{json.dumps(kernel.model_dump(), ensure_ascii=False)}",
            f"# 结构图\n{json.dumps(scoped, ensure_ascii=False)}",
        ]
    )
    if conflicts is not None:
        parts.append(
            "# 冲突\n" + json.dumps([item.model_dump() for item in conflicts], ensure_ascii=False)
        )
    if payoffs is not None:
        parts.append(
            "# 爽点\n" + json.dumps([item.model_dump() for item in payoffs], ensure_ascii=False)
        )
    req = ModelRequest(
        system=spec.render(verdict_schema=verdict_schema),
        user="\n\n".join(parts),
        max_tokens=4000,
        temperature=0.2,
    )
    verdict = await CognitiveAgent(
        deps, "concept_judge", CognitiveTask.JUDGING, ConceptJudgeVerdict
    ).run(req)
    return verdict.model_copy(update={"after_round": after_round})


# ---------- Reviser ----------


async def run_reviser(
    deps: AgentDeps,
    draft: DraftCandidate,
    order: RevisionOrder,
    issues: list[ReviewIssue],
    ctx: ChapterContextPackage,
) -> DraftCandidate:
    """最小修改:只处理 RevisionOrder 内问题;越权由 lint 拒绝(调用方执行)。"""
    spec = deps.prompt("reviser")
    selected = [i for i in issues if i.issue_id in order.issue_ids]
    scene_ids = [s.scene_id for s in draft.scenes]
    req = ModelRequest(
        system=spec.render(format_instructions=TWO_PART_FORMAT_INSTRUCTIONS),
        user="\n\n".join(
            [
                f"# 修订工单\n{json.dumps(order.model_dump(), ensure_ascii=False)}",
                f"# 需处理的问题\n"
                f"{json.dumps([i.model_dump() for i in selected], ensure_ascii=False)}",
                "# 原稿\n"
                + "\n\n".join(f"[场景 {s.scene_id}]\n{s.content}" for s in draft.scenes),
                "# 要求\n输出全部场景(未授权场景必须逐字保留原文;锁定片段不得改动)。",
            ]
        ),
        max_tokens=16000,
        temperature=0.4,
    )
    runtime = deps.runtime
    if runtime is None:
        raise RuntimeError("认知任务 runtime 未初始化")
    input_ref, output_ref = deps.version_refs("reviser")
    scenes, meta = await runtime.two_part(
        spec.slot,
        req,
        scene_ids,
        RuntimeCall(
            agent_role="reviser",
            prompt_version=spec.prompt_version,
            project_id=deps.project_id,
            chapter_key=ctx.chapter_key,
            input_ref=input_ref,
            output_ref=output_ref,
        ),
    )
    return draft.model_copy(
        update={
            "scenes": [SceneDraft(scene_id=sid, content=scenes[sid]) for sid in scene_ids],
            "chapter_summary": str(meta.get("chapter_summary", draft.chapter_summary)),
            "deviation_notes": str(meta.get("deviation_notes", "")),
        }
    )


# ---------- Canon Curator ----------


async def run_canon_curator(
    deps: AgentDeps,
    draft: DraftCandidate,
    ctx: ChapterContextPackage,
    canon_version: str,
) -> CanonDelta:
    spec = deps.prompt("canon_curator")
    delta_schema = json.dumps(CanonDelta.model_json_schema(), ensure_ascii=False)
    req = ModelRequest(
        system=spec.render(delta_schema=delta_schema),
        user="\n\n".join(
            [
                f"# 章节键\n{ctx.chapter_key}\n# 基准 canon 版本\n{canon_version}",
                _ctx_text(ctx),
                "# 批准正文\n" + draft.full_text(),
            ]
        ),
        max_tokens=6000,
        temperature=0.1,
    )
    delta = await CognitiveAgent(
        deps, "canon_curator", CognitiveTask.CANON_CURATING, CanonDelta
    ).run(req, chapter_key=ctx.chapter_key)
    return delta.model_copy(
        update={"chapter_key": ctx.chapter_key, "base_canon_version": canon_version}
    )


# ---------- 规划链 ----------


async def run_kernel_planner(deps: AgentDeps, brief: str) -> KernelCandidateSet:
    spec = deps.prompt("kernel_planner")
    schema = json.dumps(KernelCandidateSet.model_json_schema(), ensure_ascii=False)
    req = ModelRequest(system=spec.render(schema=schema), user=brief, max_tokens=8000)
    return await CognitiveAgent(
        deps, "kernel_planner", CognitiveTask.PLANNING, KernelCandidateSet
    ).run(req)


async def run_character_planner(
    deps: AgentDeps, kernel_text: str, brief: str
) -> list[CharacterCard]:
    people = await run_people_planner(deps, kernel_text, brief)
    return people.characters


async def run_people_planner(
    deps: AgentDeps, kernel_text: str, brief: str
) -> _PeoplePlan:
    spec = deps.prompt("character_planner")
    schema = json.dumps(_PeoplePlan.model_json_schema(), ensure_ascii=False)
    req = ModelRequest(
        system=spec.render(schema=schema),
        user=f"# 创作简报\n{brief}\n\n# 已确认故事内核\n{kernel_text}",
        max_tokens=PEOPLE_PLANNER_MAX_TOKENS,
    )
    return await CognitiveAgent(
        deps, "character_planner", CognitiveTask.PLANNING, _PeoplePlan
    ).run(req)


async def run_structure_planner(
    deps: AgentDeps,
    kernel_text: str,
    brief: str,
    *,
    repair_notes: str = "",
    chapter_keys: list[str] | None = None,
) -> StructureMap:
    spec = deps.prompt("structure_planner")
    schema = json.dumps(StructureMap.model_json_schema(), ensure_ascii=False)
    keys = list(chapter_keys or [])
    keys_text = ",".join(keys) if keys else "(未指定)"
    user = f"# 创作简报\n{brief}\n\n# 已确认故事内核\n{kernel_text}"
    if keys:
        user += f"\n\n# 滚动窗口章节键\n{keys_text}"
    if repair_notes.strip():
        user = f"# 修订要求\n{repair_notes.strip()}\n\n{user}"
    req = ModelRequest(
        system=spec.render(schema=schema, chapter_keys=keys_text),
        user=user,
        max_tokens=STRUCTURE_PLANNER_MAX_TOKENS,
    )
    return await CognitiveAgent(
        deps, "structure_planner", CognitiveTask.PLANNING, StructureMap
    ).run(req)


async def run_conflict_planner(
    deps: AgentDeps,
    kernel_text: str,
    characters_text: str,
    chapter_keys: list[str],
    *,
    repair_notes: str = "",
) -> list[Conflict]:
    spec = deps.prompt("conflict_planner")
    schema = json.dumps(_ConflictList.model_json_schema(), ensure_ascii=False)
    keys = ",".join(chapter_keys)
    user = (
        f"# 故事内核\n{kernel_text}\n\n# 角色\n{characters_text}\n\n"
        f"# 计划章节键\n{keys}"
    )
    if repair_notes.strip():
        user = f"# 修订要求\n{repair_notes.strip()}\n\n{user}"
    req = ModelRequest(
        system=spec.render(schema=schema, chapter_keys=keys),
        user=user,
        max_tokens=8000,
    )
    out = await CognitiveAgent(
        deps, "conflict_planner", CognitiveTask.PLANNING, _ConflictList
    ).run(req)
    return out.conflicts


async def run_payoff_planner(
    deps: AgentDeps,
    kernel_text: str,
    conflicts_text: str,
    chapter_keys: list[str],
    *,
    repair_notes: str = "",
) -> list[PayoffBeat]:
    spec = deps.prompt("payoff_planner")
    schema = json.dumps(_PayoffBeatList.model_json_schema(), ensure_ascii=False)
    keys = ",".join(chapter_keys)
    user = (
        f"# 故事内核\n{kernel_text}\n\n# 冲突\n{conflicts_text}\n\n"
        f"# 计划章节键\n{keys}"
    )
    if repair_notes.strip():
        user = f"# 修订要求\n{repair_notes.strip()}\n\n{user}"
    req = ModelRequest(
        system=spec.render(schema=schema, chapter_keys=keys),
        user=user,
        max_tokens=8000,
    )
    out = await CognitiveAgent(
        deps, "payoff_planner", CognitiveTask.PLANNING, _PayoffBeatList
    ).run(req)
    return out.beats


class _PlanOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: PlotUnitCard
    outlines: list[ChapterOutline]
    scene_cards: list[SceneCard]


async def run_outline_planner(
    deps: AgentDeps,
    kernel_text: str,
    characters_text: str,
    volume_id: str,
    unit: PlotUnitCard | None,
    chapters_needed: int,
    *,
    chapter_keys: list[str] | None = None,
    unit_id: str | None = None,
    spoiler_notes: str = "",
    canon_notes: str = "",
) -> tuple[PlotUnitCard, list[ChapterOutline], dict[str, list[SceneCard]]]:
    """单元卡(若未给)+ 章纲若干 + 每章场景卡。"""
    spec = deps.prompt("outline_planner")
    schema = json.dumps(_PlanOut.model_json_schema(), ensure_ascii=False)
    keys = chapter_keys or [f"{volume_id}c{i:03d}" for i in range(1, chapters_needed + 1)]
    pinned_unit = unit_id or (unit.unit_id if unit else "")
    unit_part = (
        f"# 已确认剧情单元\n{json.dumps(unit.model_dump(), ensure_ascii=False)}"
        if unit
        else "# 剧情单元\n(尚未确定,请一并产出)"
    )
    extra_parts = [f"# 计划章节键\n{','.join(keys)}"]
    if pinned_unit:
        extra_parts.append(f"# 指定 unit_id\n{pinned_unit}")
    extra_parts.append(f"# 指定 volume_id\n{volume_id}")
    if spoiler_notes.strip():
        extra_parts.append(f"# 禁释继承\n{spoiler_notes.strip()}")
    if canon_notes.strip():
        extra_parts.append(f"# 正史与临时增量\n{canon_notes.strip()}")
    extra = "\n\n".join(extra_parts)
    req = ModelRequest(
        system=spec.render(schema=schema, volume_id=volume_id, n=str(chapters_needed)),
        user=(
            f"# 故事内核\n{kernel_text}\n\n# 角色\n{characters_text}\n\n{unit_part}\n\n{extra}"
        ),
        max_tokens=OUTLINE_PLANNER_MAX_TOKENS,
    )
    out = await CognitiveAgent(deps, "outline_planner", CognitiveTask.PLANNING, _PlanOut).run(
        req
    )
    outline_keys = {outline.chapter_key for outline in out.outlines}
    unexpected_chapters = sorted(
        {card.chapter_key for card in out.scene_cards} - outline_keys
    )
    if unexpected_chapters:
        raise StructuredOutputError(
            f"场景卡引用了未返回章纲的章节: {unexpected_chapters}"
        )
    by_chapter: dict[str, list[SceneCard]] = {}
    for card in out.scene_cards:
        by_chapter.setdefault(card.chapter_key, []).append(card)
    return out.unit, out.outlines, by_chapter


def new_lineage_id() -> str:
    return f"lin_{uuid.uuid4().hex[:10]}"
