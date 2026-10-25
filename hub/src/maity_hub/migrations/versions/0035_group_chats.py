"""Group chats (docs/api.md §9.2).

`conversation` holds a group chat: title, creator, whether the hub made it as a jour
fixe round's thread (§20.5), and when and why it closed. `conversation_participant`
holds each stay of a member in one: a member added again after leaving gets a new
row, whose `window_after` (the project's highest event seq at that join) starts what
it reads by default. `here` marks the open stay, at most one per member and chat
through the hub's at-most-one marker (true or NULL). Direct conversations keep living
in the event log alone; `conversation_read` serves both kinds.

Revision ID: 0035
Revises: 0039
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0035"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("hub_thread", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.Column("closed_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["membership.id"], name=op.f("fk_conversation_created_by_membership")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_conversation_project_id_project")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_conversation_project_id"), "conversation", ["project_id"], unique=False
    )
    op.create_table(
        "conversation_participant",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("joined_at", TIMESTAMP, nullable=False),
        sa.Column("window_after", BIG_ID, nullable=False),
        sa.Column("added_by", sa.String(length=40), nullable=True),
        sa.Column("left_at", TIMESTAMP, nullable=True),
        sa.Column("removed_by", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("here", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "here IS NOT FALSE", name=op.f("ck_conversation_participant_here_true_or_null")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_conversation_participant_conversation_id_conversation"),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_conversation_participant_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_participant")),
        sa.UniqueConstraint(
            "conversation_id",
            "membership_id",
            "here",
            name=op.f("uq_conversation_participant_one_stay"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_conversation_participant_conversation_id"),
        "conversation_participant",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_participant_membership_id"),
        "conversation_participant",
        ["membership_id"],
        unique=False,
    )


def downgrade() -> None:
    # The indexes go with their tables: MariaDB refuses to drop one a foreign key needs.
    op.drop_table("conversation_participant")
    op.drop_table("conversation")
