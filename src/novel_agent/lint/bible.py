"""Story Bible 确定性 lint:黄金三章、爽点间距、孤儿冲突、空冲突、关系证据。"""

from __future__ import annotations

from collections.abc import Sequence

from novel_agent.domain.schemas import (
    ChapterOutline,
    Conflict,
    GoldenThreeChapter,
    PayoffBeat,
    PayoffScale,
    RelationshipProposal,
    StoryKernel,
    StructureMap,
)
from novel_agent.lint import LintFinding, LintReport

_LORE_MARKERS = ("世界观", "历史沿革", "地理志", "设定介绍", "传说考据")
_LIVE_MARKERS = ("主角", "危机", "问题", "冲突", "当场", "眼前", "承诺")
_NAME_LEADINS = ("名叫", "名为", "叫做", "叫作", "化妆师")
_NAME_BOUNDARIES = set("的是在为与和及把被将从向对给了着用要想能会去来到得也还就都且但")
_CJK_START = 0x4E00
_CJK_END = 0x9FFF


def _empty(text: str) -> bool:
    return not text.strip()


def _is_cjk(ch: str) -> bool:
    return _CJK_START <= ord(ch) <= _CJK_END


def _take_name(rest: str) -> str | None:
    chars: list[str] = []
    for ch in rest:
        if not _is_cjk(ch):
            break
        chars.append(ch)
        if len(chars) >= 3:
            break
    if len(chars) < 2:
        return None
    if len(chars) == 3:
        nxt = rest[3] if len(rest) > 3 else ""
        if nxt and _is_cjk(nxt) and nxt not in _NAME_BOUNDARIES:
            chars = chars[:2]
    name = "".join(chars)
    if name[-1] in _NAME_BOUNDARIES:
        name = name[:-1]
    if len(name) < 2:
        return None
    return name


def live_names_from_kernel(kernel: StoryKernel) -> list[str]:
    """从已确认内核的 logline/premise 抽出活人名,供黄金三章 lint 识别姓名指代。"""
    blob = f"{kernel.logline}{kernel.premise}"
    found: list[str] = []
    seen: set[str] = set()
    for leadin in _NAME_LEADINS:
        start = 0
        while True:
            pos = blob.find(leadin, start)
            if pos < 0:
                break
            start = pos + len(leadin)
            name = _take_name(blob[start:])
            if name and name not in seen:
                seen.add(name)
                found.append(name)
    return found


def lint_golden_three(
    golden: Sequence[GoldenThreeChapter],
    live_names: Sequence[str] = (),
) -> list[LintFinding]:
    if len(golden) != 3:
        return [LintFinding("golden_three", f"黄金三章必须恰好 3 章,实际 {len(golden)}")]
    first = golden[0]
    text = f"{first.promise}{first.escalation}{first.payoff_or_hook}"
    has_live = any(marker in text for marker in _LIVE_MARKERS) or any(
        name and name in text for name in live_names
    )
    has_lore = any(marker in text for marker in _LORE_MARKERS)
    if has_lore and not has_live:
        return [LintFinding("golden_three", "黄金三章第1章是设定堆砌,缺少主角与当场问题")]
    if not has_live:
        return [LintFinding("golden_three", "黄金三章第1章缺少主角或当场问题")]
    return []


def lint_payoff_spacing(beats: Sequence[PayoffBeat]) -> list[LintFinding]:
    ordered = sorted(beats, key=lambda beat: (beat.order_index, beat.beat_id))
    streak = 0
    for beat in ordered:
        if beat.scale is PayoffScale.LARGE and _empty(beat.pressure_before):
            streak += 1
            if streak >= 3:
                return [
                    LintFinding(
                        "payoff_spacing",
                        "连续三个 large 爽点的 pressure_before 为空(空白视为空)",
                    )
                ]
        else:
            streak = 0
    return []


def lint_empty_conflicts(
    conflicts: Sequence[Conflict], rolling_keys: Sequence[str] | None
) -> list[LintFinding]:
    if rolling_keys is None or conflicts:
        return []
    return [LintFinding("empty_conflict", "冲突系统为空,滚动窗口没有可兑现的冲突")]


