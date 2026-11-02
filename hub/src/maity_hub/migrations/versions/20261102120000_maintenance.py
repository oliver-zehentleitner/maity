"""Maintenance windows (docs/api.md §16.12): the window, every change of it kept for good, and
each human's choice which of its agents receive the hub's broadcasts.

Revision ID: 20261102120000_maintenance
Revises: 20261102110000_card_note_edited
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from maity_hub.types import JSON_VALUE

revision: str = "20261102120000_maintenance"
down_revision: str | None = "20261102110000_card_note_edited"
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
        "maintenance_window",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("starts_at", TIMESTAMP, nullable=False),
        sa.Column("ends_at", TIMESTAMP, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("cancelled_at", TIMESTAMP, nullable=True),
        sa.Column("settled_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["human.id"], name=op.f("fk_maintenance_window_created_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["human.id"], name=op.f("fk_maintenance_window_updated_by_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_window")),
        **MYSQL,
    )
    op.create_index("ix_maintenance_window_ends_at", "maintenance_window", ["ends_at"])
    op.create_table(
        "maintenance_change",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("window_id", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("starts_at", TIMESTAMP, nullable=False),
        sa.Column("ends_at", TIMESTAMP, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("by", sa.String(length=40), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["maintenance_window.id"],
            name=op.f("fk_maintenance_change_window_id_maintenance_window"),
        ),
        sa.ForeignKeyConstraint(["by"], ["human.id"], name=op.f("fk_maintenance_change_by_human")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_change")),
        **MYSQL,
    )
    op.create_index("ix_maintenance_change_at", "maintenance_change", ["at"])
    with op.batch_alter_table("human") as batch:
        batch.add_column(sa.Column("broadcasts", JSON_VALUE))


def downgrade() -> None:
    with op.batch_alter_table("human") as batch:
        batch.drop_column("broadcasts")
    op.drop_table("maintenance_change")
    op.drop_table("maintenance_window")
