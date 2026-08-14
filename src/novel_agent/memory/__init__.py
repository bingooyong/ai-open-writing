"""Stage 2 记忆检索:协议缝 + 本地向量索引(默认 LanceDB)。"""

from novel_agent.memory.factory import memory_retrieval_for_session
from novel_agent.memory.protocol import FactKind, MemoryFact, MemoryRetrieval
from novel_agent.memory.service import LocalMemoryRetrieval

__all__ = [
    "FactKind",
    "LocalMemoryRetrieval",
    "MemoryFact",
    "MemoryRetrieval",
    "memory_retrieval_for_session",
]
