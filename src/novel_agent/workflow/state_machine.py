"""章节状态机:表驱动转移(PRD §8.9 + Spec §6/D15)。

裸状态写入只有本模块调用 PlanningRepo.set_status;
其余代码必须经 transition() 保证合法性。
"""

from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas.base import ChapterStatus
from novel_agent.workflow.errors import IllegalTransition

S = ChapterStatus

ALLOWED: dict[ChapterStatus, frozenset[ChapterStatus]] = {
    S.PLANNED: frozenset({S.DRAFTING}),
    S.DRAFTING: frozenset({S.ADVERSARIAL_REVIEW}),
    S.ADVERSARIAL_REVIEW: frozenset({S.JUDGING, S.HUMAN_REVIEW}),
    # PASS→批次人工审阅(HUMAN_REVIEW);REVISE_LOCAL→NEEDS_REVISION;REPLAN_*→NEEDS_REPLAN
    S.JUDGING: frozenset({S.NEEDS_REVISION, S.NEEDS_REPLAN, S.HUMAN_REVIEW}),
    # 修订稿回 lint→评审;Reviser 非法输出升级人工
    S.NEEDS_REVISION: frozenset({S.ADVERSARIAL_REVIEW, S.HUMAN_REVIEW}),
    # edit-outline 导入后回 PLANNED(M3.3b)
    S.NEEDS_REPLAN: frozenset({S.PLANNED}),
    # 人工:批准 / 退回修订 / 退回重规划 / 失败后重开
    S.HUMAN_REVIEW: frozenset({S.APPROVED, S.NEEDS_REVISION, S.NEEDS_REPLAN, S.PLANNED}),
    S.APPROVED: frozenset({S.CANON_LOCKED}),
    S.CANON_LOCKED: frozenset({S.EXPORTED}),
    S.EXPORTED: frozenset(),
    # STALE 重跑:章纲未变直接重写,或先重规划
    S.STALE: frozenset({S.PLANNED, S.DRAFTING}),
}

# D15:CANON_LOCKED 前的任何生产中状态都可能被级联置 STALE
STALEABLE: frozenset[ChapterStatus] = frozenset(
    {
        S.DRAFTING,
        S.ADVERSARIAL_REVIEW,
        S.JUDGING,
        S.NEEDS_REVISION,
        S.NEEDS_REPLAN,
        S.HUMAN_REVIEW,
        S.APPROVED,
    }
)


def assert_transition(current: ChapterStatus, to: ChapterStatus) -> None:
    if to == S.STALE:
        if current not in STALEABLE:
            raise IllegalTransition(f"{current} 不可置 STALE(已锁定或未开始)")
        return
    if to not in ALLOWED[current]:
        raise IllegalTransition(f"非法转移: {current} → {to}")


def transition(
    repo: PlanningRepo, project_id: int, chapter_key: str, to: ChapterStatus
) -> ChapterStatus:
    """校验并执行状态转移,返回新状态。"""
    current = repo.get_chapter(project_id, chapter_key).status
    assert_transition(current, to)
    if to is S.DRAFTING:
        try:
            repo.get_outline(project_id, chapter_key)
        except Exception as exc:
            raise IllegalTransition("写前守卫拒绝进入 DRAFTING: 缺少有效章纲") from exc
        if not repo.list_scene_cards(project_id, chapter_key):
            raise IllegalTransition("写前守卫拒绝进入 DRAFTING: 缺少场景卡")
    repo.set_status(project_id, chapter_key, to)
    return to


_RESETTABLE = frozenset(
    {
        S.DRAFTING,
        S.ADVERSARIAL_REVIEW,
        S.JUDGING,
        S.NEEDS_REVISION,
        S.NEEDS_REPLAN,
        S.HUMAN_REVIEW,
        S.APPROVED,
    }
)


def reset_to_planned(repo: PlanningRepo, project_id: int, chapter_key: str) -> ChapterStatus:
    """失败工作流后重开:回到 PLANNED,下一轮走写前守卫。"""
    current = repo.get_chapter(project_id, chapter_key).status
    if current is S.PLANNED:
        return current
    if current not in _RESETTABLE:
        raise IllegalTransition(f"{current} 不可重开为 PLANNED")
    repo.set_status(project_id, chapter_key, S.PLANNED)
    return S.PLANNED
