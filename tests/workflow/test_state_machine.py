"""M1.4:状态机转移合法性(含 D15 STALE 规则)。"""

import pytest
from test_schemas import OUTLINE, SCENE

from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import PlanningRepo
from novel_agent.domain.schemas import ChapterOutline, SceneCard
from novel_agent.domain.schemas.base import ChapterStatus as S
from novel_agent.workflow.errors import IllegalTransition
from novel_agent.workflow.state_machine import assert_transition, transition


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


@pytest.mark.parametrize("has_outline,has_scene_cards", [(False, True), (True, False)])
def test_drafting_transition_rejects_missing_write_plan(
    tmp_path, has_outline: bool, has_scene_cards: bool
) -> None:
    """N1 must prevent drafting when either the chapter outline or scene cards are absent."""
    engine = build_engine(tmp_path / "guard.db")
    create_all(engine)
    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        project_id = repo.create_project("写前守卫").id
        outline = ChapterOutline.model_validate(OUTLINE)
        repo.create_chapter(project_id, outline, order_index=1)
        if not has_outline:
            repo.get_chapter(project_id, "v1c001").outline = {}
        if has_scene_cards:
            repo.save_scene_cards(project_id, "v1c001", [SceneCard.model_validate(SCENE)])

        with pytest.raises(IllegalTransition, match="写前守卫"):
            transition(repo, project_id, "v1c001", S.DRAFTING)
        assert repo.get_chapter(project_id, "v1c001").status is S.PLANNED


def test_drafting_transition_accepts_valid_outline_and_scene_cards(tmp_path) -> None:
    engine = build_engine(tmp_path / "guard-valid.db")
    create_all(engine)
    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        project_id = repo.create_project("写前守卫").id
        repo.create_chapter(project_id, ChapterOutline.model_validate(OUTLINE), order_index=1)
        repo.save_scene_cards(project_id, "v1c001", [SceneCard.model_validate(SCENE)])

        assert transition(repo, project_id, "v1c001", S.DRAFTING) is S.DRAFTING
