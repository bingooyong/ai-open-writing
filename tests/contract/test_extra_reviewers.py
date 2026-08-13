"""Stage 1 slice 3: Writer B + Reader Advocate, Source Reviewer 在无表时跳过。"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.repos import PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus, ReviewerRole, VerdictType
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningGates, run_planning_chain
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.planning.settings import (
    desk_settings,
    has_source_record_table,
    review_roles_for,
)
from novel_agent.production.loop import ChapterLoopGates, run_chapter_loop
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "extra.db")
    create_all(engine)
    return engine


async def _planned(tmp_path, *, settings_patch: dict | None = None):
    engine = _engine(tmp_path)
    session = Session(engine)
    repo = PlanningRepo(session)
    project = repo.create_project("说书人传奇", genre="奇幻", boundaries=["禁无代价全能"])
    if settings_patch:
        project.settings = {**desk_settings(project), **settings_patch}
        session.add(project)
    session.commit()
    mock = MockProvider()
    register_planning_defaults(mock)
    register_chapter_loop_defaults(mock)
    settings = Settings(_env_file=None)
    deps = AgentDeps(
        gateway=ModelGateway(settings, session, {"mock": mock}),
        project_id=project.id,
    )
    await run_planning_chain(
        repo,
        deps,
        brief="说书人发现故事会成真",
        gates=PlanningGates.auto(),
        volume_id="v1",
        chapters_needed=5,
    )
    session.commit()
    return session, deps, mock, project.id


def test_source_record_table_absent_on_stage0_schema(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        assert has_source_record_table(session) is False
        assert "source_record" not in inspect(session.get_bind()).get_table_names()
        roles = review_roles_for(session, PlanningRepo(session).create_project("x"))
        assert ReviewerRole.SOURCE not in roles
        assert ReviewerRole.READER_ADVOCATE in roles


async def test_writer_b_and_reader_advocate_participate_and_r6_still_passes(tmp_path) -> None:
    session, deps, mock, project_id = await _planned(tmp_path)
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()
        assert result.status is ChapterStatus.CANON_LOCKED
        assert result.verdict is VerdictType.PASS
        called = {role for role, _req in mock.calls}
        assert "writer_a" in called
        assert "writer_b" in called
        assert "reader_advocate" in called
        assert "source" not in called
        drafts = ProductionRepo(session).list_drafts(project_id, "v1c001", result.lineage_id)
        n3_drafts = [row for row in drafts if row.revision_of is None]
        assert len(n3_drafts) >= 2
        assert {row.candidate_id for row in n3_drafts} >= {"candidate_1", "candidate_2"}
    finally:
        session.close()


async def test_flags_can_disable_writer_b_and_reader_advocate(tmp_path) -> None:
    session, deps, mock, project_id = await _planned(
        tmp_path,
        settings_patch={"enable_writer_b": False, "enable_reader_advocate": False},
    )
    try:
        result = await run_chapter_loop(
            session,
            deps,
            project_id,
            "v1c001",
            gates=ChapterLoopGates.auto(),
        )
        session.commit()
        assert result.verdict is VerdictType.PASS
        called = {role for role, _req in mock.calls}
        assert "writer_a" in called
        assert "writer_b" not in called
        assert "reader_advocate" not in called
    finally:
        session.close()
