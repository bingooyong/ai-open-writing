"""Stage 1 slice 3: concept_judge 与项目 settings JSON 列

Revision ID: e7a1c3d5f902
Revises: c3e9a1b0d4f1
Create Date: 2026-08-13 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a1c3d5f902"
down_revision: str | Sequence[str] | None = "c3e9a1b0d4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("concept_judge", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("settings")
        batch_op.drop_column("concept_judge")
