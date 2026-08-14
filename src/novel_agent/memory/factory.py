"""从会话/配置装配默认检索实现。索引落在 SQLite 旁的 memory/ 目录。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from novel_agent.config import Settings, get_settings
from novel_agent.memory.embeddings import build_embedder
from novel_agent.memory.service import LocalMemoryRetrieval
from novel_agent.memory.store import LanceMemoryStore


def index_dir_for_session(session: Session, settings: Settings | None = None) -> Path:
    """优先跟会话绑定的 sqlite 文件走,避免测试写到开发库旁。"""
    bind = session.get_bind()
    database: str | None = None
    if isinstance(bind, Engine):
        raw = bind.url.database
        if isinstance(raw, str) and raw and raw != ":memory:":
            database = raw
    if database:
        return Path(database).resolve().parent / "memory"
    resolved = settings or get_settings()
    return Path(resolved.db_path).resolve().parent / "memory"


def memory_retrieval_for_session(
    session: Session, settings: Settings | None = None
) -> LocalMemoryRetrieval:
    resolved = settings or get_settings()
    store = LanceMemoryStore(index_dir_for_session(session, resolved))
    return LocalMemoryRetrieval(session, store, build_embedder(resolved.embedding))
