"""Stage 1 slice 1: FastAPI 写作台契约(TestClient + tmp sqlite + mock,无网络)。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from novel_agent.api.app import create_app
from novel_agent.cli.main import app as cli_app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo
from novel_agent.graph.projector import project_graph


@pytest.fixture()
def client(tmp_path):
    engine = build_engine(tmp_path / "desk.db")
    create_all(engine)
    settings = Settings(_env_file=None, db_path=tmp_path / "desk.db")
    with TestClient(create_app(settings=settings, engine=engine)) as test_client:
        yield test_client


def test_projects_crud_and_list(client: TestClient) -> None:
    empty = client.get("/projects")
    assert empty.status_code == 200
    assert empty.json() == []

    created = client.post(
        "/projects",
        json={"title": "墨案", "spark": "说书人发现故事会成真", "auto_bible": False},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["title"] == "墨案"
    assert body["spark"] == "说书人发现故事会成真"
    pid = body["id"]

    listed = client.get("/projects")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == pid

    fetched = client.get(f"/projects/{pid}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "墨案"

    patched = client.patch(f"/projects/{pid}", json={"title": "说书人传奇", "genre": "奇幻"})
    assert patched.status_code == 200
    assert patched.json()["title"] == "说书人传奇"
    assert patched.json()["genre"] == "奇幻"

    deleted = client.delete(f"/projects/{pid}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "archived"
    assert client.get("/projects").json() == []
    assert client.get("/projects?include_archived=true").json()[0]["id"] == pid


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/projects/99").status_code == 404
    assert client.get("/projects/99/bible").status_code == 404
    assert client.get("/projects/99/graph").status_code == 404


def test_cors_localhost_only(client: TestClient) -> None:
    allowed = client.options(
        "/projects",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    denied = client.options(
        "/projects",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert denied.headers.get("access-control-allow-origin") != "https://evil.example"


def test_create_with_spark_runs_auto_bible(client: TestClient) -> None:
    created = client.post(
        "/projects",
        json={"title": "说书人传奇", "spark": "说书人发现故事会成真", "auto_bible": True},
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    bible = client.get(f"/projects/{pid}/bible")
    assert bible.status_code == 200, bible.text
    payload = bible.json()
    assert payload["kernel"] is not None
    assert payload["structure"] is not None
    assert payload["characters"]
    assert payload["conflicts"]
    assert payload["payoffs"]
    assert len(payload["outlines"]) == 5
    assert set(payload["completed"]) == {"R0", "R1", "R2", "R3", "R4", "R5"}
    assert payload["pending"] is None


def test_interactive_round_confirm(client: TestClient) -> None:
    created = client.post(
        "/projects",
        json={"title": "对话台", "spark": "说书人发现故事会成真", "auto_bible": False},
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    pending = created.json()["bible"]["pending"]
    assert pending["round"] == 0
    assert pending["kind"] == "R0"

    r0 = client.post(f"/projects/{pid}/bible/rounds/0/confirm")
    assert r0.status_code == 200, r0.text
    assert r0.json()["completed"] == ["R0"]
    assert r0.json()["pending"]["round"] == 1

    r1 = client.post(f"/projects/{pid}/bible/rounds/1/confirm", json={"select": 1})
    assert r1.status_code == 200, r1.text
    assert "R1" in r1.json()["completed"]
    assert r1.json()["kernel"] is not None
    assert r1.json()["pending"]["round"] == 2

    for n in (2, 3, 4, 5):
        step = client.post(f"/projects/{pid}/bible/rounds/{n}/confirm")
        assert step.status_code == 200, step.text
    done = client.get(f"/projects/{pid}/bible")
    assert done.json()["pending"] is None
    assert set(done.json()["completed"]) == {"R0", "R1", "R2", "R3", "R4", "R5"}
    assert len(done.json()["outlines"]) == 5


def test_graph_endpoint_matches_projector(client: TestClient) -> None:
    created = client.post(
        "/projects",
        json={"title": "关系图", "spark": "说书人发现故事会成真", "auto_bible": True},
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    api_graph = client.get(f"/projects/{pid}/graph")
    assert api_graph.status_code == 200, api_graph.text
    payload = api_graph.json()
    assert payload["project_id"] == pid
    assert "nodes" in payload and "edges" in payload and "tracks" in payload

    engine = client.app.state.engine
    with session_scope(engine) as session:
        projected = project_graph(
            pid, PlanningRepo(session), BibleRepo(session), CanonRepo(session)
        )
    assert payload == json.loads(json.dumps(projected.to_dict()))


def test_chapters_write_approve_and_export(client: TestClient) -> None:
    created = client.post(
        "/projects",
        json={"title": "章节轨", "spark": "说书人发现故事会成真", "auto_bible": True},
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]

    listed = client.get(f"/projects/{pid}/chapters")
    assert listed.status_code == 200
    keys = [row["chapter_key"] for row in listed.json()]
    assert keys[:3] == ["v1c001", "v1c002", "v1c003"]

    written = client.post(f"/projects/{pid}/chapters/v1c001/write-chapter")
    assert written.status_code == 200, written.text
    assert written.json()["status"] == "HUMAN_REVIEW"

    approved = client.post(f"/projects/{pid}/chapters/v1c001/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "CANON_LOCKED"

    exported = client.get(f"/projects/{pid}/export?format=md")
    assert exported.status_code == 200
    assert "v1c001" in exported.text


def test_write_batch_and_resume_endpoints(client: TestClient) -> None:
    created = client.post(
        "/projects",
        json={"title": "批次", "spark": "说书人发现故事会成真", "auto_bible": True},
    )
    pid = created.json()["id"]
    batch = client.post(
        f"/projects/{pid}/write-batch", json={"chapters": 3, "yes": True}
    )
    assert batch.status_code == 200, batch.text
    statuses = {row["chapter_key"]: row["status"] for row in batch.json()["results"]}
    assert statuses["v1c001"] == "CANON_LOCKED"
    resumed = client.post(f"/projects/{pid}/resume", json={"yes": True})
    assert resumed.status_code == 200, resumed.text


def test_cli_doctor_prints_api_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    reset_settings_cache()
    result = CliRunner().invoke(cli_app, ["doctor"])
    reset_settings_cache()
    assert result.exit_code == 0, result.output
    assert "api_url:" in result.output
    assert "127.0.0.1" in result.output


def test_cli_serve_help() -> None:
    result = CliRunner().invoke(cli_app, ["serve", "--help"])
    assert result.exit_code == 0, result.output
    assert "API" in result.output or "uvicorn" in result.output.lower() or "写作台" in result.output
