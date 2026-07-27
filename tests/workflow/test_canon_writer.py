"""M1.7 DoD:冲突拦截(R1 类)、无批准拒绝、provisional 转正、幂等防重复、git 检查点。"""

import subprocess

import pytest
from sqlmodel import select

from novel_agent.domain.canon_writer import CanonConflict, CanonWriter
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.models import EntityStateRecord
from novel_agent.domain.repos import CanonRepo, OpsRepo, PlanningRepo
from novel_agent.domain.schemas import CanonDelta


def _delta(chapter: str, entity: str = "ch_su", **change_over: object) -> CanonDelta:
    change = dict(
        entity_id=entity, state_type="status", old_value="", new_value="重伤", reason="激战",
    )
    change.update(change_over)
    return CanonDelta.model_validate(
        dict(chapter_key=chapter, base_canon_version="canon_v0",
             character_state_changes=[change])
    )


@pytest.fixture()
def env(tmp_path):
    engine = build_engine(tmp_path / "t.db")
    create_all(engine)
    with session_scope(engine) as s:
        pid = PlanningRepo(s).create_project("p").id
    return engine, pid


def test_dead_guard_blocks_resurrection(env) -> None:
    """R1 类:角色已死仍被变更 → CanonConflict。"""
    engine, pid = env
    with session_scope(engine) as s:
        CanonRepo(s).append_entity_state(pid, "ch_wang", "status", "已死亡", "坠崖", "v1c001")
    with session_scope(engine) as s, pytest.raises(CanonConflict, match="死亡守卫"):
        CanonWriter(s, pid).stage_provisional(
            _delta("v1c002", entity="ch_wang", new_value="现身酒馆"), "idem-r1"
        )


def test_old_value_assertion(env) -> None:
    engine, pid = env
    with session_scope(engine) as s:
        CanonRepo(s).append_entity_state(pid, "ch_su", "position", "临安", "开局", "v1c001")
    with session_scope(engine) as s, pytest.raises(CanonConflict, match="旧值断言"):
        CanonWriter(s, pid).stage_provisional(
            _delta("v1c002", state_type="position", old_value="汴京", new_value="西域"),
            "idem-ov",
        )


def test_finalize_requires_approval(env) -> None:
    """无人工批准记录 → 拒绝提交(PRD §12.3)。"""
    engine, pid = env
    with session_scope(engine) as s, pytest.raises(PermissionError, match="无人工批准"):
        CanonWriter(s, pid).finalize(_delta("v1c001"), "idem-a", "v1c001")


def test_provisional_promote_and_idempotent_finalize(env) -> None:
    engine, pid = env
    delta = _delta("v1c001")

    with session_scope(engine) as s:
        CanonWriter(s, pid).stage_provisional(delta, "idem-1")
        # stage 幂等:同 key 二次调用不重复写状态
        CanonWriter(s, pid).stage_provisional(delta, "idem-1")

    with session_scope(engine) as s:
        assert len(s.exec(select(EntityStateRecord)).all()) == 1  # 未重复

    with session_scope(engine) as s:
        OpsRepo(s).save_approval(pid, "chapter", "v1c001", "approved")
        CanonWriter(s, pid).finalize(delta, "idem-1", "v1c001")

    with session_scope(engine) as s:
        repo = CanonRepo(s)
        states = repo.latest_entity_states(pid)  # 不含 provisional 也能查到 → 已转正
        assert ("ch_su", "status") in states
        assert repo.current_canon_version(pid) == "canon_v1"

    # finalize 幂等:重复提交不产生第二份状态/第二个版本
    with session_scope(engine) as s:
        CanonWriter(s, pid).finalize(delta, "idem-1", "v1c001")
    with session_scope(engine) as s:
        assert len(s.exec(select(EntityStateRecord)).all()) == 1
        assert CanonRepo(s).current_canon_version(pid) == "canon_v1"


def test_git_checkpoint(tmp_path) -> None:
    """D12:批准后产生 git 检查点;git 失败不影响事务(此处验证成功路径)。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "t"], check=True)

    engine = build_engine(repo_dir / "data" / "t.db")
    create_all(engine)
    with session_scope(engine) as s:
        pid = PlanningRepo(s).create_project("p").id
        OpsRepo(s).save_approval(pid, "chapter", "v1c001", "approved")
        CanonWriter(s, pid, git_root=repo_dir).finalize(_delta("v1c001"), "idem-g", "v1c001")

    log = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "--oneline"], capture_output=True, text=True
    ).stdout
    assert "canon: v1c001" in log
