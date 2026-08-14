"""Stage 1 slice 1: FastAPI 写作台契约(TestClient + tmp sqlite + mock,无网络)。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_channel_export import LOCKED_1, _add_chapter
from typer.testing import CliRunner

from novel_agent.api.app import create_app
from novel_agent.cli.main import app as cli_app
from novel_agent.config import Settings, reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import BibleRepo, CanonRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterStatus
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


def test_patch_extra_reviewer_flags(client: TestClient) -> None:
    created = client.post(
        "/projects",
        json={"title": "开关", "spark": "说书人发现故事会成真", "auto_bible": False},
    )
    pid = created.json()["id"]
    assert created.json()["enable_writer_b"] is True
    patched = client.patch(
        f"/projects/{pid}",
        json={"enable_writer_b": False, "enable_reader_advocate": False},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["enable_writer_b"] is False
    assert patched.json()["enable_reader_advocate"] is False
    fetched = client.get(f"/projects/{pid}")
    assert fetched.json()["enable_writer_b"] is False


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/projects/99").status_code == 404
    assert client.get("/projects/99/bible").status_code == 404
    assert client.get("/projects/99/graph").status_code == 404
    assert client.get("/projects/99/retrieve?q=西市").status_code == 404


def test_cors_localhost_only(client: TestClient) -> None:
    allowed = client.options(
        "/projects",
        headers={
            "Origin": "http://localhost:18765",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:18765"

    stale_vite = client.options(
        "/projects",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert stale_vite.headers.get("access-control-allow-origin") != "http://localhost:5173"

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
    assert payload["concept_judge"]["after_r2"]["verdict"] == "PASS"
    assert payload["concept_judge"]["after_r4"]["verdict"] == "PASS"
    assert payload["settings"]["enable_writer_b"] is True
    assert payload["settings"]["enable_reader_advocate"] is True


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
    assert "第1章" in exported.text
    assert "v1c001" not in exported.text


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
    assert "desk_url:" in result.output
    assert "18765" in result.output


def test_cli_serve_help() -> None:
    result = CliRunner().invoke(cli_app, ["serve", "--help"])
    assert result.exit_code == 0, result.output
    assert "API" in result.output or "uvicorn" in result.output.lower() or "写作台" in result.output
    assert "18765" in result.output


def _bible_project(client: TestClient, title: str) -> int:
    created = client.post(
        "/projects",
        json={"title": title, "spark": "说书人发现故事会成真", "auto_bible": True},
    )
    assert created.status_code == 200, created.text
    return int(created.json()["id"])


def test_outline_tree_has_five_levels(client: TestClient) -> None:
    pid = _bible_project(client, "大纲树")
    missing = client.get("/projects/99/outline-tree")
    assert missing.status_code == 404

    tree = client.get(f"/projects/{pid}/outline-tree")
    assert tree.status_code == 200, tree.text
    payload = tree.json()
    assert payload["project_id"] == pid
    kernel = payload["kernel"]
    assert kernel is not None
    assert kernel["logline"]
    volumes = payload["volumes"]
    assert volumes
    volume = volumes[0]
    assert volume["volume_id"] == "v1"
    units = volume["units"]
    assert units
    chapters = units[0]["chapters"]
    assert [row["chapter_key"] for row in chapters][:3] == ["v1c001", "v1c002", "v1c003"]
    first = chapters[0]
    assert first["outline"]["chapter_key"] == "v1c001"
    assert first["outline"]["core_event"]
    scenes = first["scenes"]
    assert scenes
    assert scenes[0]["scene_id"]
    assert scenes[0]["goal"]


def test_edit_outline_yaml_roundtrip(client: TestClient) -> None:
    pid = _bible_project(client, "YAML 改纲")
    exported = client.get(f"/projects/{pid}/chapters/v1c001/outline.yaml")
    assert exported.status_code == 200, exported.text
    yaml_text = exported.text
    assert "chapter_key: v1c001" in yaml_text
    assert "scenes:" in yaml_text
    assert "title: 第1章" in yaml_text
    edited = yaml_text.replace("title: 第1章", "title: 修订后的章名", 1)
    applied = client.post(
        f"/projects/{pid}/chapters/v1c001/edit-outline",
        json={"yaml": edited},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["outline_version"] >= 2
    assert applied.json()["status"] == "PLANNED"

    tree = client.get(f"/projects/{pid}/outline-tree").json()
    chapter = tree["volumes"][0]["units"][0]["chapters"][0]
    assert chapter["title"] == "修订后的章名"
    assert chapter["outline"]["title"] == "修订后的章名"


def test_review_list_buckets_and_actions(client: TestClient) -> None:
    pid = _bible_project(client, "审稿台")
    empty = client.get(f"/projects/{pid}/review")
    assert empty.status_code == 200
    assert empty.json() == []

    written = client.post(f"/projects/{pid}/chapters/v1c001/write-chapter")
    assert written.status_code == 200, written.text
    assert written.json()["status"] == "HUMAN_REVIEW"

    queue = client.get(f"/projects/{pid}/review")
    assert queue.status_code == 200, queue.text
    items = queue.json()
    assert len(items) == 1
    item = items[0]
    assert item["chapter_key"] == "v1c001"
    assert item["bucket"] == "HUMAN_REVIEW"
    assert item["status"] == "HUMAN_REVIEW"
    assert item["verdict"] == "PASS"
    assert "茶楼" in item["draft_text"]
    assert item["issues"]
    quotes = [
        span["quote"]
        for issue in item["issues"]
        for span in issue["evidence"]
        if span.get("quote")
    ]
    assert quotes
    locatable = next(
        span for issue in item["issues"] for span in issue["evidence"] if span.get("found")
    )
    assert locatable["start"] >= 0
    assert item["draft_text"][locatable["start"] : locatable["end"]] == locatable["quote"]
    missing = next(
        span
        for issue in item["issues"]
        for span in issue["evidence"]
        if span.get("quote") and not span.get("found")
    )
    assert missing["start"] is None
    assert "正文里根本没有这句话" in missing["quote"]
    assert item["diff"] is None

    locked = client.post(
        f"/projects/{pid}/chapters/v1c001/locked-ranges",
        json={"ranges": ["开场灯火"]},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["locked_ranges"] == ["开场灯火"]

    approved = client.post(f"/projects/{pid}/chapters/v1c001/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "CANON_LOCKED"

    second = client.post(f"/projects/{pid}/chapters/v1c002/write-chapter")
    assert second.status_code == 200, second.text
    rejected = client.post(f"/projects/{pid}/chapters/v1c002/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "NEEDS_REPLAN"

    board = {row["chapter_key"]: row for row in client.get(f"/projects/{pid}/review").json()}
    assert board["v1c001"]["bucket"] == "CANON_LOCKED"
    assert board["v1c002"]["bucket"] == "IN_PROGRESS"
    assert board["v1c002"]["status"] == "NEEDS_REPLAN"


def test_review_diff_when_two_drafts_exist(client: TestClient) -> None:
    pid = _bible_project(client, "双稿差异")
    written = client.post(f"/projects/{pid}/chapters/v1c001/write-chapter")
    assert written.status_code == 200, written.text

    engine = client.app.state.engine
    with session_scope(engine) as session:
        production = ProductionRepo(session)
        latest = production.latest_chapter_draft(pid, "v1c001")
        assert latest is not None
        production.create_draft(
            pid,
            "v1c001",
            latest.candidate_id,
            latest.lineage_id,
            "修订后的第二稿：茶楼已打烊。",
            dict(latest.meta or {}),
            latest.prompt_version,
            latest.outline_version,
            revision_of=latest.id,
        )

    board = client.get(f"/projects/{pid}/review").json()
    item = board[0]
    assert item["previous_draft_text"]
    assert "茶楼" in item["previous_draft_text"]
    assert item["draft_text"] == "修订后的第二稿：茶楼已打烊。"
    assert item["diff"]
    assert "修订后的第二稿" in item["diff"]


def test_retrieve_api_and_cli(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = _bible_project(client, "检索台")
    empty = client.get(f"/projects/{pid}/retrieve?q=")
    assert empty.status_code == 400
    found = client.get(f"/projects/{pid}/retrieve?q=说书人")
    assert found.status_code == 200, found.text
    payload = found.json()
    assert payload["project_id"] == pid
    assert payload["query"] == "说书人"
    assert payload["facts"]
    assert all("text" in fact and "fact_id" in fact for fact in payload["facts"])

    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "cli-retrieve.db"))
    monkeypatch.setenv("NOVEL_CREATIVE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_REVIEW__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_JUDGE__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EXTRACT__PROVIDER", "mock")
    monkeypatch.setenv("NOVEL_EMBEDDING__PROVIDER", "mock")
    reset_settings_cache()
    init = CliRunner().invoke(
        cli_app,
        ["init", "检索CLI", "--brief", "说书人发现故事会成真", "--yes", "--skip-concept-judge"],
    )
    assert init.exit_code == 0, init.output
    result = CliRunner().invoke(
        cli_app, ["retrieve", "--project-id", "1", "--query", "说书人"]
    )
    reset_settings_cache()
    assert result.exit_code == 0, result.output
    assert "fact_id=" in result.output or "章纲" in result.output or "冲突" in result.output


def test_export_channel_query_returns_file(client: TestClient) -> None:
    created = client.post(
        "/projects",
        json={"title": "渠道包", "spark": "说书人发现故事会成真", "auto_bible": False},
    )
    pid = created.json()["id"]
    engine = client.app.state.engine
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        production = ProductionRepo(session)
        planning.save_volume(pid, "v1", {}, title="入局")
        _add_chapter(
            planning,
            production,
            pid,
            chapter_key="v1c001",
            title="醒木",
            body=LOCKED_1,
            status=ChapterStatus.CANON_LOCKED,
            order_index=1,
        )
        _add_chapter(
            planning,
            production,
            pid,
            chapter_key="v1c002",
            title="草稿",
            body="仅预览可见的草稿",
            status=ChapterStatus.HUMAN_REVIEW,
            order_index=2,
        )

    qidian = client.get(f"/projects/{pid}/export?channel=qidian&format=txt")
    assert qidian.status_code == 200
    assert "第1章 醒木" in qidian.text
    assert LOCKED_1 in qidian.text
    assert "仅预览可见的草稿" not in qidian.text
    assert "text/plain" in qidian.headers["content-type"]

    drafts = client.get(
        f"/projects/{pid}/export?channel=qidian&format=txt&include_drafts=true"
    )
    assert drafts.status_code == 200
    assert "仅预览可见的草稿" in drafts.text

    epub = client.get(f"/projects/{pid}/export?channel=epub&format=epub")
    assert epub.status_code == 200
    assert epub.headers["content-type"].startswith("application/epub+zip")
    assert epub.content[:2] == b"PK"
    assert b"application/epub+zip" in epub.content

    bad = client.get(f"/projects/{pid}/export?channel=wechat")
    assert bad.status_code == 400
