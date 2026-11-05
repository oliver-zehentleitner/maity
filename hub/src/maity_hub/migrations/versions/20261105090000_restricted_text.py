"""A card's restricted text (docs/api.md §6.4 "Restricted text", §6.1 `restricted_access`):
`task_restricted`, the text with its version, at most one per card; `task_restricted_history`,
who set or cleared it and when, never the text; and `restricted_event_list`, the private
list of readers a restricted-text event carries. No card had a restricted text before, so
nothing needs carrying over. The downgrade drops all three, and the texts with them.

Revision ID: 20261105090000_restricted_text
Revises: 20261105073000_cross_chats
Create Date: 2026-11-05
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from maity_hub.types import BIG_ID, UtcDateTime

revision: str = "20261105090000_restricted_text"
down_revision: str | None = "20261105073000_cross_chats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "task_restricted",
        sa.Column("task_id", sa.String(40), sa.ForeignKey("card.id"), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("text", sa.String(1000)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("membership.id"), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.Index("ix_task_restricted_project_id", "project_id"),
        **MYSQL,
    )
    op.create_table(
        "task_restricted_history",
        sa.Column("task_id", sa.String(40), sa.ForeignKey("card.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("author", sa.Integer(), sa.ForeignKey("membership.id"), nullable=False),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("task_id", "version"),
        sa.Index("ix_task_restricted_history_author_at", "author", "at"),
        **MYSQL,
    )
    op.create_table(
        "restricted_event_list",
        sa.Column("seq", BIG_ID, sa.ForeignKey("event.seq"), nullable=False),
        sa.Column("membership_id", sa.Integer(), sa.ForeignKey("membership.id"), nullable=False),
        sa.PrimaryKeyConstraint("seq", "membership_id"),
        sa.Index("ix_restricted_event_list_membership", "membership_id"),
        **MYSQL,
    )


def downgrade() -> None:
    # The tables alone: their indexes go with them, and dropping one first fails on MariaDB
    # while a foreign key needs it.
    op.drop_table("restricted_event_list")
    op.drop_table("task_restricted_history")
    op.drop_table("task_restricted")
