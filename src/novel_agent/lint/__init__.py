"""确定性 Lint(M2.7,零模型成本):评审前预检(N4)。

检查项(Spec §3/§9.3 工程污染门禁 + 评审修订约束):
1. 工程污染:JSON 片段、提示词残留、协议标记、模型自述;
2. 禁写项命中(项目 boundaries);
3. n-gram 重复:章内长片段重复;
4. 场景完整性:正文场景与场景卡集合一致、字数预算粗检;
5. Reviser 越权:修改了 RevisionOrder 范围外的场景 / 破坏锁定片段。
"""

import re
from dataclasses import dataclass, field

from novel_agent.domain.schemas import DraftCandidate, RevisionOrder, SceneCard


@dataclass
class LintFinding:
    code: str  # leak / boundary / repetition / scene_mismatch / word_budget / unauthorized
    message: str
    blocking: bool = True
    scene_id: str = ""


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def blocking(self) -> list[LintFinding]:
        return [f for f in self.findings if f.blocking]

    @property
    def passed(self) -> bool:
        return not self.blocking


# 工程污染模式(PRD §9.3 硬门禁"工程污染")
_LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("json_block", re.compile(r"```json|\{\s*\"[a-z_]+\"\s*:", re.IGNORECASE)),
    ("protocol_marker", re.compile(r"<<<(SCENE|END|META)")),
    (
        "prompt_residue",
        re.compile(r"系统提示词|输出\s*Schema|schema_version|你是一名|作为(一个)?AI"),
    ),
    ("model_self", re.compile(r"(作为语言模型|我无法|抱歉[,,]我不能)")),
    ("review_residue", re.compile(r"(issue_id|reviewer_role|violated_rule|revision_scope)")),
]


def check_engineering_leak(text: str) -> list[LintFinding]:
    out = []
    for name, pat in _LEAK_PATTERNS:
        m = pat.search(text)
        if m:
            snippet = text[max(0, m.start() - 10) : m.end() + 10]
            out.append(LintFinding("leak", f"工程污染({name}): …{snippet}…"))
    return out


_BOUNDARY_DENIAL_RE = re.compile(
    r"(?:我|并)?(?:没(?:有)?|未)(?:说|解释|提过|写过|提到)$"
)


def _boundary_is_denied(text: str, start: int) -> bool:
    """「我没说X / 我没解释X」只是否认,不算正文命中禁写项。"""
    prefix = text[max(0, start - 12) : start]
    return bool(_BOUNDARY_DENIAL_RE.search(prefix))


def check_boundaries(text: str, boundaries: list[str]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for boundary in boundaries:
        if not boundary:
            continue
        start = 0
        hit = False
        while True:
            idx = text.find(boundary, start)
            if idx < 0:
                break
            if not _boundary_is_denied(text, idx):
                hit = True
                break
            start = idx + len(boundary)
        if hit:
            findings.append(LintFinding("boundary", f"命中禁写项: {boundary}"))
    return findings


def check_repetition(text: str, ngram: int = 12, threshold: int = 3) -> list[LintFinding]:
    """长片段重复:去空白后长度 ngram 的窗口出现 ≥threshold 次 → 非阻断提示。"""
    clean = re.sub(r"\s+", "", text)
    seen: dict[str, int] = {}
    for i in range(0, max(0, len(clean) - ngram)):
        seg = clean[i : i + ngram]
        seen[seg] = seen.get(seg, 0) + 1
    repeated = sorted({s for s, n in seen.items() if n >= threshold})
    # 合并互相重叠的片段,只报代表
    out: list[LintFinding] = []
    reported: list[str] = []
    for seg in repeated:
        if any(seg in r or r in seg for r in reported):
            continue
        reported.append(seg)
        out.append(
            LintFinding("repetition", f"片段重复≥{threshold}次: 「{seg}」", blocking=False)
        )
    return out


def check_scenes(draft: DraftCandidate, cards: list[SceneCard]) -> list[LintFinding]:
    out = []
    draft_ids = {s.scene_id for s in draft.scenes}
    card_ids = {c.scene_id for c in cards}
    if draft_ids != card_ids:
        missing = sorted(card_ids - draft_ids)
        extra = sorted(draft_ids - card_ids)
        out.append(
            LintFinding("scene_mismatch", f"场景集不一致: 缺失={missing} 多余={extra}")
        )
    budgets = {c.scene_id: c.word_budget for c in cards}
    for s in draft.scenes:
        budget = budgets.get(s.scene_id)
        if budget and not (0.3 * budget <= len(s.content) <= 3.0 * budget):
            out.append(
                LintFinding(
                    "word_budget",
                    f"场景 {s.scene_id} 字数 {len(s.content)} 偏离预算 {budget} 过远",
                    blocking=False,
                    scene_id=s.scene_id,
                )
            )
    return out


def check_revision_authority(
    revised: DraftCandidate, original: DraftCandidate, order: RevisionOrder
) -> list[LintFinding]:
    """Reviser 越权检测(Spec §7 硬规则):范围外场景必须逐字不变;锁定片段必须保留。"""
    out = []
    orig = {s.scene_id: s.content for s in original.scenes}
    for s in revised.scenes:
        if s.scene_id not in order.scope and orig.get(s.scene_id) != s.content:
            out.append(
                LintFinding(
                    "unauthorized",
                    f"越权修改范围外场景 {s.scene_id}(RevisionOrder.scope={order.scope})",
                    scene_id=s.scene_id,
                )
            )
    full = revised.full_text()
    for locked in order.locked_ranges:
        if locked and locked not in full:
            out.append(LintFinding("unauthorized", f"锁定片段被改动或删除: 「{locked[:30]}…」"))
    return out


def lint_draft(
    draft: DraftCandidate,
    cards: list[SceneCard],
    boundaries: list[str],
    *,
    original: DraftCandidate | None = None,
    order: RevisionOrder | None = None,
) -> LintReport:
    """N4 入口:组合全部确定性检查。"""
    text = draft.full_text()
    findings = [
        *check_engineering_leak(text),
        *check_boundaries(text, boundaries),
        *check_repetition(text),
        *check_scenes(draft, cards),
    ]
    if original is not None and order is not None:
        findings.extend(check_revision_authority(draft, original, order))
    return LintReport(findings)
