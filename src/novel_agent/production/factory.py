"""隔夜工厂门禁:短稿/拒稿信剔除、唯一干净候选锁定、Judge 空包回退、修订范围落到真实 scene_id。

不改 Writer / Judge 提示词,只在循环侧拦死现场会停锁的形态。
"""

from __future__ import annotations

import re

from novel_agent.domain.schemas import (
    DraftCandidate,
    HardGate,
    JudgeVerdict,
    ReviewIssue,
    SceneCard,
    VerdictType,
)
from novel_agent.lint import check_boundaries, check_engineering_leak

MIN_DRAFT_PROSE_CHARS = 800
_PLACEHOLDER_PROSE = frozenset(
    {
        "（正文）",
        "(正文)",
        "正文",
        "...",
        "……",
        "xxx",
        "XXX",
        "TODO",
        "TBD",
    }
)
_PLACEHOLDER_BODY_RE = re.compile(r"（正文）|\(正文\)|【正文】")
_PROTOCOL_MARK_RE = re.compile(
    r"```(?:markdown|text|md)?\s*|<<<SCENE:[^>\n]+>>>|<<<END>>>|<<<META>>>|```",
    re.IGNORECASE,
)
# 操作员拒稿口吻。禁止单凭「场景卡」二字,以免误杀《穿回去当导演》正文。
_META_REFUSAL_RE = re.compile(
    r"(?:"
    r"仍未收到本场景|未收到本场景|尚未收到本场景|我当前仍未收到"
    r"|请将以下内容补齐|补齐后重新下发"
    r"|重新下发[：:]"
    r"|场景卡字段|上下文包字段"
    r"|请(?:提供|补齐|补充).{0,24}(?:场景卡|上下文包|硬约束)"
    r")"
)
_EMPTY_PACKET_MARKERS = (
    "用户未提供",
    "未提供评审",
    "评审材料",
    "未提供候选",
    "缺少评审",
    "没有评审材料",
    "强制 HUMAN_REVIEW",
    "未提供任何",
    "输入内容为空",
    "未检测到任何场景",
    "未提供实际场景",
    "未提供实际裁决",
    "JSON Schema",
    "Schema 定义",
    "Schema定义",
    "$defs",
    "缺少必需字段",
    "缺少必需的 verdict",
)
_EMPTY_PACKET_SOFT_GATES = frozenset({"source_risk", "info_violation"})
_SCENE_ID_IN_TEXT = re.compile(r"(?:v\d+c\d+_s\d+|[A-Za-z]+_s\d+|s\d+)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
# 硬门禁风格泄漏:真名/穿越/耳鸣/实习生/左眼花/左眼薄雾/反噬。禁止单凭「笔记」或裸「左眼」。
_HARD_GATE_LEAK_RE = re.compile(r"穿越|耳鸣|真名|实习生|左眼花|左眼薄雾|反噬")


def prose_char_count(text: str) -> int:
    return len(_WS_RE.sub("", text or ""))


def _core_prose(text: str) -> str:
    """剥掉 SCENE/END 脚手架、围栏和「（正文）」后再计字。"""
    stripped = _PROTOCOL_MARK_RE.sub(" ", text or "")
    return _PLACEHOLDER_BODY_RE.sub(" ", stripped)


def _looks_like_meta_refusal(text: str) -> bool:
    """要操作员补场景卡/上下文包,而不是在写正文。"""
    return bool(_META_REFUSAL_RE.search(text or ""))


def _is_mostly_scaffold(text: str) -> bool:
    placeholders = _PLACEHOLDER_BODY_RE.findall(text)
    scene_marks = len(re.findall(r"<<<SCENE:", text, re.IGNORECASE))
    if len(placeholders) >= 3:
        return True
    if scene_marks >= 2 and placeholders:
        return True
    orig_n = prose_char_count(text)
    if orig_n == 0:
        return True
    core_n = prose_char_count(_core_prose(text))
    return bool((scene_marks or placeholders) and core_n < orig_n * 0.5)


def is_usable_draft(text: str, *, min_chars: int = MIN_DRAFT_PROSE_CHARS) -> bool:
    """真实正文:不是拒稿信/脚手架,剥协议标记后达到最低字数。"""
    cleaned = (text or "").strip()
    if not cleaned or cleaned in _PLACEHOLDER_PROSE:
        return False
    if _looks_like_meta_refusal(cleaned):
        return False
    if _is_mostly_scaffold(cleaned):
        return False
    core = _core_prose(cleaned).strip()
    if not core or core in _PLACEHOLDER_PROSE:
        return False
    return prose_char_count(core) >= min_chars


def is_empty_packet_reason(text: str) -> bool:
    """Judge 把空包 / schema echo 说成「没给材料」或强制 HUMAN_REVIEW。"""
    blob = text or ""
    return any(marker in blob for marker in _EMPTY_PACKET_MARKERS)


def is_empty_packet_verdict(verdict: JudgeVerdict) -> bool:
    if not is_empty_packet_reason(verdict.reasoning_summary):
        if verdict.hard_gate_failures:
            return False
        if verdict.verdict is not VerdictType.HUMAN_REVIEW:
            return False
        return not verdict.rulings or all(not item.accepted for item in verdict.rulings)
    real_gates = [g for g in verdict.hard_gate_failures if str(g) not in _EMPTY_PACKET_SOFT_GATES]
    return not real_gates


def catalog_scene_ids(
    draft: DraftCandidate,
    cards: list[SceneCard] | None = None,
    issues: list[ReviewIssue] | None = None,
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(sid: str) -> None:
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)

    for scene in draft.scenes:
        add(scene.scene_id)
    for card in cards or []:
        add(card.scene_id)
    for issue in issues or []:
        for ev in issue.evidence:
            add(ev.scene_id)
    return ids


def resolve_revision_scope(
    revision_scope: list[str],
    draft: DraftCandidate,
    cards: list[SceneCard] | None = None,
    issues: list[ReviewIssue] | None = None,
) -> list[str]:
    """把 Judge 的中文 revision_scope 映射到真实 scene_id。

    解析不出任何 id 时,用已采纳 issue 的 scene_id;再没有则用稿件全部场景。
    禁止把中文描述当 membership 去卡 lint。
    """
    catalog = catalog_scene_ids(draft, cards, issues)
    catalog_set = set(catalog)
    parsed: list[str] = []
    seen: set[str] = set()

    def add(sid: str) -> None:
        if sid in catalog_set and sid not in seen:
            seen.add(sid)
            parsed.append(sid)

    for item in revision_scope:
        token = (item or "").strip()
        if not token:
            continue
        if token in catalog_set:
            add(token)
            continue
        for match in _SCENE_ID_IN_TEXT.finditer(token):
            add(match.group(0))
        for sid in catalog:
            if sid and sid in token:
                add(sid)

    if parsed:
        return parsed
    from_issues: list[str] = []
    for issue in issues or []:
        for ev in issue.evidence:
            if ev.scene_id and ev.scene_id not in from_issues:
                from_issues.append(ev.scene_id)
    return from_issues or [scene.scene_id for scene in draft.scenes]


def has_hard_gate_leak(text: str) -> bool:
    """正文里的真名/穿越/耳鸣/实习生类硬门禁泄漏。"""
    return bool(_HARD_GATE_LEAK_RE.search(text or ""))


def is_lockable_draft(
    text: str,
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> bool:
    """可继续锁定:可用正文,且不踩禁写项/工程污染/硬门禁泄漏。"""
    if not is_usable_draft(text):
        return False
    if check_boundaries(text, boundaries):
        return False
    if check_engineering_leak(text):
        return False
    if has_hard_gate_leak(text):
        return False
    names = [n for n in (required_names or []) if n]
    return not names or any(n in (text or "") for n in names)


def _lockable_candidates(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> list[DraftCandidate]:
    return [
        draft
        for draft in candidates
        if is_lockable_draft(draft.full_text(), boundaries, required_names)
    ]


def pick_lockable_candidate(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> DraftCandidate | None:
    """空包回退:选更长的合规正文,排除占位短稿与真硬门禁命中。"""
    viable = _lockable_candidates(candidates, boundaries, required_names)
    if not viable:
        return None
    return max(viable, key=lambda item: prose_char_count(item.full_text()))


def pick_sole_lockable_candidate(
    candidates: list[DraftCandidate],
    boundaries: list[str],
    required_names: list[str] | None = None,
) -> DraftCandidate | None:
    """真 REPLAN 回退:恰好一稿可锁才选用,含仅一稿且 on-brief 的情形。"""
    viable = _lockable_candidates(candidates, boundaries, required_names)
    if len(viable) != 1:
        return None
    return viable[0]


def synthesize_pass_verdict(
    candidate: DraftCandidate,
    *,
    reason: str = "Judge 空包或 schema echo 后回退:选用更长的合规候选,继续锁定。",
) -> JudgeVerdict:
    return JudgeVerdict(
        verdict=VerdictType.PASS,
        selected_candidate=candidate.candidate_id,
        hard_gate_failures=[],
        rulings=[],
        reasoning_summary=reason,
    )


_FORBIDDEN_REAL_NAME_RE = re.compile(r"章子怡|赵薇|周迅|徐静蕾|范冰冰|李冰冰|刘亦菲")


def strip_allowed_name_boundaries(
    verdict: JudgeVerdict,
    issues: list[ReviewIssue],
    allowed_names: list[str] | None = None,
) -> JudgeVerdict:
    """角色卡名被裁成 content_boundary 真名时剔除该门禁,不放过章子怡/徐静蕾。"""
    allowed = [n for n in (allowed_names or []) if n]
    if not allowed or HardGate.CONTENT_BOUNDARY not in verdict.hard_gate_failures:
        return verdict
    cb_issues = [issue for issue in issues if issue.hard_gate == HardGate.CONTENT_BOUNDARY]
    blob = " ".join(
        [verdict.reasoning_summary]
        + [issue.claim for issue in cb_issues]
        + [ruling.reason for ruling in verdict.rulings]
    )
    if _FORBIDDEN_REAL_NAME_RE.search(blob):
        return verdict
    if not any(name in blob for name in allowed):
        return verdict
    gates = [gate for gate in verdict.hard_gate_failures if gate != HardGate.CONTENT_BOUNDARY]
    drop_ids = {issue.issue_id for issue in cb_issues}
    rulings = [
        ruling
        for ruling in verdict.rulings
        if not (ruling.accepted and ruling.issue_id in drop_ids)
    ]
    return verdict.model_copy(update={"hard_gate_failures": gates, "rulings": rulings})
