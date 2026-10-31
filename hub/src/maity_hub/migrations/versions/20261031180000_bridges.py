"""Bridges: an agent that lends its hands to another agent of the project (docs/api.md §2.3,
"The bridge").

`bridge` holds one row per connection, served and bridge as memberships, the purpose and whether
the two agents have different owners; an ended one keeps its row with `ended_at`, `ended_by` and
`end_reason`, and `live` NULL so the pair may connect again. A connection that waits for consent
is only its requests until both said `go`.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261031180000_bridges
Revises: 20261031150000_join_takes_over
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261031180000_bridges"
down_revision: str | None = "20261031150000_join_takes_over"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "bridge",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("served", sa.Integer(), nullable=False),
        sa.Column("bridge", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=200), nullable=False),
        sa.Column("cross_owner", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("ended_at", TIMESTAMP, nullable=True),
        sa.Column("ended_by", sa.String(length=40), nullable=True),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.Column("live", sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.CheckConstraint("served <> bridge", name=op.f("ck_bridge_not_self")),
        sa.CheckConstraint("live IS NOT FALSE", name=op.f("ck_bridge_live_true_or_null")),
        sa.ForeignKeyConstraint(
            ["bridge"], ["membership.id"], name=op.f("fk_bridge_bridge_membership")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_bridge_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["served"], ["membership.id"], name=op.f("fk_bridge_served_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bridge")),
        sa.UniqueConstraint("served", "bridge", "live", name=op.f("uq_bridge_served_bridge_live")),
        **MYSQL,
    )
    op.create_index(op.f("ix_bridge_bridge"), "bridge", ["bridge"])
    op.create_index(op.f("ix_bridge_project_id"), "bridge", ["project_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_bridge_project_id"), table_name="bridge")
    op.drop_index(op.f("ix_bridge_bridge"), table_name="bridge")
    op.drop_table("bridge")
