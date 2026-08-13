"""M3.2 规划链契约:mock 下走通,产物入库可查;--yes 非交互路径不挂起。"""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.models import ProjectRecord
from novel_agent.domain.repos import PlanningRepo
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningAborted, PlanningGates, run_planning_chain
from novel_agent.planning.mock_fixtures import (
    PLANNING_CHARACTERS,
    PLANNING_KERNELS,
    planning_outline_payload,
    register_planning_defaults,
)
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "plan.db")
    create_all(engine)
    return engine


def _deps(session: Session, mock: MockProvider | None = None) -> AgentDeps:
    mock = mock or MockProvider()
    register_planning_defaults(mock)
    settings = Settings(_env_file=None)
    gateway = ModelGateway(settings, session, {"mock": mock})
    return AgentDeps(gateway=gateway, project_id=None)


def test_planning_repo_lists_planning_artifacts(tmp_path) -> None:
    from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

    from novel_agent.domain.schemas import (
        ChapterOutline,
        CharacterCard,
        PlotUnitCard,
        SceneCard,
        StoryKernel,
    )

    engine = _engine(tmp_path)
    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        pid = repo.create_project("列表查询").id
        repo.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        repo.save_kernel(pid, StoryKernel.model_validate({**KERNEL, "logline": "另一候选"}))
        repo.approve_kernel(pid, 1)
        repo.upsert_character(pid, CharacterCard.model_validate(CHARACTER))
        repo.save_volume(pid, "v1", {"goal": "入局"}, title="第一卷")
        repo.save_unit(pid, "v1", PlotUnitCard.model_validate(UNIT))
        repo.create_chapter(pid, ChapterOutline.model_validate(OUTLINE), order_index=1)
        repo.save_scene_cards(pid, "v1c001", [SceneCard.model_validate(SCENE)])

        kernels = repo.list_kernels(pid)
        assert len(kernels) == 2
        assert kernels[0].approved is True
        assert repo.list_volumes(pid)[0].volume_id == "v1"
        assert repo.list_units(pid)[0].unit_id == "u1"
        chapters = repo.list_chapters(pid)
        assert [c.chapter_key for c in chapters] == ["v1c001"]


