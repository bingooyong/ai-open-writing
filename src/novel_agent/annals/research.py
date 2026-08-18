from __future__ import annotations

from typing import Protocol

import httpx

from novel_agent.domain.schemas.annals import SourceRef


class ResearchPort(Protocol):
    def lookup(self, query: str) -> list[SourceRef]: ...


class NullResearchPort:
    def lookup(self, query: str) -> list[SourceRef]:
        return []


class WebResearchPort:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)

    def lookup(self, query: str) -> list[SourceRef]:
        q = (query or "").strip()
        if not q:
            return []
        try:
            if q.startswith("http://") or q.startswith("https://"):
                response = self._client.get(q)
                response.raise_for_status()
                excerpt = (response.text or "")[:240]
                if not excerpt:
                    return []
                return [SourceRef(url=q, excerpt=excerpt)]
            response = self._client.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": q, "limit": 1, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        if not isinstance(payload, list) or len(payload) < 4:
            return []
        titles, snippets, urls = payload[1], payload[2], payload[3]
        if not titles or not urls:
            return []
        excerpt = snippets[0] if snippets else ""
        if not urls[0]:
            return []
        return [SourceRef(url=str(urls[0]), excerpt=str(excerpt or titles[0])[:240])]
