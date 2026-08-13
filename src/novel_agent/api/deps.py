"""FastAPI 依赖:会话与配置。"""

from collections.abc import Generator

from fastapi import HTTPException, Request
from sqlalchemy.orm.exc import NoResultFound
from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.domain.models import ChapterRecord, ProjectRecord
from novel_agent.domain.repos.planning import PlanningRepo


def get_session(request: Request) -> Generator[Session, None, None]:
    session = Session(request.app.state.engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_app_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("应用未注入 Settings")
    return settings


def require_project(planning: PlanningRepo, project_id: int) -> ProjectRecord:
    try:
        return planning.get_project(project_id)
    except NoResultFound as exc:
        raise HTTPException(status_code=404, detail=f"项目不存在 project_id={project_id}") from exc


def require_chapter(
    planning: PlanningRepo, project_id: int, chapter_key: str
) -> ChapterRecord:
    try:
        return planning.get_chapter(project_id, chapter_key)
    except NoResultFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"章节不存在 project_id={project_id} chapter_key={chapter_key}",
        ) from exc
