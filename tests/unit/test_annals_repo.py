from novel_agent.annals.taxonomy import seed_source
from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import AnnalsRepo, PlanningRepo
from novel_agent.domain.schemas.annals import AnnalsCover, YearCard


def test_cover_and_year_roundtrip_and_r6_complete(tmp_path) -> None:
    engine = build_engine(tmp_path / "annals.db")
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("年代志").id
        repo = AnnalsRepo(session)
        assert repo.get_cover(pid) is None
        assert repo.r6_complete(pid) is False
        repo.upsert_cover(
            pid,
            AnnalsCover(applicable=False),
            status="confirmed",
        )
        cover, status = repo.get_cover(pid)
        assert cover.applicable is False
        assert status == "confirmed"
        assert repo.r6_complete(pid) is True


def test_applicable_cover_requires_plot_hit_years(tmp_path) -> None:
    engine = build_engine(tmp_path / "annals2.db")
    create_all(engine)
    with session_scope(engine) as session:
        pid = PlanningRepo(session).create_project("导演").id
        repo = AnnalsRepo(session)
        repo.upsert_cover(
            pid,
            AnnalsCover(applicable=True, span_start=2005, span_end=2006, plot_hit_years=[2005]),
            status="confirmed",
        )
        assert repo.r6_complete(pid) is False
        repo.upsert_year(
            pid,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("x")]),
            status="pending",
        )
        repo.upsert_year(
            pid,
            YearCard(year=2006, density="thin", climate="c", sources=[seed_source("y")]),
            status="confirmed",
        )
        assert repo.r6_complete(pid) is False
        repo.upsert_year(
            pid,
            YearCard(year=2005, density="thick", climate="c", sources=[seed_source("x")]),
            status="confirmed",
        )
        assert repo.r6_complete(pid) is True
