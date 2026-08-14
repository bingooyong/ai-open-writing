from test_schemas import OUTLINE

from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos import PlanningRepo, ProductionRepo
from novel_agent.domain.schemas import ChapterOutline, ChapterStatus
from novel_agent.production.review import list_review_desk


def test_list_review_desk_includes_any_chapter_with_draft_text(tmp_path) -> None:
    engine = build_engine(tmp_path / "review-desk.db")
    create_all(engine)
    with session_scope(engine) as session:
        planning = PlanningRepo(session)
        production = ProductionRepo(session)
        project_id = planning.create_project("余烬回声").id
        planning.create_chapter(
            project_id,
            ChapterOutline.model_validate({**OUTLINE, "title": "开场"}),
            order_index=1,
        )
        assert list_review_desk(session, project_id) == []

        production.create_draft(
            project_id,
            "v1c001",
            "candidate_1",
            "lin1",
            "茶楼灯火。\n\n苏晚生开口。",
            {},
            "w1",
            1,
        )
        planned = list_review_desk(session, project_id)
        assert len(planned) == 1
        assert planned[0]["status"] == "PLANNED"
        assert planned[0]["bucket"] == "IN_PROGRESS"
        assert planned[0]["order_index"] == 1
        assert planned[0]["heading"] == "第1章 开场"
        assert "茶楼" in str(planned[0]["draft_text"])

        planning.set_status(project_id, "v1c001", ChapterStatus.JUDGING)
        judging = list_review_desk(session, project_id)[0]
        assert judging["status"] == "JUDGING"
        assert judging["bucket"] == "IN_PROGRESS"
        assert "苏晚生" in str(judging["draft_text"])

        planning.set_status(project_id, "v1c001", ChapterStatus.NEEDS_REPLAN)
        replan = list_review_desk(session, project_id)[0]
        assert replan["status"] == "NEEDS_REPLAN"
        assert "茶楼" in str(replan["draft_text"])
