import pytest
from test_schemas import KERNEL, OUTLINE

from novel_agent.annals.skeleton import ensure_annals_cover
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import AnnalsRepo, PlanningRepo
from novel_agent.domain.schemas import ChapterOutline, StoryKernel
from novel_agent.planning.chain import PlanningError
from novel_agent.planning.rounds import confirm_round


def test_ensure_cover_auto_not_applicable(tmp_path) -> None:
    engine = build_engine(tmp_path / "r6.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("说书人传奇").id
        planning.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(pid, 1)
        planning.create_chapter(pid, ChapterOutline.model_validate(OUTLINE), order_index=1)
        cover = ensure_annals_cover(
            planning, AnnalsRepo(session), pid, auto_not_applicable_only=True
        )
        assert cover is not None
        assert cover.applicable is False
        assert AnnalsRepo(session).r6_complete(pid) is True


def test_ensure_cover_does_not_invent_era_years(tmp_path) -> None:
    engine = build_engine(tmp_path / "r6era.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("导演").id
        kernel = dict(KERNEL)
        kernel["logline"] = KERNEL["logline"] + " 2005年"
        planning.save_kernel(pid, StoryKernel.model_validate(kernel))
        planning.approve_kernel(pid, 1)
        outline = dict(OUTLINE)
        outline["time_location"] = "2005秋,北影厂"
        planning.create_chapter(pid, ChapterOutline.model_validate(outline), order_index=1)
        cover = ensure_annals_cover(
            planning, AnnalsRepo(session), pid, auto_not_applicable_only=True
        )
        assert cover is None
        assert AnnalsRepo(session).r6_complete(pid) is False


async def test_confirm_round_rejects_index_7(tmp_path) -> None:
    engine = build_engine(tmp_path / "r6bound.db")
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("越界").id
        with pytest.raises(PlanningError, match="0–6"):
            await confirm_round(session, None, pid, 7, "火花")
