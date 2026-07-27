"""M1.4:状态机转移合法性(含 D15 STALE 规则)。"""

import pytest

from novel_agent.domain.schemas.base import ChapterStatus as S
from novel_agent.workflow.errors import IllegalTransition
from novel_agent.workflow.state_machine import assert_transition


def test_happy_path_chain() -> None:
    chain = [
        S.PLANNED, S.DRAFTING, S.ADVERSARIAL_REVIEW, S.JUDGING,
        S.HUMAN_REVIEW, S.APPROVED, S.CANON_LOCKED, S.EXPORTED,
    ]
    for cur, nxt in zip(chain, chain[1:], strict=False):
        assert_transition(cur, nxt)  # 不抛即合法


def test_revision_and_replan_loops() -> None:
    assert_transition(S.JUDGING, S.NEEDS_REVISION)
    assert_transition(S.NEEDS_REVISION, S.ADVERSARIAL_REVIEW)
    assert_transition(S.JUDGING, S.NEEDS_REPLAN)
    assert_transition(S.NEEDS_REPLAN, S.PLANNED)
    assert_transition(S.HUMAN_REVIEW, S.NEEDS_REVISION)


@pytest.mark.parametrize(
    ("cur", "to"),
    [
        (S.PLANNED, S.ADVERSARIAL_REVIEW),  # 跳过写前守卫
        (S.DRAFTING, S.HUMAN_REVIEW),  # 跳过评审与裁决
        (S.JUDGING, S.APPROVED),  # 裁决不能直接批准
        (S.EXPORTED, S.PLANNED),  # 终态不可回退
        (S.NEEDS_REPLAN, S.DRAFTING),  # 重规划必须回 PLANNED 走守卫
    ],
)
def test_illegal_transitions(cur: S, to: S) -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(cur, to)


def test_stale_rules() -> None:
    # 生产中可置 STALE(D15 级联)
    for cur in (S.DRAFTING, S.JUDGING, S.HUMAN_REVIEW, S.APPROVED):
        assert_transition(cur, S.STALE)
    # 未开始/已锁定不可 STALE
    with pytest.raises(IllegalTransition):
        assert_transition(S.PLANNED, S.STALE)
    with pytest.raises(IllegalTransition):
        assert_transition(S.CANON_LOCKED, S.STALE)
    # STALE 恢复
    assert_transition(S.STALE, S.PLANNED)
    assert_transition(S.STALE, S.DRAFTING)
