"""M2.4/M2.6 契约测试:mock 下各 Agent IO Schema 正确;评审失败策略;裁判泄漏断言。"""

import json

import pytest
from sqlmodel import Session
from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

from novel_agent.config import Settings
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.schemas import (
    ChapterContextPackage,
    CharacterCard,
    DraftCandidate,
    ReviewerRole,
    ReviewIssue,
    RevisionOrder,
)
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.runtime.agents import (
    AgentDeps,
    _evidence_locates,
    run_canon_curator,
    run_judge,
    run_kernel_planner,
    run_review_round,
    run_reviewer,
    run_reviser,
    run_writer,
)


def _ctx() -> ChapterContextPackage:
    return ChapterContextPackage.model_validate(
        dict(
            chapter_key="v1c001",
            canon_version="canon_v0",
            task_brief="写第一章",
            outline=OUTLINE,
            scene_cards=[SCENE, {**SCENE, "scene_id": "v1c001_s2"}],
            kernel_summary="说书人故事成真",
            volume_summary="第一卷",
            unit_card=UNIT,
            characters=[CHARACTER],
            boundaries=["禁写项X"],
        )
    )


TWO_PART = """<<<SCENE:v1c001_s1>>>
茶楼里灯火通明,说书人一拍醒木,满堂皆静。
<<<END>>>
<<<SCENE:v1c001_s2>>>
散场后他数着铜钱,忽听巷口马蹄声急。
<<<END>>>
<<<META>>>
{"chapter_summary": "说书人卷入失火案", "deviation_notes": ""}"""


def _review_json(good_quote: str) -> str:
    issues = [
        dict(  # 证据可定位 → 保留
            issue_id="x_1", reviewer_role="plot", claim="转折依赖巧合",
            evidence=[{"scene_id": "v1c001_s1", "quote": good_quote}],
            violated_rule="因果规则", severity="P1",
            failure_consequence="读者出戏", recommended_rollback_level="scene_card",
            confidence=0.8,
        ),
        dict(  # 引文杜撰 → 降权
            issue_id="x_2", reviewer_role="plot", claim="凭空断言",
            evidence=[{"scene_id": "v1c001_s1", "quote": "正文里根本没有这句话"}],
            violated_rule="任意", severity="P0", hard_gate="canon_conflict",
            failure_consequence="任意", recommended_rollback_level="prose",
            confidence=0.9,
        ),
    ]
    return json.dumps(
        {"reviewer_role": "plot", "candidate_id": "candidate_1", "issues": issues,
         "overall_note": "ok"},
        ensure_ascii=False,
    )


VERDICT_JSON = json.dumps(
    dict(
        verdict="REVISE_LOCAL", selected_candidate="candidate_1",
        rulings=[{"issue_id": "plot_1", "accepted": True, "reason": "证据成立"}],
        revision_scope=["v1c001_s1"], locked_strengths=["开场画面感"],
        reasoning_summary="仅一处局部问题",
    ),
    ensure_ascii=False,
)


@pytest.fixture()
def deps(tmp_path):
    engine = build_engine(tmp_path / "t.db")
    create_all(engine)
    session = Session(engine)
    mock = MockProvider()
    mock.register("writer_a", lambda req: TWO_PART)
    mock.register("reviser", lambda req: TWO_PART)
    for role in ("red_team", "plot", "character", "continuity", "prose"):
        mock.register(role, lambda req: _review_json("茶楼里灯火通明"))
    mock.register("judge", lambda req: VERDICT_JSON)
    mock.register(
        "canon_curator",
        lambda req: json.dumps(
            {"chapter_key": "v1c001", "base_canon_version": "canon_v0"}, ensure_ascii=False
        ),
    )
    mock.register(
        "kernel_planner",
        lambda req: json.dumps(
            {"candidates": [KERNEL, {**KERNEL, "logline": "另一个方向"}],
             "differentiation_notes": "题材切入不同"},
            ensure_ascii=False,
        ),
    )
    gw = ModelGateway(Settings(_env_file=None), session, {"mock": mock})
    d = AgentDeps(gateway=gw, project_id=1)
    d.mock = mock  # type: ignore[attr-defined]
    yield d
    session.close()