def lint_orphan_conflicts(
    conflicts: Sequence[Conflict], rolling_keys: Sequence[str]
) -> list[LintFinding]:
    keys = set(rolling_keys)
    findings: list[LintFinding] = []
    for conflict in conflicts:
        payoff = conflict.payoff_chapter_key.strip()
        if not payoff:
            findings.append(
                LintFinding(
                    "orphan_conflict",
                    f"冲突 {conflict.conflict_id} 缺少 payoff_chapter_key",
                )
            )
        elif payoff not in keys:
            window = list(rolling_keys)
            findings.append(
                LintFinding(
                    "orphan_conflict",
                    f"冲突 {conflict.conflict_id} 的 payoff {payoff} 不在滚动窗口 {window}",
                )
            )
    return findings


def lint_relationship_evidence(proposals: Sequence[RelationshipProposal]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for proposal in proposals:
        if _empty(proposal.evidence):
            parties = "-".join(proposal.parties)
            findings.append(
                LintFinding("relationship_evidence", f"关系提案 {parties} 缺少可追溯证据")
            )
    return findings


def lint_outline_citations(
    cited_conflict_ids: Sequence[str], cited_beat_ids: Sequence[str], chapter_key: str
) -> list[LintFinding]:
    if not cited_conflict_ids and not cited_beat_ids:
        return [
            LintFinding(
                "outline_citation",
                f"章纲 {chapter_key} 未引用任何冲突或爽点",
            )
        ]
    return []


def collect_remaining_forbidden(outlines: Sequence[ChapterOutline]) -> list[str]:
    forbidden: list[str] = []
    allowed: set[str] = set()
    seen: set[str] = set()
    for outline in outlines:
        for item in outline.reveal_allowed:
            if item:
                allowed.add(item)
        for item in outline.reveal_forbidden:
            if item and item not in seen:
                seen.add(item)
                forbidden.append(item)
    return [item for item in forbidden if item not in allowed]


def lint_spoiler_visibility(
    previous: Sequence[ChapterOutline], new_outlines: Sequence[ChapterOutline]
) -> list[LintFinding]:
    remaining = collect_remaining_forbidden(previous)
    findings: list[LintFinding] = []
    for outline in new_outlines:
        allowed = set(outline.reveal_allowed)
        blob = f"{outline.core_event}{outline.title}{outline.exit_hook}{outline.key_choice}"
        for secret in remaining:
            if secret in allowed:
                continue
            if secret not in outline.reveal_forbidden:
                findings.append(
                    LintFinding(
                        "spoiler",
                        f"章纲 {outline.chapter_key} 未继承禁释 {secret}",
                    )
                )
            if secret in blob:
                findings.append(
                    LintFinding(
                        "spoiler",
                        f"章纲 {outline.chapter_key} 泄露仍被禁止的信息 {secret}",
                    )
                )
    return findings


def lint_bible(
    *,
    structure: StructureMap | None = None,
    conflicts: Sequence[Conflict] = (),
    payoff_beats: Sequence[PayoffBeat] = (),
    rolling_keys: Sequence[str] | None = None,
    relationship_proposals: Sequence[RelationshipProposal] = (),
    outline_citations: Sequence[tuple[str, Sequence[str], Sequence[str]]] = (),
    previous_outlines: Sequence[ChapterOutline] = (),
    new_outlines: Sequence[ChapterOutline] = (),
    live_names: Sequence[str] = (),
) -> LintReport:
    findings: list[LintFinding] = []
    if structure is not None:
        findings.extend(lint_golden_three(structure.golden_three, live_names))
    findings.extend(lint_payoff_spacing(payoff_beats))
    findings.extend(lint_relationship_evidence(relationship_proposals))
    findings.extend(lint_empty_conflicts(conflicts, rolling_keys))
    if rolling_keys is not None:
        findings.extend(lint_orphan_conflicts(conflicts, rolling_keys))
    for chapter_key, conflict_ids, beat_ids in outline_citations:
        findings.extend(lint_outline_citations(conflict_ids, beat_ids, chapter_key))
    if previous_outlines or new_outlines:
        findings.extend(lint_spoiler_visibility(previous_outlines, new_outlines))
    return LintReport(findings)
