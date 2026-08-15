"""隔夜工厂门禁:短稿/拒稿信剔除、Judge 空包回退、修订范围落到真实 scene_id。

不改 Writer / Judge 提示词,只在循环侧拦死现场会停锁的形态。
"""

from __future__ import annotations

import re

from novel_agent.domain.schemas import (
    DraftCandidate,
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
)
_SCENE_ID_IN_TEXT = re.compile(r"(?:v\d+c\d+_s\d+|[A-Za-z]+_s\d+|s\d+)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


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
    if verdict.hard_gate_failures:
        return False
    if is_empty_packet_reason(verdict.reasoning_summary):
        return True
    if verdict.verdict is not VerdictType.HUMAN_REVIEW:
        return False
    return not verdict.rulings or all(not item.accepted for item in verdict.rulings)


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


def pick_lockable_candidate(
    candidates: list[DraftCandidate],
    boundaries: list[str],
) -> DraftCandidate | None:
    """空包回退:选更长的合规正文,排除占位短稿与真硬门禁命中。"""
    viable: list[DraftCandidate] = []
    for draft in candidates:
        text = draft.full_text()
        if not is_usable_draft(text):
            continue
        if check_boundaries(text, boundaries):
            continue
        if check_engineering_leak(text):
            continue
        viable.append(draft)
    if not viable:
        return None
    return max(viable, key=lambda item: prose_char_count(item.full_text()))


def synthesize_pass_verdict(candidate: DraftCandidate) -> JudgeVerdict:
    return JudgeVerdict(
        verdict=VerdictType.PASS,
        selected_candidate=candidate.candidate_id,
        hard_gate_failures=[],
        rulings=[],
        reasoning_summary="Judge 空包或 schema echo 后回退:选用更长的合规候选,继续锁定。",
    )