async def test_writer_two_part_assembly(deps) -> None:
    draft = await run_writer(deps, _ctx(), writer_id="writer_a")
    assert [s.scene_id for s in draft.scenes] == ["v1c001_s1", "v1c001_s2"]
    assert draft.chapter_summary == "说书人卷入失火案"


async def test_reviewer_downweights_unlocatable_evidence(deps) -> None:
    draft = await run_writer(deps, _ctx(), writer_id="writer_a")
    report = await run_reviewer(deps, ReviewerRole.PLOT, draft, _ctx())
    assert report.reviewer_role == ReviewerRole.PLOT
    by_flag = {i.downweighted for i in report.issues}
    assert by_flag == {True, False}  # 一条定位成功保留,一条杜撰引文降权
    assert all(i.issue_id.startswith("plot_") for i in report.issues)


def test_evidence_location_allows_small_normalized_quote_drift() -> None:
    draft = DraftCandidate.model_validate(
        {
            "candidate_id": "candidate_1",
            "chapter_key": "v1c001",
            "chapter_summary": "说书人开场",
            "scenes": [
                {
                    "scene_id": "v1c001_s1",
                    "content": "茶楼里灯火通明，说书人一拍醒木，满堂皆静。",
                }
            ],
        }
    )
    issue = ReviewIssue.model_validate(
        {
            "issue_id": "plot_1",
            "reviewer_role": "plot",
            "claim": "开场依赖静态描写",
            "evidence": [
                {
                    "scene_id": "v1c001_s1",
                    "quote": "茶楼灯火通明；说书人一拍醒木",
                }
            ],
            "violated_rule": "推进规则",
            "severity": "P2",
            "failure_consequence": "推进偏慢",
            "recommended_rollback_level": "prose",
            "confidence": 0.8,
        }
    )

    assert _evidence_locates(issue, draft) is True

    drifted = issue.model_copy(
        update={
            "evidence": [
                issue.evidence[0].model_copy(update={"quote": "说书人抬手醒木满堂皆静"})
            ]
        }
    )
    assert _evidence_locates(drifted, draft) is True


async def test_review_round_absence_policy(deps) -> None:
    draft = await run_writer(deps, _ctx(), writer_id="writer_a")

    # prose 失败 → 缺席但不阻断
    deps.mock.register("prose", lambda req: (_ for _ in ()).throw(RuntimeError("挂了")))
    result = await run_review_round(deps, draft, _ctx())
    assert result.absent == ["prose"] and len(result.reports) == 4

    # continuity(关键评审)失败 → 节点失败
    deps.mock.register("continuity", lambda req: (_ for _ in ()).throw(RuntimeError("挂了")))
    with pytest.raises(RuntimeError, match="关键评审"):
        await run_review_round(deps, draft, _ctx())


async def test_judge_receives_anonymized_and_verdict(deps) -> None:
    draft = await run_writer(deps, _ctx(), writer_id="writer_a")
    report = await run_reviewer(deps, ReviewerRole.PLOT, draft, _ctx())
    verdict = await run_judge(deps, [draft], [report], _ctx(), absent=[])
    assert verdict.verdict.value == "REVISE_LOCAL" and verdict.revision_scope

    # Judge 收到的 user 内容不含 reviewer_role 字段(匿名化)
    judge_calls = [req for role, req in deps.mock.calls if role == "judge"]
    assert judge_calls and "reviewer_role" not in judge_calls[-1].user


async def test_judge_uses_bounded_context_slice(deps) -> None:
    ctx = _ctx().model_copy(
        update={
            "characters": [
                CharacterCard.model_validate(
                    {**CHARACTER, "name": "JUDGE_CONTEXT_SHOULD_NOT_INCLUDE_THIS"}
                )
            ]
        }
    )
    draft = await run_writer(deps, ctx, writer_id="writer_a")
    report = await run_reviewer(deps, ReviewerRole.PLOT, draft, ctx)
    await run_judge(deps, [draft], [report], ctx, absent=[])

    judge_request = [req for role, req in deps.mock.calls if role == "judge"][-1]
    assert "JUDGE_CONTEXT_SHOULD_NOT_INCLUDE_THIS" not in judge_request.user


