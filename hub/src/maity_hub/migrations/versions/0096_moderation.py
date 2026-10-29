"""Moderation (docs/api.md §16.8): the holds that `hide` and `remove` leave on a target, an
account's suspension, and the report an event's change was made for (actor
`{kind: "moderation", report_id}`).

Revision ID: 0096
Revises: 0097
Create Date: 2026-10-29
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0096"
down_revision: str | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "moderation_hold",
        sa.Column("report_id", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["abuse_report.id"],
            name=op.f("fk_moderation_hold_report_id_abuse_report"),
        ),
        sa.PrimaryKeyConstraint("report_id", name=op.f("pk_moderation_hold")),
        **OPTIONS,
    )
    op.create_index(
        "ix_moderation_hold_target", "moderation_hold", ["target_type", "target_id"], unique=False
    )
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(sa.Column("suspended_at", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("suspended_report", sa.String(length=40), nullable=True))
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.add_column(sa.Column("actor_report_id", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.drop_column("actor_report_id")
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("suspended_report")
        batch_op.drop_column("suspended_at")
    # The table goes with its index, as 0095 does: MariaDB keeps an index a foreign key needs.
    op.drop_table("moderation_hold")
