"""M3.3b: novel edit-outline YAML 导出/导入,bump outline_ver,回 N1。"""

from __future__ import annotations

import pytest
from sqlmodel import Session
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import BibleRepo, OpsRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus, Conflict, PayoffBeat, VerdictType
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningGates, run_planning_chain
from novel_agent.planning.mock_fixtures import (
    PLANNING_CONFLICTS,
    PLANNING_PAYOFFS,
    register_planning_defaults,
)
from novel_agent.production.loop import ChapterLoopGates, run_chapter_loop
from novel_agent.production.mock_fixtures import register_chapter_loop_defaults, verdict_json
from novel_agent.production.outline import (
    OutlineEditError,
    apply_outline_edit,
    dump_outline_yaml,
    export_outline_bundle,
)
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "outline.db")
    create_all(engine)
    return engine


async def _planned(tmp_path, mock: MockProvider | None = None):
    engine = _engine(tmp_path)
    session = Session(engine)
    repo = PlanningRepo(session)
    project = repo.create_project("说书人传奇", genre="奇幻", boundaries=["禁无代价全能"])
    session.commit()
    mock = mock or MockProvider()
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
    bible = BibleRepo(session)
    bible.replace_conflicts(
        project.id, [Conflict.model_validate(item) for item in PLANNING_CONFLICTS]
    )
    bible.replace_payoff_beats(
        project.id, [PayoffBeat.model_validate(item) for item in PLANNING_PAYOFFS]
    )
    session.commit()
    return session, deps, mock, project.id


def _n1_count(session: Session, workflow_run_id: int) -> int:
    return sum(
        1
        for rec in OpsRepo(session).node_history(workflow_run_id)
        if rec.node_name == "n1_validate_outline" and rec.status == "succeeded"
    )


async def test_replan_then_edit_outline_resumes_from_n1(tmp_path) -> None:
    mock = MockProvider()
    session, deps, mock, project_id = await _planned(tmp_path, mock=mock)
    mock.register(
        "judge",
        lambda _req: verdict_json(
            "REPLAN_CHAPTER",
            accepted_issue="continuity_1",
            rollback_target="chapter_outline",
        ),
    )
    try:
        first = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert first.status is ChapterStatus.NEEDS_REPLAN
        assert first.verdict is VerdictType.REPLAN_CHAPTER
        old_lineage = first.lineage_id

        bundle = export_outline_bundle(PlanningRepo(session), project_id, "v1c001")
        bundle["outline"]["core_event"] = "说书人改口,西市失火不再写进评书"
        yaml_text = dump_outline_yaml(bundle)
        new_ver = apply_outline_edit(session, project_id, "v1c001", yaml_text)
        session.commit()

        chapter = PlanningRepo(session).get_chapter(project_id, "v1c001")
        assert new_ver == 2
        assert chapter.outline_version == 2
        assert chapter.revision_round == 0
        assert chapter.status is ChapterStatus.PLANNED
        assert chapter.outline["core_event"] == "说书人改口,西市失火不再写进评书"
        drafts = ProductionRepo(session).list_drafts(project_id, "v1c001")
        assert drafts
        assert all(
            rec.lineage_id.startswith("voided:") or (rec.meta or {}).get("voided")
            for rec in drafts
        )

        mock.register("judge", lambda _req: verdict_json("PASS"))
        second = await run_chapter_loop(
            session, deps, project_id, "v1c001", gates=ChapterLoopGates.auto()
        )
        session.commit()
        assert second.status is ChapterStatus.CANON_LOCKED
        assert second.lineage_id != old_lineage
        assert not second.lineage_id.startswith("voided:")
        assert PlanningRepo(session).get_chapter(project_id, "v1c001").revision_round == 0
        assert _n1_count(session, second.workflow_run_id) >= 1
    finally:
        session.close()