async def test_judge_user_omits_in_draft_evidence_quotes(deps) -> None:
    draft = await run_writer(deps, _ctx(), writer_id="writer_a")
    long_quote = draft.scenes[0].content
    report = await run_reviewer(deps, ReviewerRole.PLOT, draft, _ctx())
    report = report.model_copy(
        update={
            "issues": [
                report.issues[0].model_copy(
                    update={
                        "claim": "开场信息越权",
                        "evidence": [
                            report.issues[0].evidence[0].model_copy(update={"quote": long_quote})
                        ],
                    }
                )
            ]
        }
    )
    await run_judge(deps, [draft], [report], _ctx(), absent=[])

    user = [req for role, req in deps.mock.calls if role == "judge"][-1].user
    assert long_quote in user
    assert user.count(long_quote) == 1
    assert "开场信息越权" in user
    assert "issue_1" in user
    assert "reviewer_role" not in user


async def test_red_team_issue_id_is_blinded_and_restored_for_rulings(deps) -> None:
    draft = await run_writer(deps, _ctx(), writer_id="writer_a")
    report = await run_reviewer(deps, ReviewerRole.RED_TEAM, draft, _ctx())
    deps.mock.register(
        "judge",
        lambda req: json.dumps(
            {
                "verdict": "REVISE_LOCAL",
                "selected_candidate": "candidate_1",
                "rulings": [
                    {"issue_id": "issue_1", "accepted": True, "reason": "证据成立"}
                ],
                "revision_scope": ["v1c001_s1"],
                "reasoning_summary": "红队问题成立",
            },
            ensure_ascii=False,
        ),
    )

    verdict = await run_judge(deps, [draft], [report], _ctx())

    judge_request = [req for role, req in deps.mock.calls if role == "judge"][-1]
    assert "red_team" not in judge_request.user
    assert '"issue_id": "issue_1"' in judge_request.user
    assert verdict.rulings[0].issue_id == "red_team_1"


async def test_professional_reviewers_receive_minimum_role_context(deps) -> None:
    ctx = _ctx().model_copy(update={"style_rules": "STYLE_SENTINEL"})
    draft = await run_writer(deps, ctx, writer_id="writer_a")

    for role in (
        ReviewerRole.PLOT,
        ReviewerRole.CHARACTER,
        ReviewerRole.CONTINUITY,
        ReviewerRole.PROSE,
    ):
        await run_reviewer(deps, role, draft, ctx)

    requests = {role: req for role, req in deps.mock.calls if role in ReviewerRole}
    character_id = str(CHARACTER["character_id"])
    assert character_id not in requests[ReviewerRole.PLOT].user
    assert character_id in requests[ReviewerRole.CHARACTER].user
    assert character_id in requests[ReviewerRole.CONTINUITY].user
    assert character_id not in requests[ReviewerRole.PROSE].user
    assert "STYLE_SENTINEL" not in requests[ReviewerRole.PLOT].user
    assert "STYLE_SENTINEL" in requests[ReviewerRole.PROSE].user


async def test_reviser_and_canon_curator(deps) -> None:
    draft = await run_writer(deps, _ctx(), writer_id="writer_a")
    order = RevisionOrder.model_validate(
        dict(verdict_ref="v1", candidate_id="candidate_1", issue_ids=["plot_1"],
             scope=["v1c001_s1"], instructions="修转折")
    )
    issues = [
        ReviewIssue.model_validate(
            dict(issue_id="plot_1", reviewer_role="plot", claim="c",
                 evidence=[{"scene_id": "v1c001_s1", "quote": "茶楼里灯火通明"}],
                 violated_rule="r", severity="P1", failure_consequence="f",
                 recommended_rollback_level="prose", confidence=0.5)
        )
    ]
    revised = await run_reviser(deps, draft, order, issues, _ctx())
    assert isinstance(revised, DraftCandidate)

    delta = await run_canon_curator(deps, revised, _ctx(), "canon_v3")
    assert delta.chapter_key == "v1c001" and delta.base_canon_version == "canon_v3"


async def test_kernel_planner(deps) -> None:
    out = await run_kernel_planner(deps, "写一本说书人题材的书")
    assert len(out.candidates) >= 2 and out.differentiation_notes
