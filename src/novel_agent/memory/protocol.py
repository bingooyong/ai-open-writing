"""Stage 2 记忆检索协议(Spec D4 `memory_retrieval` 缝)。

检索是正史/规划的**索引**,不是第二本圣经。SQLite 仍是工作流与 canon 真源。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class FactKind(StrEnum):
    """可索引产物类别。只收录已提交(及可选提案态)摘要/事实,不收录密钥或 .env。"""

    SUMMARY = "summary"
    ENTITY = "entity"
    RELATIONSHIP = "relationship"
    SCENE = "scene"
    PAYOFF = "payoff"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """一条可注入上下文的检索命中。"""

    fact_id: str
    text: str
    kind: FactKind
    source: str
    provisional: bool = False
    score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "text": self.text,
            "kind": self.kind.value,
            "source": self.source,
            "provisional": self.provisional,
            "score": self.score,
        }


class MemoryRetrieval(Protocol):
    """ContextBuilder / CLI / 写作台共用的检索缝。默认实现为本地向量索引。"""

    def reindex(self, project_id: int, *, include_provisional: bool = False) -> int:
        """从 SQLite 真源重建项目索引。幂等:相同真源得到相同 fact_id 与条数。"""

    def retrieve(
        self,
        project_id: int,
        query: str,
        *,
        limit: int = 8,
        include_provisional: bool = False,
        max_chars: int | None = None,
    ) -> list[MemoryFact]:
        """按查询返回相关事实,稳定排序:分数降序,同分按 fact_id。"""
