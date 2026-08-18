"""annals_card table for 年代志 R6

Revision ID: f8b2d4e6a103
Revises: e7a1c3d5f902
Create Date: 2026-08-18 05:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8b2d4e6a103"
down_revision: str | Sequence[str] | None = "e7a1c3d5f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annals_card",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("card_key", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "kind", "card_key"),
    )
    op.create_index("ix_annals_card_project_id", "annals_card", ["project_id"])
    op.create_index("ix_annals_card_kind", "annals_card", ["kind"])
    op.create_index("ix_annals_card_card_key", "annals_card", ["card_key"])
    op.create_index("ix_annals_card_year", "annals_card", ["year"])
    op.create_index("ix_annals_card_status", "annals_card", ["status"])


def downgrade() -> None:
    op.drop_index("ix_annals_card_status", table_name="annals_card")
    op.drop_index("ix_annals_card_year", table_name="annals_card")
    op.drop_index("ix_annals_card_card_key", table_name="annals_card")
    op.drop_index("ix_annals_card_kind", table_name="annals_card")
    op.drop_index("ix_annals_card_project_id", table_name="annals_card")
    op.drop_table("annals_card")
