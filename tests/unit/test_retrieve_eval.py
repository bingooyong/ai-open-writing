"""Stage 2 检索评测:冻结金标、hash 嵌入下限、CLI;无网络。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from novel_agent.cli.main import app
from novel_agent.config import reset_settings_cache
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.eval.retrieval import (
    HASH_MIN_HIT_RATE,
    HASH_MIN_MRR,
    HASH_MIN_RECALL_AT_1,
    HASH_MIN_RECALL_AT_3,
    HASH_MUST_HIT_AT_3,
    default_golden_path,
    first_relevant_rank,
    format_report,
    is_pollutant,
    is_relevant,
    load_golden,
    run_retrieval_eval,
)
from novel_agent.memory.embeddings import HashEmbedding
from novel_agent.memory.protocol import FactKind, MemoryFact

_REQUIRED_CATEGORIES = {
    "entity",
    "character",
    "relationship",
    "scene",
    "conflict",
    "payoff",
    "summary",
}


def _fact(
    text: str,
    *,
    fact_id: str = "entity:ch_su:fact",
    kind: FactKind = FactKind.ENTITY,
) -> MemoryFact:
    return MemoryFact(fact_id=fact_id, text=text, kind=kind, source="v1c001")


def test_golden_set_is_frozen_and_covers_kinds() -> None:
    payload = load_golden(default_golden_path())
    queries = payload.queries
    assert payload.version == 1
    assert len(queries) >= 10
    assert {item.category for item in queries} >= _REQUIRED_CATEGORIES
    ids = [item.id for item in queries]
    assert len(ids) == len(set(ids))
    for item in queries:
        assert item.query.strip()
        assert item.expect.keywords or item.expect.fact_id_prefixes


def test_relevant_hit_requires_expected_keyword() -> None:
    expect = {"keywords": ["西市火灾"], "fact_id_prefixes": ["entity:"]}
    assert is_relevant(_fact("西市火灾由说书人编造"), expect)
    assert not is_relevant(_fact("北境商队走失三头骆驼"), expect)
    assert first_relevant_rank([_fact("北境商队走失三头骆驼")], expect) is None
    assert first_relevant_rank([_fact("西市火灾由说书人编造")], expect) == 1


def test_pollutant_ignores_relevant_hits() -> None:
    expect = {"keywords": ["西市火灾"]}
    negatives = {"keywords": ["北境商队"]}
    assert is_pollutant(_fact("北境商队走失骆驼"), expect, negatives)
    assert not is_pollutant(_fact("西市火灾与北境商队无关"), expect, negatives)


def test_hash_eval_meets_documented_floor(tmp_path: Path) -> None:
    engine = build_engine(tmp_path / "eval.db")
    create_all(engine)
    with session_scope(engine) as session:
        report = run_retrieval_eval(session, default_golden_path(), embedder=HashEmbedding())
    assert report.embedder == "hash"
    assert report.indexed >= 8
    assert report.recall_at[1] >= HASH_MIN_RECALL_AT_1
    assert report.recall_at[3] >= HASH_MIN_RECALL_AT_3
    assert report.hit_rate >= HASH_MIN_HIT_RATE
    assert report.mrr >= HASH_MIN_MRR
    by_id = {row.id: row for row in report.queries}
    missing = [query_id for query_id in HASH_MUST_HIT_AT_3 if not by_id[query_id].recall_at[3]]
    assert missing == []


def test_eval_fails_when_expected_hit_is_broken(tmp_path: Path) -> None:
    raw = json.loads(default_golden_path().read_text(encoding="utf-8"))
    raw["queries"] = [
        {
            "id": "broken-impossible",
            "category": "entity",
            "query": "西市火灾",
            "expect": {"keywords": ["此关键词绝不该出现在语料里XYZ"]},
        }
    ]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    engine = build_engine(tmp_path / "eval.db")
    create_all(engine)
    with session_scope(engine) as session:
        report = run_retrieval_eval(session, broken, embedder=HashEmbedding())
    assert report.recall_at[3] == 0.0
    assert report.hit_rate == 0.0
    assert report.queries[0].first_relevant_rank is None


def test_eval_does_not_call_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("评测默认路径不得访问网络")

    monkeypatch.setattr(httpx, "post", _blocked)
    monkeypatch.setattr(httpx, "get", _blocked)
    engine = build_engine(tmp_path / "eval.db")
    create_all(engine)
    with session_scope(engine) as session:
        report = run_retrieval_eval(session, default_golden_path(), embedder=HashEmbedding())
    assert report.hit_rate >= 0.0
    text = format_report(report)
    assert "recall@3" in text
    assert "hash" in text


def test_retrieve_eval_cli_help_and_temp_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    help_result = CliRunner().invoke(app, ["retrieve-eval", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "retrieve-eval" in help_result.output

    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("NOVEL_EMBEDDING__PROVIDER", "mock")
    reset_settings_cache()
    out = tmp_path / "report.md"
    result = CliRunner().invoke(
        app,
        [
            "retrieve-eval",
            "--golden",
            str(default_golden_path()),
            "--out",
            str(out),
        ],
    )
    reset_settings_cache()
    assert result.exit_code == 0, result.output
    assert "recall@3" in result.output
    assert out.is_file()
    assert "recall@3" in out.read_text(encoding="utf-8")


def test_compare_real_refused_when_embedding_is_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("NOVEL_EMBEDDING__PROVIDER", "mock")
    reset_settings_cache()
    result = CliRunner().invoke(app, ["retrieve-eval", "--compare-real"])
    reset_settings_cache()
    assert result.exit_code == 2
    assert "拒绝" in result.output
    assert "compare-real" in result.output
