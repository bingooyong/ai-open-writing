"""Story Bible 确定性 lint:黄金三章、爽点间距、孤儿冲突、关系证据。"""

from __future__ import annotations

from collections.abc import Sequence

from novel_agent.domain.schemas import (
    Conflict,
    GoldenThreeChapter,
    PayoffBeat,
    PayoffScale,
    RelationshipProposal,
    StructureMap,
)
from novel_agent.lint import LintFinding, LintReport

_LORE_MARKERS = ("世界观", "历史沿革", "地理志", "设定介绍", "传说考据")
_LIVE_MARKERS = ("主角", "危机", "问题", "冲突", "当场", "眼前", "承诺")


def _empty(text: str) -> bool:
    return not text.strip()


def lint_golden_three(golden: Sequence[GoldenThreeChapter]) -> list[LintFinding]:
    if len(golden) != 3:
        return [LintFinding("golden_three", f"黄金三章必须恰好 3 章,实际 {len(golden)}")]
    first = golden[0]
    text = f"{first.promise}{first.escalation}{first.payoff_or_hook}"
    has_live = any(marker in text for marker in _LIVE_MARKERS)
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


def lint_bible(
    *,
    structure: StructureMap | None = None,
    conflicts: Sequence[Conflict] = (),
    payoff_beats: Sequence[PayoffBeat] = (),
    rolling_keys: Sequence[str] | None = None,
    relationship_proposals: Sequence[RelationshipProposal] = (),
    outline_citations: Sequence[tuple[str, Sequence[str], Sequence[str]]] = (),
) -> LintReport:
    findings: list[LintFinding] = []
    if structure is not None:
        findings.extend(lint_golden_three(structure.golden_three))
    findings.extend(lint_payoff_spacing(payoff_beats))
    findings.extend(lint_relationship_evidence(relationship_proposals))
    if rolling_keys is not None:
        findings.extend(lint_orphan_conflicts(conflicts, rolling_keys))
    for chapter_key, conflict_ids, beat_ids in outline_citations:
        findings.extend(lint_outline_citations(conflict_ids, beat_ids, chapter_key))
    return LintReport(findings)
