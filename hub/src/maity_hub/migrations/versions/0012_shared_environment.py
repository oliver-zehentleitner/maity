"""The environment a session declared, and overlaps between members (docs/api.md §5.2, §5.3).

`agent_session.env_home` and `env_workspace` hold the declared ids, null for sessions
before this ran and for clients that send none. `environment_overlap` keeps one row per
pair of members that shared an environment, so `shared_environment_detected` is emitted
once per overlap and level rise.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("env_home", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("env_workspace", sa.String(length=16), nullable=True))
    op.create_table(
        "environment_overlap",
        sa.Column("member_a", sa.Integer(), nullable=False),
        sa.Column("member_b", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("announced", sa.String(length=16), nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("quiet_since", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["member_a"],
            ["membership.id"],
            name=op.f("fk_environment_overlap_member_a_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["member_b"],
            ["membership.id"],
            name=op.f("fk_environment_overlap_member_b_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_environment_overlap_project_id_project")
        ),
        sa.PrimaryKeyConstraint("member_a", "member_b", name=op.f("pk_environment_overlap")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_environment_overlap_member_b"), "environment_overlap", ["member_b"], unique=False
    )


def downgrade() -> None:
    # The table takes its index along; dropping the index first is refused by MariaDB,
    # which needs it for the foreign key on member_b.
    op.drop_table("environment_overlap")
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.drop_column("env_workspace")
        batch_op.drop_column("env_home")