async def test_planning_chain_persists_approved_kernel_characters_volume_units_and_rolling_outlines(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("说书人传奇", genre="奇幻", boundaries=["禁血腥"])
        session.commit()
        deps = _deps(session)
        deps.project_id = project.id

        result = await run_planning_chain(
            repo,
            deps,
            brief="说书人发现故事会成真",
            gates=PlanningGates.auto(select_index=0),
            volume_id="v1",
            chapters_needed=5,
        )
        session.commit()

        assert result.project_id == project.id
        assert len(result.chapter_keys) == 5

        kernels = repo.list_kernels(project.id)
        assert len(kernels) == 3
        approved = repo.get_approved_kernel(project.id)
        assert approved is not None
        assert approved.logline == PLANNING_KERNELS[0]["logline"]

        characters = repo.list_characters(project.id)
        assert {c.character_id for c in characters} == {
            card["character_id"] for card in PLANNING_CHARACTERS
        }

        volumes = repo.list_volumes(project.id)
        assert len(volumes) == 1 and volumes[0].volume_id == "v1"
        assert volumes[0].status == "confirmed"

        units = repo.list_units(project.id)
        assert len(units) == 1
        assert units[0].unit_id == planning_outline_payload()["unit"]["unit_id"]

        chapters = repo.list_chapters(project.id)
        assert [c.chapter_key for c in chapters] == [f"v1c{i:03d}" for i in range(1, 6)]
        assert all(c.status.value == "PLANNED" for c in chapters)
        for chapter in chapters:
            cards = repo.list_scene_cards(project.id, chapter.chapter_key)
            assert len(cards) >= 2
            assert all(card.chapter_key == chapter.chapter_key for card in cards)
            outline = repo.get_outline(project.id, chapter.chapter_key)
            assert outline.unit_id == units[0].unit_id
            assert outline.volume_id == "v1"


async def test_planning_chain_selects_requested_kernel_candidate(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("候选二")
        session.commit()
        deps = _deps(session)
        deps.project_id = project.id

        await run_planning_chain(
            repo,
            deps,
            brief="简报",
            gates=PlanningGates.auto(select_index=1),
            volume_id="v1",
            chapters_needed=5,
        )
        session.commit()

        approved = repo.get_approved_kernel(project.id)
        assert approved is not None
        assert approved.logline == PLANNING_KERNELS[1]["logline"]


async def test_planning_chain_aborts_before_persisting_characters_when_confirm_rejected(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("中止")
        session.commit()
        deps = _deps(session)
        deps.project_id = project.id

        def confirm(prompt: str) -> bool:
            return "角色" not in prompt

        with pytest.raises(PlanningAborted, match="characters"):
            await run_planning_chain(
                repo,
                deps,
                brief="简报",
                gates=PlanningGates(
                    select_kernel=lambda _cands: 0,
                    confirm=confirm,
                ),
                volume_id="v1",
                chapters_needed=5,
            )
        session.commit()

        assert repo.get_approved_kernel(project.id) is not None
        assert repo.list_characters(project.id) == []
        assert repo.list_volumes(project.id) == []
        assert repo.list_chapters(project.id) == []


async def test_planning_chain_skips_completed_stages_on_resume(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        repo = PlanningRepo(session)
        project = repo.create_project("续跑")
        session.commit()
        deps = _deps(session)
        deps.project_id = project.id
        await run_planning_chain(
            repo,
            deps,
            brief="简报",
            gates=PlanningGates.auto(select_index=0),
            volume_id="v1",
            chapters_needed=5,
        )
        session.commit()

        mock = MockProvider()
        register_planning_defaults(mock)
        deps = AgentDeps(
            gateway=ModelGateway(Settings(_env_file=None), session, {"mock": mock}),
            project_id=project.id,
        )
        result = await run_planning_chain(
            repo,
            deps,
            brief="简报",
            gates=PlanningGates.auto(select_index=0),
            volume_id="v1",
            chapters_needed=5,
        )

        assert set(result.skipped) == {"kernel", "characters", "outline"}
        assert mock.calls == []
        assert len(repo.list_chapters(project.id)) == 5


@pytest.fixture()
def cli_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    yield db_path
    reset_settings_cache()


def test_cli_init_yes_creates_project_and_persists_planning_chain(cli_db) -> None:
    db_path = cli_db

    result = CliRunner().invoke(
        app,
        [
            "init",
            "说书人传奇",
            "--brief",
            "说书人发现自己讲的故事会成真",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "project_id=" in result.output

    engine = build_engine(db_path)
    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        # CLI 首个项目 id 为 1
        assert repo.get_approved_kernel(1) is not None
        assert repo.list_characters(1)
        assert repo.list_volumes(1)
        assert repo.list_units(1)
        assert len(repo.list_chapters(1)) == 5
        assert repo.list_scene_cards(1, "v1c001")


def test_cli_plan_yes_runs_chain_for_existing_project(cli_db) -> None:
    engine = build_engine(cli_db)
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("已有项目").id

    result = CliRunner().invoke(
        app,
        ["plan", "--project-id", str(pid), "--brief", "说书人题材", "--yes"],
    )
    assert result.exit_code == 0, result.output

    with session_scope(engine) as session:
        repo = PlanningRepo(session)
        assert repo.get_approved_kernel(pid) is not None
        assert len(repo.list_chapters(pid)) == 5


def test_cli_init_without_yes_exits_in_non_interactive_env(cli_db) -> None:
    result = CliRunner().invoke(app, ["init", "会挂起吗", "--brief", "简报"])
    assert result.exit_code == 2, result.output
    assert "--yes" in result.output

    engine = build_engine(cli_db)
    create_all(engine)
    with session_scope(engine) as session:
        assert session.exec(select(ProjectRecord)).first() is None


def test_mock_planning_fixtures_are_valid_json_payloads() -> None:
    payload = planning_outline_payload(chapters_needed=5)
    assert len(payload["outlines"]) == 5
    assert len(payload["scene_cards"]) == 10
    assert json.dumps(PLANNING_KERNELS, ensure_ascii=False)
