import pytest
from test_schemas import KERNEL, OUTLINE

from novel_agent.annals.skeleton import (
    AnnalsSkeleton,
    chapter_needs_annals,
    ensure_annals_cover,
    extend_annals_for_outlines,
    overlay_confirmed_years,
)
from novel_agent.annals.taxonomy import seed_source
from novel_agent.config import Settings
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import AnnalsRepo, PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterOutline, ChapterStatus, StoryKernel
from novel_agent.domain.schemas.annals import AnnalsCover, YearCard
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.planning.chain import PlanningError
from novel_agent.planning.rounds import _generate_artifact, confirm_round
from novel_agent.runtime.agents import AgentDeps


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


def test_not_applicable_cover_reopens_when_chapter_gains_year(tmp_path) -> None:
    engine = build_engine(tmp_path / "r6reopen.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("说书人传奇").id
        planning.save_kernel(pid, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(pid, 1)
        planning.create_chapter(pid, ChapterOutline.model_validate(OUTLINE), order_index=1)
        annals = AnnalsRepo(session)
        cover = ensure_annals_cover(planning, annals, pid, auto_not_applicable_only=True)
        assert cover is not None
        assert cover.applicable is False
        assert chapter_needs_annals(planning, annals, pid, "v1c001") is False

        later = dict(OUTLINE)
        later["chapter_key"] = "v1c002"
        later["time_location"] = "2005秋"
        planning.create_chapter(pid, ChapterOutline.model_validate(later), order_index=2)
        assert chapter_needs_annals(planning, annals, pid, "v1c002") is True
        assert chapter_needs_annals(planning, annals, pid, "v1c001") is False

        extend_annals_for_outlines(planning, annals, pid)
        got = annals.get_cover(pid)
        assert got is not None
        new_cover, status = got
        assert new_cover.applicable is True
        assert status == "pending"
        year = annals.get_year(pid, 2005)
        assert year is not None
        card, year_status = year
        assert card.year == 2005
        assert year_status == "pending"
        assert card.climate == ""
        assert annals.r6_complete(pid) is False


def test_overlay_confirmed_years_keeps_sourced_climate(tmp_path) -> None:
    engine = build_engine(tmp_path / "overlay.db")
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("导演").id
        annals = AnnalsRepo(session)
        annals.upsert_year(
            pid,
            YearCard(year=2005, density="thick", climate="胶片", sources=[seed_source("2005")]),
            status="confirmed",
        )
        rebuilt = AnnalsSkeleton(
            cover=AnnalsCover(
                applicable=True, span_start=2005, span_end=2006, plot_hit_years=[2005]
            ),
            year_cards=[
                YearCard(year=2005, density="thick", climate=""),
                YearCard(year=2006, density="thin", climate=""),
            ],
        )
        out = overlay_confirmed_years(rebuilt, annals, pid)
        by_year = {card.year: card for card in out.year_cards}
        assert by_year[2005].climate == "胶片"
        assert by_year[2006].climate == ""


async def test_r6_generate_scans_locked_drafts(tmp_path) -> None:
    engine = build_engine(tmp_path / "r6lock.db")
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
        planning.set_status(pid, "v1c001", ChapterStatus.CANON_LOCKED)
        ProductionRepo(session).create_draft(
            pid,
            "v1c001",
            "candidate_1",
            "lin1",
            "柏林一种关注放映前夜，戛纳年初的雨",
            {},
            "p",
            1,
        )
        deps = AgentDeps(
            gateway=ModelGateway(Settings(_env_file=None), session, {"mock": MockProvider()}),
            project_id=pid,
        )
        artifact = await _generate_artifact(session, deps, pid, "火花", 6, "v1", 5)
        blob = " ".join(item["issue"] for item in artifact.get("debts") or [])
        assert "柏林一种关注" in blob
        assert "年初" in blob
