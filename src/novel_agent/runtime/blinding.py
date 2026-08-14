"""盲化/匿名化(M2.5,D11):代码层强制,不依赖提示词自觉。

- 候选稿:writer 身份 → candidate_N;映射只进 NodeRun 快照,解盲由代码执行。
- 评审报告:剥离 reviewer_role 等身份字段后才可进入 Judge 输入。
- 缺席评审:只把席位数交给 Judge;真实角色名留在 NodeRun / 调用方。
- assert_no_leak:对将要进入 Judge 的文本做泄漏断言。
"""

from novel_agent.domain.schemas import DraftCandidate, ReviewIssue


class BlindingLeak(Exception):
    pass


def blind_candidates(
    writer_drafts: list[tuple[str, DraftCandidate]],
) -> tuple[list[DraftCandidate], dict[str, str]]:
    """[(writer 标识, 稿件)] → (盲化稿件列表, {candidate_id: writer 标识})。

    映射由调用方存入 N3 NodeRun 快照;绝不进任何 Agent 上下文。
    """
    blinded: list[DraftCandidate] = []
    mapping: dict[str, str] = {}
    for i, (writer_id, draft) in enumerate(writer_drafts, start=1):
        cid = f"candidate_{i}"
        blinded.append(draft.model_copy(update={"candidate_id": cid}))
        mapping[cid] = writer_id
    return blinded, mapping


def unblind(mapping: dict[str, str], candidate_id: str) -> str:
    """Judge 选定后由代码解盲。"""
    return mapping[candidate_id]


def anonymize_issues(issues: list[ReviewIssue]) -> list[dict]:
    """剥离评审身份字段(PRD §9.4 规则2)。产物为进入 Judge 的意见集。"""
    anonymized, _ = anonymize_issues_with_mapping(issues)
    return anonymized


def anonymize_issues_with_mapping(
    issues: list[ReviewIssue],
) -> tuple[list[dict], dict[str, str]]:
    """Blind reviewer identity in fields and IDs, retaining code-only reconciliation."""
    out = []
    mapping: dict[str, str] = {}
    for index, issue in enumerate(issues, start=1):
        anonymous_id = f"issue_{index}"
        d = issue.model_dump()
        d.pop("reviewer_role", None)
        d["issue_id"] = anonymous_id
        out.append(d)
        mapping[anonymous_id] = issue.issue_id
    return out, mapping


def anonymize_absent(absent: list[str] | None) -> str:
    """Judge 只看到缺席席位数;角色名不得进入提示词。"""
    if not absent:
        return "无"
    return f"{len(absent)} 席"


def assert_no_leak(text: str, forbidden_tokens: list[str]) -> None:
    """断言 Judge 输入不含 writer/模型/评审身份标识。"""
    lowered = text.lower()
    hits = [t for t in forbidden_tokens if t and t.lower() in lowered]
    if hits:
        raise BlindingLeak(f"Judge 输入泄漏身份标识: {hits}")


# Judge 输入默认必须屏蔽的通用标识(角色名与常见模型名前缀)
DEFAULT_FORBIDDEN = [
    "writer_a",
    "writer_b",
    "reviewer_role",
    "reader_advocate",
    "red_team",
    "claude-",
    "gpt-",
    "deepseek",
    "qwen",
    "glm-",
    "kimi",
    "mock-model",
]
