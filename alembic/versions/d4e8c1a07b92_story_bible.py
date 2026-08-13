"""Story Bible 表与 project.spark/brief 列

Revision ID: d4e8c1a07b92
Revises: af5362846a20
Create Date: 2026-08-13 12:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d4e8c1a07b92"
down_revision: str | Sequence[str] | None = "af5362846a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("spark", sa.String(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("brief", sa.String(), nullable=False, server_default=""))

    op.create_table(
        "structure_map",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version"),
    )
    with op.batch_alter_table("structure_map", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_structure_map_project_id"), ["project_id"], unique=False)

    op.create_table(
        "conflict",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("conflict_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "conflict_id"),
    )
    with op.batch_alter_table("conflict", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_conflict_conflict_id"), ["conflict_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_conflict_project_id"), ["project_id"], unique=False)

    op.create_table(
        "payoff_beat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("beat_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "beat_id"),
    )
    with op.batch_alter_table("payoff_beat", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_payoff_beat_beat_id"), ["beat_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_payoff_beat_order_index"), ["order_index"], unique=False)
        batch_op.create_index(batch_op.f("ix_payoff_beat_project_id"), ["project_id"], unique=False)

    op.create_table(
        "identity_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("canonical_character_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("alias", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "alias"),
    )
    with op.batch_alter_table("identity_alias", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_identity_alias_canonical_character_id"),
            ["canonical_character_id"],
            unique=False,
        )
        batch_op.create_index(batch_op.f("ix_identity_alias_project_id"), ["project_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("identity_alias", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_identity_alias_project_id"))
        batch_op.drop_index(batch_op.f("ix_identity_alias_canonical_character_id"))
    op.drop_table("identity_alias")

    with op.batch_alter_table("payoff_beat", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_payoff_beat_project_id"))
        batch_op.drop_index(batch_op.f("ix_payoff_beat_order_index"))
        batch_op.drop_index(batch_op.f("ix_payoff_beat_beat_id"))
    op.drop_table("payoff_beat")

    with op.batch_alter_table("conflict", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conflict_project_id"))
        batch_op.drop_index(batch_op.f("ix_conflict_conflict_id"))
    op.drop_table("conflict")

    with op.batch_alter_table("structure_map", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_structure_map_project_id"))
    op.drop_table("structure_map")

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("brief")
        batch_op.drop_column("spark")
