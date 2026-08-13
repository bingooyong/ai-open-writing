"""项目级 Stage 1 开关:Writer B / Reader Advocate;Source Reviewer 仅在有来源表时启用。"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlmodel import Session

from novel_agent.domain.models import ProjectRecord
from novel_agent.domain.schemas import ReviewerRole

BASE_REVIEW_ROLES = (
    ReviewerRole.RED_TEAM,
    ReviewerRole.PLOT,
    ReviewerRole.CHARACTER,
    ReviewerRole.CONTINUITY,
    ReviewerRole.PROSE,
)


def desk_settings(project: ProjectRecord) -> dict[str, bool]:
    raw = project.settings if isinstance(project.settings, dict) else {}
    return {
        "enable_writer_b": bool(raw.get("enable_writer_b", True)),
        "enable_reader_advocate": bool(raw.get("enable_reader_advocate", True)),
    }


def has_source_record_table(session: Session) -> bool:
    """Stage 1 不建 source_record;有表才启用 Source Reviewer,不另设计存储。"""
    bind = session.get_bind()
    return "source_record" in inspect(bind).get_table_names()


def review_roles_for(session: Session, project: ProjectRecord) -> list[ReviewerRole]:
    roles = list(BASE_REVIEW_ROLES)
    if desk_settings(project)["enable_reader_advocate"]:
        roles.append(ReviewerRole.READER_ADVOCATE)
    if has_source_record_table(session):
        roles.append(ReviewerRole.SOURCE)
    return roles
