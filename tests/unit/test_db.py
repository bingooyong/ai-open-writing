"""M1.2 冒烟:建表、WAL、round-trip、约束生效。"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.models import ChapterRecord, ProjectRecord
from novel_agent.domain.schemas.base import ChapterStatus


@pytest.fixture()
def engine(tmp_path):
    e = build_engine(tmp_path / "t.db")
    create_all(e)
    return e


def test_wal_enabled(engine) -> None:
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_chapter_roundtrip_and_unique(engine) -> None:
    with session_scope(engine) as s:
        p = ProjectRecord(title="测试作品")
        s.add(p)
        s.flush()
        s.add(
            ChapterRecord(
                project_id=p.id,
                chapter_key="v1c001",
                volume_id="v1",
                unit_id="u1",
                order_index=1,
                target_words=3000,
            )
        )

    with session_scope(engine) as s:
        ch = s.exec(select(ChapterRecord).where(ChapterRecord.chapter_key == "v1c001")).one()
        assert ch.status == ChapterStatus.PLANNED
        assert ch.revision_round == 0
        pid = ch.project_id

    # 唯一约束 (project_id, chapter_key)
    with pytest.raises(IntegrityError), session_scope(engine) as s:
        s.add(
            ChapterRecord(
                project_id=pid,
                chapter_key="v1c001",
                volume_id="v1",
                unit_id="u1",
                order_index=2,
            )
        )
