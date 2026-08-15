"""M2.5/M2.7 DoD:盲化 round-trip、泄漏断言、lint 各检查项(R4 类拦截、越权拒绝)。"""

import pytest
from test_schemas import SCENE, _issue

from novel_agent.domain.schemas import DraftCandidate, ReviewIssue, RevisionOrder, SceneCard
from novel_agent.lint import lint_draft
from novel_agent.runtime.blinding import (
    DEFAULT_FORBIDDEN,
    BlindingLeak,
    anonymize_absent,
    anonymize_issues,
    assert_no_leak,
    blind_candidates,
    unblind,
)


def _draft(cid: str = "candidate_1", content: str = "茶楼里灯火通明。" * 100) -> DraftCandidate:
    return DraftCandidate.model_validate(
        dict(
            candidate_id=cid,
            chapter_key="v1c001",
            scenes=[{"scene_id": "v1c001_s1", "content": content}],
            chapter_summary="摘要",
        )
    )


def _cards() -> list[SceneCard]:
    return [SceneCard.model_validate({**SCENE, "word_budget": 800})]


def test_blinding_roundtrip_and_anonymize() -> None:
    b, mapping = blind_candidates([("writer_a", _draft("candidate_9"))])
    assert b[0].candidate_id == "candidate_1"
    assert unblind(mapping, "candidate_1") == "writer_a"

    anon = anonymize_issues([ReviewIssue.model_validate(_issue())])
    assert "reviewer_role" not in anon[0]

    with pytest.raises(BlindingLeak):
        assert_no_leak("这份稿子来自 Writer_A", DEFAULT_FORBIDDEN)
    assert_no_leak("干净的裁判输入", DEFAULT_FORBIDDEN)  # 不抛


def test_anonymize_absent_keeps_count_without_role_names() -> None:
    assert anonymize_absent(None) == "无"
    assert anonymize_absent([]) == "无"
    assert anonymize_absent(["reader_advocate"]) == "1 席"
    assert anonymize_absent(["prose", "reader_advocate"]) == "2 席"
    rendered = anonymize_absent(["reader_advocate", "red_team", "writer_a", "writer_b"])
    assert rendered == "4 席"
    for token in ("reader_advocate", "red_team", "writer_a", "writer_b"):
        assert token not in rendered
    assert_no_leak(f"# 缺席评审\n{rendered}", DEFAULT_FORBIDDEN)


def test_lint_clean_draft_passes() -> None:
    clean = _draft(content="夜里茶楼灯火未熄,他数着铜钱。" + "說書聲遠去。" * 60)
    report = lint_draft(clean, _cards(), [])
    assert report.passed, [f.message for f in report.blocking]


def test_lint_engineering_leak_blocks() -> None:
    """R4 类:正文混入 JSON/提示词 → lint 层拦截,不消耗评审。"""
    leaky = _draft(content='他说道:```json\n{"issue_id": 1}\n``` 然后离开。' + "正文。" * 100)
    report = lint_draft(leaky, _cards(), [])
    assert not report.passed
    assert any(f.code == "leak" for f in report.blocking)


def test_lint_boundary_hit() -> None:
    bounded = _draft(content="他掏出了枪支弹药。" + "正文。" * 100)
    report = lint_draft(bounded, _cards(), ["枪支弹药"])
    assert any(f.code == "boundary" for f in report.blocking)


def test_lint_boundary_denial_does_not_trip() -> None:
    """写手常写「我没说X / 我没解释X」,不得当禁写命中。"""
    denied = _draft(content="我没说枪支弹药。我没解释枪支弹药。" + "正文。" * 100)
    report = lint_draft(denied, _cards(), ["枪支弹药"])
    assert all(f.code != "boundary" for f in report.findings)


def test_lint_boundary_denial_still_trips_real_use() -> None:
    mixed = _draft(content="我没解释昨夜的事,他掏出了枪支弹药。" + "正文。" * 80)
    report = lint_draft(mixed, _cards(), ["枪支弹药"])
    assert any(f.code == "boundary" for f in report.blocking)


def test_lint_scene_mismatch() -> None:
    wrong = DraftCandidate.model_validate(
        dict(
            candidate_id="candidate_1",
            chapter_key="v1c001",
            scenes=[{"scene_id": "陌生场景", "content": "x" * 500}],
            chapter_summary="s",
        )
    )
    report = lint_draft(wrong, _cards(), [])
    assert any(f.code == "scene_mismatch" for f in report.blocking)


def test_lint_repetition_nonblocking() -> None:
    rep = _draft(content="他抬起头看向远方的天空。" * 30)
    report = lint_draft(rep, _cards(), [])
    assert any(f.code == "repetition" for f in report.findings)
    assert all(f.code != "repetition" for f in report.blocking)  # 非阻断


def test_revision_authority() -> None:
    original = DraftCandidate.model_validate(
        dict(
            candidate_id="candidate_1",
            chapter_key="v1c001",
            scenes=[
                {"scene_id": "s1", "content": "场景一原文,含锁定句:醒木一响满堂静。"},
                {"scene_id": "s2", "content": "场景二原文。"},
            ],
            chapter_summary="s",
        )
    )
    order = RevisionOrder.model_validate(
        dict(
            verdict_ref="v1", candidate_id="candidate_1", issue_ids=["i1"],
            scope=["s2"], locked_ranges=["醒木一响满堂静"], instructions="只修 s2",
        )
    )
    cards = [
        SceneCard.model_validate({**SCENE, "scene_id": "s1"}),
        SceneCard.model_validate({**SCENE, "scene_id": "s2"}),
    ]

    # 合法修订:只改 s2,锁定句保留
    ok = original.model_copy(deep=True)
    ok.scenes[1].content = "场景二修订后。"
    assert lint_draft(ok, cards, [], original=original, order=order).passed

    # 越权:改了 s1
    bad = original.model_copy(deep=True)
    bad.scenes[0].content = "偷偷改掉场景一,锁定句也没了。"
    report = lint_draft(bad, cards, [], original=original, order=order)
    codes = [f.code for f in report.blocking]
    assert "unauthorized" in codes


def test_revision_scope_chinese_maps_to_scene_ids() -> None:
    from novel_agent.production.factory import resolve_revision_scope

    original = DraftCandidate.model_validate(
        dict(
            candidate_id="candidate_1",
            chapter_key="v1c001",
            scenes=[
                {"scene_id": "v1c001_s1", "content": "场景一原文。"},
                {"scene_id": "v1c001_s2", "content": "场景二原文。"},
            ],
            chapter_summary="s",
        )
    )
    issue = ReviewIssue.model_validate(
        {
            **_issue(),
            "issue_id": "i1",
            "evidence": [{"scene_id": "v1c001_s1", "quote": "场景一原文。"}],
        }
    )
    scope = resolve_revision_scope(
        ["只修开场对白,收紧因果"],
        original,
        issues=[issue],
    )
    assert scope == ["v1c001_s1"]

    order = RevisionOrder.model_validate(
        dict(
            verdict_ref="v1",
            candidate_id="candidate_1",
            issue_ids=["i1"],
            scope=scope,
            instructions="只修开场",
        )
    )
    cards = [
        SceneCard.model_validate({**SCENE, "scene_id": "v1c001_s1"}),
        SceneCard.model_validate({**SCENE, "scene_id": "v1c001_s2"}),
    ]
    revised = original.model_copy(deep=True)
    revised.scenes[0].content = "场景一修订后。"
    assert lint_draft(revised, cards, [], original=original, order=order).passed
