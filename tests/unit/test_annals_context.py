from novel_agent.annals.slice import annals_slice_for_chapter, title_fence  # noqa: F401
from novel_agent.annals.taxonomy import METHOD_LIBRARY_EXAMPLES
from novel_agent.domain.schemas.annals import MethodLibraryCard


def test_title_fence_2005_includes_buried_not_1997() -> None:
    methods = list(METHOD_LIBRARY_EXAMPLES) + [
        MethodLibraryCard(
            film_title="黑洞",
            release_year=1997,
            speak_as_existing_from_year=1997,
            craft="x",
        ),
    ]
    fence = title_fence(methods, 2005)
    assert "活埋" in fence
    assert "小偷家族" in fence
    assert "黑洞" not in fence


def test_builder_not_applicable_allows_linan(tmp_path) -> None:
    from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

    from novel_agent.annals.skeleton import ensure_annals_cover
    from novel_agent.context import ContextBuilder
    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.repos import AnnalsRepo, CanonRepo, PlanningRepo
    from novel_agent.domain.schemas import (
        ChapterOutline,
        CharacterCard,
        PlotUnitCard,
        SceneCard,
        StoryKernel,
    )

    engine = build_engine(tmp_path / "ctx.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("上下文测试", boundaries=["项目边界"])
        planning.save_kernel(project.id, StoryKernel.model_validate(KERNEL))
        planning.approve_kernel(project.id, 1)
        planning.upsert_character(project.id, CharacterCard.model_validate(CHARACTER))
        planning.save_volume(project.id, "v1", {"summary": "第一卷摘要"})
        planning.save_unit(project.id, "v1", PlotUnitCard.model_validate(UNIT))
        planning.create_chapter(project.id, ChapterOutline.model_validate(OUTLINE), order_index=1)
        planning.save_scene_cards(project.id, "v1c001", [SceneCard.model_validate(SCENE)])
        ensure_annals_cover(
            planning, AnnalsRepo(session), project.id, auto_not_applicable_only=True
        )
        package = ContextBuilder(planning, CanonRepo(session)).build(
            project.id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要"
        )
        assert package.annals.applicable is False


def test_builder_applicable_missing_year_card_raises(tmp_path) -> None:
    from test_schemas import CHARACTER, KERNEL, OUTLINE, SCENE, UNIT

    from novel_agent.annals.taxonomy import METHOD_LIBRARY_EXAMPLES, seed_source
    from novel_agent.context import ContextBuilder
    from novel_agent.domain.db import build_engine, create_all, session_scope
    from novel_agent.domain.repos import AnnalsRepo, CanonRepo, PlanningRepo
    from novel_agent.domain.schemas import (
        ChapterOutline,
        CharacterCard,
        PlotUnitCard,
        SceneCard,
        StoryKernel,
    )
    from novel_agent.domain.schemas.annals import AnnalsCover, YearCard

    engine = build_engine(tmp_path / "ctx2.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        project = planning.create_project("导演", boundaries=["项目边界"])
        kernel = dict(KERNEL)
        kernel["logline"] = KERNEL["logline"] + " 2005年"
        planning.save_kernel(project.id, StoryKernel.model_validate(kernel))
        planning.approve_kernel(project.id, 1)
        planning.upsert_character(project.id, CharacterCard.model_validate(CHARACTER))
        planning.save_volume(project.id, "v1", {"summary": "第一卷摘要"})
        planning.save_unit(project.id, "v1", PlotUnitCard.model_validate(UNIT))
        outline = dict(OUTLINE)
        outline["time_location"] = "2005秋,北影厂"
        planning.create_chapter(project.id, ChapterOutline.model_validate(outline), order_index=1)
        planning.save_scene_cards(project.id, "v1c001", [SceneCard.model_validate(SCENE)])
        annals = AnnalsRepo(session)
        annals.upsert_cover(
            project.id,
            AnnalsCover(applicable=True, span_start=2005, span_end=2005, plot_hit_years=[2005]),
            status="confirmed",
        )
        builder = ContextBuilder(planning, CanonRepo(session))
        try:
            builder.build(project.id, "v1c001", task_brief="写第一章", volume_summary="第一卷摘要")
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "年代志" in str(exc) or "故事年" in str(exc)
        annals.upsert_year(
            project.id,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("x")]),
            status="confirmed",
        )
        annals.replace_methods(project.id, list(METHOD_LIBRARY_EXAMPLES), status="confirmed")
        package = builder.build(
            project.id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            retrieval_facts=["a" * 40, "b" * 40],
        )
        assert package.annals.applicable is True
        assert package.annals.story_year == 2005
        assert "活埋" in package.annals.title_fence
        fence = list(package.annals.title_fence)
        required = builder.required_size(package)
        trimmed = builder.build(
            project.id,
            "v1c001",
            task_brief="写第一章",
            volume_summary="第一卷摘要",
            retrieval_facts=["a" * 40, "b" * 40],
            max_chars=required + 10,
        )
        assert trimmed.annals.title_fence == fence
