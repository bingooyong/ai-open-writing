"""数据库引擎与会话(SQLite WAL,Spec §9)。"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from novel_agent.config import get_settings

_engine: Engine | None = None


def build_engine(db_path: Path) -> Engine:
    """创建 engine 并启用 WAL/外键。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _record) -> None:  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine(get_settings().db_path)
    return _engine


def set_engine(engine: Engine) -> None:
    """测试注入用。"""
    global _engine
    _engine = engine


def create_all(engine: Engine) -> None:
    """建表(测试/初始化用;生产迁移走 Alembic)。"""
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """事务边界:成功提交,异常回滚。"""
    s = Session(engine or get_engine())
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
