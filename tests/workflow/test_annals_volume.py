from tests.workflow.test_chapter_loop import _planned

from novel_agent.annals.skeleton import extend_annals_for_outlines
from novel_agent.annals.taxonomy import METHOD_LIBRARY_EXAMPLES, seed_source
from novel_agent.config import Settings
from novel_agent.context import ContextBuilder
from novel_agent.domain.repos import AnnalsRepo, CanonRepo, PlanningRepo
from novel_agent.domain.schemas.annals import AnnalsCover, YearCard
from novel_agent.production.volume_run import VolumeStopReason, run_volume


async def _planned_era(tmp_path):
    session, deps, mock, project_id = await _planned(tmp_path)
    planning = PlanningRepo(session)
    chapter = planning.get_chapter(project_id, "v1c001")
    outline = dict(chapter.outline)
    outline["time_location"] = "2005秋,北影厂"
    chapter.outline = outline
    session.add(chapter)
    kernel = planning.get_approved_kernel(project_id)
    assert kernel is not None
    patched = kernel.model_copy(update={"logline": kernel.logline + " 2005年"})
    rec = planning.save_kernel(project_id, patched)
    planning.approve_kernel(project_id, rec.version)
    annals = AnnalsRepo(session)
    existing = annals.get_cover(project_id)
    if existing is not None:
        cover, _status = existing
        if not cover.applicable:
            annals.upsert_cover(
                project_id,
                AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
                status="pending",
            )
    session.commit()
    return session, deps, mock, project_id


def _confirm_2005_cover(session, project_id: int) -> None:
    annals = AnnalsRepo(session)
    annals.upsert_cover(
        project_id,
        AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
        status="confirmed",
    )
    annals.upsert_year(
        project_id,
        YearCard(
            year=2005,
            density="thick",
            climate="厂里还在用胶片",
            sources=[seed_source("2005")],
        ),
        status="confirmed",
    )
    annals.replace_methods(project_id, list(METHOD_LIBRARY_EXAMPLES), status="confirmed")
    session.commit()


async def test_era_project_without_year_card_stops_needs_annals(tmp_path) -> None:
    """R5 outlines with years cannot volume_run until R6 plot-hit cards are confirmed."""
    session, deps, mock, project_id = await _planned_era(tmp_path)
    settings = Settings(_env_file=None)
    result = await run_volume(
        session, deps, project_id, budget_usd=50.0, yes=True, settings=settings, max_chapters=1
    )
    assert result.stop_reason == VolumeStopReason.NEEDS_ANNALS
    assert result.chapters_done == 0


async def test_not_applicable_project_still_volume_runs(tmp_path) -> None:
    session, deps, mock, project_id = await _planned(tmp_path)  # 临安, from test_chapter_loop
    settings = Settings(_env_file=None)
    result = await run_volume(
        session, deps, project_id, budget_usd=50.0, yes=True, settings=settings, max_chapters=1
    )
    assert result.stop_reason != VolumeStopReason.NEEDS_ANNALS


async def test_confirmed_2005_slice_fences_buried(tmp_path) -> None:
    session, deps, mock, project_id = await _planned_era(tmp_path)
    _confirm_2005_cover(session, project_id)
    package = ContextBuilder(PlanningRepo(session), CanonRepo(session)).build(
        project_id, "v1c001", task_brief="t", volume_summary="v"
    )
    assert package.annals.applicable is True
    assert package.annals.story_year == 2005
    assert "活埋" in package.annals.title_fence


def test_plan_more_new_year_is_pending(tmp_path) -> None:
    from test_schemas import KERNEL, OUTLINE

    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.schemas import ChapterOutline, StoryKernel

    engine = build_engine(tmp_path / "extend.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        pid = planning.create_project("导演").id
        kernel = dict(KERNEL)
        kernel["logline"] = KERNEL["logline"] + " 2005年"
        planning.save_kernel(pid, StoryKernel.model_validate(kernel))
        planning.approve_kernel(pid, 1)
        first = dict(OUTLINE)
        first["time_location"] = "2005秋"
        planning.create_chapter(pid, ChapterOutline.model_validate(first), order_index=1)
        later = dict(OUTLINE)
        later["chapter_key"] = "v1c002"
        later["time_location"] = "2009春"
        planning.create_chapter(pid, ChapterOutline.model_validate(later), order_index=2)
        annals = AnnalsRepo(session)
        annals.upsert_cover(
            pid,
            AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
            status="confirmed",
        )
        annals.upsert_year(
            pid,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("2005")]),
            status="confirmed",
        )
        extend_annals_for_outlines(planning, annals, pid)
        got = annals.get_year(pid, 2009)
        assert got is not None
        card, status = got
        assert card.year == 2009
        assert status == "pending"
        assert annals.r6_complete(pid) is False
