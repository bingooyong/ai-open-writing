"""Story Bible 待确认轮次 JSON 列

Revision ID: c3e9a1b0d4f1
Revises: d4e8c1a07b92
Create Date: 2026-08-13 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e9a1b0d4f1"
down_revision: str | Sequence[str] | None = "d4e8c1a07b92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bible_pending", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("bible_pending")
