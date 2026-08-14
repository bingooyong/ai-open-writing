"""本地向量索引:默认 LanceDB(Spec 点名)。空项目不建表。"""

from __future__ import annotations

from pathlib import Path

import lancedb

from novel_agent.memory.embeddings import cosine, lexical_overlap
from novel_agent.memory.protocol import FactKind, MemoryFact


class LanceMemoryStore:
    """每项目一张表,reindex 时整表替换,保证幂等。"""

    def __init__(self, index_dir: Path) -> None:
        self._index_dir = index_dir
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(self._index_dir / "lancedb")

    def replace(self, project_id: int, facts: list[MemoryFact], vectors: list[list[float]]) -> int:
        if len(facts) != len(vectors):
            raise ValueError("facts 与 vectors 条数必须一致")
        name = self._table_name(project_id)
        if name in self._table_names():
            self._db.drop_table(name)
        if not facts:
            return 0
        rows = [
            {
                "fact_id": fact.fact_id,
                "text": fact.text,
                "kind": fact.kind.value,
                "source": fact.source,
                "provisional": fact.provisional,
                "vector": vector,
            }
            for fact, vector in zip(facts, vectors, strict=True)
        ]
        self._db.create_table(name, rows)
        return len(rows)

    def count(self, project_id: int) -> int:
        name = self._table_name(project_id)
        if name not in self._table_names():
            return 0
        return int(self._db.open_table(name).count_rows())

    def search(
        self,
        project_id: int,
        query: str,
        query_vector: list[float],
        *,
        limit: int,
        include_provisional: bool,
    ) -> list[MemoryFact]:
        name = self._table_name(project_id)
        if name not in self._table_names() or limit < 1:
            return []
        table = self._db.open_table(name)
        overfetch = max(limit * 4, 16)
        raw = table.search(query_vector).limit(overfetch).to_list()
        scored: list[MemoryFact] = []
        for row in raw:
            provisional = bool(row.get("provisional"))
            if provisional and not include_provisional:
                continue
            text = str(row.get("text") or "")
            if not text:
                continue
            vector = [float(item) for item in row.get("vector") or []]
            distance = float(row.get("_distance") or 0.0)
            vector_score = 1.0 / (1.0 + distance) if distance >= 0 else cosine(query_vector, vector)
            score = vector_score + lexical_overlap(query, text)
            scored.append(
                MemoryFact(
                    fact_id=str(row["fact_id"]),
                    text=text,
                    kind=FactKind(str(row["kind"])),
                    source=str(row.get("source") or ""),
                    provisional=provisional,
                    score=score,
                )
            )
        scored.sort(key=lambda fact: (-fact.score, fact.fact_id))
        return scored[:limit]

    def _table_names(self) -> set[str]:
        listed = self._db.list_tables()
        return set(listed.tables)

    @staticmethod
    def _table_name(project_id: int) -> str:
        return f"project_{project_id}"
