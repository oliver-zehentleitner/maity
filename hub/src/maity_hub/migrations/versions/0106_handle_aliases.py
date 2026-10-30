"""Renameable handles with aliases (docs/api.md §6.24).

`handle_alias` keeps the handles an id gave up, `handle_change` counts the renames for the limit
of three in 24 hours, `handle_lock` is the per-handle lock a rename or a creation takes.

Revision ID: 0106
Revises: 0105
Create Date: 2026-10-28
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0106"
down_revision: str | None = "0105"
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
    op.create_table(
        "handle_alias",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=True),
        sa.Column("agent_id", sa.String(length=40), nullable=True),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("live", sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.CheckConstraint(
            "(human_id IS NULL) <> (agent_id IS NULL)", name=op.f("ck_handle_alias_one_id")
        ),
        sa.CheckConstraint("live IS NOT FALSE", name=op.f("ck_handle_alias_live_true_or_null")),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_handle_alias_human_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profile.id"], name=op.f("fk_handle_alias_agent_id_agent_profile")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_handle_alias")),
        sa.UniqueConstraint("scope", "handle", "live", name="uq_handle_alias_scope_handle"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "handle_change",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subject_id", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_handle_change")),
        **TABLE_OPTIONS,
    )
    op.create_index(op.f("ix_handle_change_subject_id"), "handle_change", ["subject_id"])
    op.create_table(
        "handle_lock",
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("scope", "handle", name=op.f("pk_handle_lock")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("handle_lock")
    op.drop_index(op.f("ix_handle_change_subject_id"), table_name="handle_change")
    op.drop_table("handle_change")
    op.drop_table("handle_alias")
