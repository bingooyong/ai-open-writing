"""默认 MemoryRetrieval:SQLite 真源 + 本地向量索引。"""

from __future__ import annotations

from sqlmodel import Session

from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.repos.production import ProductionRepo
from novel_agent.memory.collect import collect_indexable_facts
from novel_agent.memory.embeddings import EmbeddingProvider
from novel_agent.memory.protocol import MemoryFact
from novel_agent.memory.store import LanceMemoryStore


class LocalMemoryRetrieval:
    """索引不是第二本圣经:只镜像已落库的摘要/事实/场景/冲突/爽点。"""

    def __init__(
        self,
        session: Session,
        store: LanceMemoryStore,
        embedder: EmbeddingProvider,
    ) -> None:
        self._session = session
        self._store = store
        self._embedder = embedder

    def reindex(self, project_id: int, *, include_provisional: bool = False) -> int:
        # 提案态一并入库并由 retrieve(include_provisional=...) 过滤;参数保留以贴合协议。
        _ = include_provisional
        facts = collect_indexable_facts(
            project_id,
            PlanningRepo(self._session),
            CanonRepo(self._session),
            BibleRepo(self._session),
            ProductionRepo(self._session),
        )
        vectors = self._embedder.embed([fact.text for fact in facts]) if facts else []
        return self._store.replace(project_id, facts, vectors)

    def retrieve(
        self,
        project_id: int,
        query: str,
        *,
        limit: int = 8,
        include_provisional: bool = False,
        max_chars: int | None = None,
    ) -> list[MemoryFact]:
        cleaned = query.strip()
        if not cleaned or limit < 1:
            return []
        if self._store.count(project_id) == 0:
            self.reindex(project_id)
        query_vector = self._embedder.embed([cleaned])[0]
        hits = self._store.search(
            project_id,
            cleaned,
            query_vector,
            limit=limit,
            include_provisional=include_provisional,
        )
        if max_chars is None:
            return hits
        kept: list[MemoryFact] = []
        used = 0
        for fact in hits:
            extra = len(fact.text) + (1 if kept else 0)
            if used + extra > max_chars:
                continue
            kept.append(fact)
            used += extra
        return kept
