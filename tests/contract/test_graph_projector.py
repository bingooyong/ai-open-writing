"""关系图投影契约:空图、R3 填充、异名合并、provisional、证据保留。"""

from __future__ import annotations

from contextlib import suppress

from sqlmodel import Session
from test_schemas import CHARACTER, KERNEL
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
from novel_agent.domain.schemas import (
    CanonDelta,
    CharacterCard,
    IdentityAlias,
    RelationshipChange,
    StoryKernel,
)
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.graph.export import to_json, to_mermaid
from novel_agent.graph.projector import MISSING_EVIDENCE, project_graph
from novel_agent.planning.chain import PlanningAborted, PlanningGates
from novel_agent.planning.conversation import run_bible_conversation
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.runtime.agents import AgentDeps


def _engine(tmp_path):
    engine = build_engine(tmp_path / "graph.db")
    create_all(engine)
    return engine


def _deps(session: Session) -> AgentDeps:
    mock = MockProvider()
    register_planning_defaults(mock)
    return AgentDeps(
        gateway=ModelGateway(Settings(_env_file=None), session, {"mock": mock}),
        project_id=None,
    )


def test_graph_empty_after_r1(tmp_path) -> None:
    engine = _engine(tmp_path)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("仅内核").id
        planning.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(pid, 1)
        graph = project_graph(pid, planning, BibleRepo(session), CanonRepo(session))
        assert graph.nodes == []
        assert graph.edges == []
        assert graph.tracks == []
        assert graph.canon_version == "canon_v0"


async def test_graph_populated_after_r3(tmp_path) -> None:
    engine = _engine(tmp_path)
    with Session(engine) as session:
        planning = PlanningRepo(session)
        bible = BibleRepo(session)
        canon = CanonRepo(session)
        project = planning.create_project("人物后", boundaries=["禁无代价全能"])
        session.commit()
        deps = _deps(session)
        deps.project_id = project.id

        def confirm(prompt: str) -> bool:
            return "冲突" not in prompt

        with suppress(PlanningAborted):
            await run_bible_conversation(
                planning,
                bible,
                canon,
                deps,
                spark="火花",
                gates=PlanningGates(select_kernel=lambda _c: 0, confirm=confirm),
            )
        session.commit()
        graph = project_graph(project.id, planning, bible, canon)
        kinds = {node.id: node.kind for node in graph.nodes}
        assert kinds["ch_su"] == "character"
        assert kinds["ch_shuju"] == "character"
        assert any(node.kind == "faction" and node.label == "书局" for node in graph.nodes)
        assert graph.edges
        edge = graph.edges[0]
        assert edge.provisional is True
        assert edge.evidence.strip()
        assert edge.evidence != MISSING_EVIDENCE


def test_graph_alias_merge_provisional_and_missing_evidence_kept(tmp_path) -> None:
    engine = _engine(tmp_path)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        bible = BibleRepo(session)
        canon = CanonRepo(session)
        pid = planning.create_project("异名合并").id
        planning.upsert_character(pid, CharacterCard.model_validate(CHARACTER))
        planning.upsert_character(
            pid,
            CharacterCard.model_validate(
                {**CHARACTER, "character_id": "ch_shuju", "name": "霍执事"}
            ),
        )
        bible.upsert_alias(pid, IdentityAlias(canonical_character_id="ch_su", alias="苏说书的"))
        canon.upsert_relationship(
            pid,
            "苏说书的",
            "ch_shuju",
            "胁迫",
            evidence="",
            source_chapter="planning",
            provisional=True,
        )
        delta = CanonDelta(
            chapter_key="v1c001",
            base_canon_version="canon_v0",
            relationship_changes=[
                RelationshipChange(
                    parties=["苏说书的", "ch_shuju"],
                    from_state="陌生人",
                    to_state="胁迫",
                    evidence="书局执事上门",
                )
            ],
        )
        canon.save_delta(pid, delta, "k1", provisional=True)

        graph = project_graph(pid, planning, bible, canon)
        alias_nodes = [n for n in graph.nodes if n.kind == "alias"]
        assert alias_nodes[0].alias_of == "ch_su"
        pair = {(e.source, e.target) for e in graph.edges}
        assert ("ch_shuju", "ch_su") in pair or ("ch_su", "ch_shuju") in pair
        assert all("苏说书的" not in (e.source, e.target) for e in graph.edges)
        edge = graph.edges[0]
        assert edge.provisional is True
        assert edge.evidence == MISSING_EVIDENCE
        assert edge.occurrence >= 1
        assert graph.tracks
        assert graph.tracks[0].beats[0].from_state == "陌生人"
        mermaid = to_mermaid(graph)
        assert "graph LR" in mermaid
        assert "-.->" in mermaid
        payload = to_json(graph)
        assert MISSING_EVIDENCE in payload


def test_cli_graph_json_and_mermaid(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    engine = build_engine(db_path)
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("图导出").id
        PlanningRepo(session).upsert_character(
            pid, CharacterCard.model_validate(CHARACTER)
        )

    json_result = CliRunner().invoke(
        app, ["graph", "--project-id", str(pid), "--format", "json"]
    )
    assert json_result.exit_code == 0, json_result.output
    assert '"kind": "character"' in json_result.output

    mermaid_result = CliRunner().invoke(
        app, ["graph", "--project-id", str(pid), "--format", "mermaid"]
    )
    assert mermaid_result.exit_code == 0, mermaid_result.output
    assert "graph LR" in mermaid_result.output
    reset_settings_cache()
