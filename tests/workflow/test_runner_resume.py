"""M1.5/M1.6 DoD:节点幂等、崩溃恢复不重跑、revision_round 不因重启归零、预算暂停。"""

from pathlib import Path

import pytest

from novel_agent.config import Settings
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import OpsRepo, PlanningRepo
from novel_agent.domain.schemas import ChapterOutline
from novel_agent.workflow import NodeFailed, check_chapter_budget, run_node
from novel_agent.workflow.budget import BudgetExceeded

OUTLINE = dict(
    chapter_key="v1c001", volume_id="v1", unit_id="u1", core_event="e", pov="p",
    time_location="t", protagonist_goal="g", key_choice="c", start_state="s",
    end_state="e2", emotion_shift="a→b", entry_point="in", exit_hook="out",
    target_words=1000,
)


def _setup(db: Path) -> int:
    engine = build_engine(db)
    create_all(engine)
    with session_scope(engine) as s:
        pid = PlanningRepo(s).create_project("p").id
    return pid


def test_crash_resume_skips_succeeded_nodes(tmp_path) -> None:
    """任意节点后"崩溃"(异常退出+新 engine),resume 不重跑已成功节点。"""
    db = tmp_path / "t.db"
    pid = _setup(db)

    calls = {"n1": 0, "n2": 0, "n3": 0}

    def pipeline(engine, fail_at: str | None) -> None:
        with session_scope(engine) as s:
            ops = OpsRepo(s)
            run = ops.find_resumable_run(pid, "chapter_loop", "v1c001") or ops.create_workflow_run(
                pid, "chapter_loop", "v1c001"
            )
            for name in ("n1", "n2", "n3"):
                def fn(n=name):  # noqa: B008
                    calls[n] += 1
                    if n == fail_at:
                        raise RuntimeError("boom")
                    return {"done": n}

                run_node(ops, run.id, name, f"v1c001|{name}", {}, fn)

    # 第一次:n2 崩溃(模拟进程死亡:引擎废弃,事务已提交的 n1 成功记录留存)
    e1 = build_engine(db)
    with pytest.raises(NodeFailed):
        pipeline(e1, fail_at="n2")
    assert calls == {"n1": 1, "n2": 1, "n3": 0}

    # "重启":全新 engine,重跑整条流水线
    e2 = build_engine(db)
    pipeline(e2, fail_at=None)
    # n1 幂等命中不再执行;n2 重跑成功;n3 首次执行
    assert calls == {"n1": 1, "n2": 2, "n3": 1}

    # 三度重跑:全部命中,零执行
    pipeline(build_engine(db), fail_at=None)
    assert calls == {"n1": 1, "n2": 2, "n3": 1}


def test_revision_round_survives_restart(tmp_path) -> None:
    db = tmp_path / "t.db"
    pid = _setup(db)
    e1 = build_engine(db)
    with session_scope(e1) as s:
        repo = PlanningRepo(s)
        repo.create_chapter(pid, ChapterOutline.model_validate(OUTLINE), 1)
        repo.increment_revision_round(pid, "v1c001")

    # "重启"后读取:轮次仍为 1(Spec §6 N7)
    e2 = build_engine(db)
    with session_scope(e2) as s:
        assert PlanningRepo(s).get_chapter(pid, "v1c001").revision_round == 1


def test_budget_gate_raises_and_counts(tmp_path) -> None:
    db = tmp_path / "t.db"
    pid = _setup(db)
    settings = Settings(_env_file=None, max_calls_per_chapter=2)
    engine = build_engine(db)
    with session_scope(engine) as s:
        ops = OpsRepo(s)
        for _ in range(2):
            ops.record_model_run(
                project_id=pid, chapter_key="v1c001", agent_role="writer",
                provider="mock", model="m", prompt_version="v1",
            )
        run = ops.create_workflow_run(pid, "chapter_loop", "v1c001")
        with pytest.raises(BudgetExceeded):
            run_node(
                ops, run.id, "n_draft", "v1c001|draft", {},
                lambda: {"ok": True},
                budget_check=lambda: check_chapter_budget(ops, "v1c001", settings),
            )