async def test_edit_outline_strips_overnight_forbidden_on_import(tmp_path) -> None:
    session, _deps, _mock, project_id = await _planned(tmp_path)
    try:
        bundle = export_outline_bundle(PlanningRepo(session), project_id, "v1c001")
        forbidden = list(bundle["outline"].get("reveal_forbidden") or [])
        forbidden.extend(["反噬设定", "默写分镜笔记的存在", "穿越身份"])
        bundle["outline"]["reveal_forbidden"] = forbidden
        yaml_text = dump_outline_yaml(bundle)
        new_ver = apply_outline_edit(session, project_id, "v1c001", yaml_text)
        session.commit()
        chapter = PlanningRepo(session).get_chapter(project_id, "v1c001")
        stored = chapter.outline["reveal_forbidden"]
        assert "反噬设定" not in stored
        assert "默写分镜笔记的存在" not in stored
        assert "穿越身份" in stored
        assert new_ver == 2
        assert chapter.outline_version == 2
    finally:
        session.close()


async def test_edit_outline_rejects_empty_citations(tmp_path) -> None:
    session, _deps, _mock, project_id = await _planned(tmp_path)
    try:
        planning = PlanningRepo(session)
        before = planning.get_chapter(project_id, "v1c001").outline_version
        bundle = export_outline_bundle(planning, project_id, "v1c001")
        bundle["outline"]["cited_conflict_ids"] = []
        bundle["outline"]["cited_beat_ids"] = []
        yaml_text = dump_outline_yaml(bundle)
        with pytest.raises(OutlineEditError, match="未引用"):
            apply_outline_edit(session, project_id, "v1c001", yaml_text)
        session.commit()
        assert planning.get_chapter(project_id, "v1c001").outline_version == before
    finally:
        session.close()


async def test_edit_outline_rejects_invented_beat_id(tmp_path) -> None:
    session, _deps, _mock, project_id = await _planned(tmp_path)
    try:
        planning = PlanningRepo(session)
        before = planning.get_chapter(project_id, "v1c001").outline_version
        bundle = export_outline_bundle(planning, project_id, "v1c001")
        bundle["outline"]["cited_beat_ids"] = ["b1_救场立身份"]
        assert bundle["outline"]["cited_conflict_ids"]
        yaml_text = dump_outline_yaml(bundle)
        with pytest.raises(OutlineEditError, match="b1_救场立身份"):
            apply_outline_edit(session, project_id, "v1c001", yaml_text)
        session.commit()
        assert planning.get_chapter(project_id, "v1c001").outline_version == before
    finally:
        session.close()


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


def test_cli_edit_outline_from_file_yes_imports(cli_db, tmp_path) -> None:
    init = CliRunner().invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output

    export = CliRunner().invoke(
        app,
        [
            "edit-outline",
            "v1c001",
            "--project-id",
            "1",
            "--out",
            str(tmp_path / "outline.yaml"),
        ],
    )
    assert export.exit_code == 0, export.output
    yaml_path = tmp_path / "outline.yaml"
    assert yaml_path.is_file()
    text = yaml_path.read_text(encoding="utf-8")
    text = text.replace(
        "说书人随口编的故事一夜成真",
        "说书人改口不再编西市失火",
        1,
    )
    yaml_path.write_text(text, encoding="utf-8")

    imported = CliRunner().invoke(
        app,
        [
            "edit-outline",
            "--project-id",
            "1",
            "--chapter-key",
            "v1c001",
            "--from-file",
            str(yaml_path),
            "--yes",
        ],
    )
    assert imported.exit_code == 0, imported.output
    engine = build_engine(cli_db)
    with session_scope(engine) as session:
        chapter = PlanningRepo(session).get_chapter(1, "v1c001")
        assert chapter.outline_version == 2
        assert chapter.status is ChapterStatus.PLANNED
        assert "改口" in chapter.outline["core_event"]


def test_cli_edit_outline_non_tty_without_file_or_yes_exits_2(cli_db) -> None:
    init = CliRunner().invoke(
        app, ["init", "说书人传奇", "--brief", "说书人发现故事会成真", "--yes"]
    )
    assert init.exit_code == 0, init.output
    result = CliRunner().invoke(app, ["edit-outline", "v1c001", "--project-id", "1"])
    assert result.exit_code == 2, result.output
