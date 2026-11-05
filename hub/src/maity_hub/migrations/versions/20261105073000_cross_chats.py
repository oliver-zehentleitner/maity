"""Cross-project group chats (docs/api.md §9.5).

A room one human holds for agent profiles they own. It is not a project, so its
messages are rows of their own and not events. A `cross_chat_mention` is still one
project event; its author, when an agent profile that is no member of that project,
is `actor_agent_id` with `actor_instance`.

Revision ID: 20261105073000_cross_chats
Revises: 20261104150000_report_request
Create Date: 2026-11-05
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from maity_hub.types import BIG_ID, JSON_VALUE, MARKDOWN_TEXT

revision: str = "20261105073000_cross_chats"
down_revision: str | None = "20261104150000_report_request"
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
    op.add_column("event", sa.Column("actor_agent_id", sa.String(length=40), nullable=True))
    op.add_column("event", sa.Column("actor_instance", sa.String(length=5), nullable=True))
    op.create_table(
        "cross_chat",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.Column("closed_reason", sa.String(length=32), nullable=True),
        sa.Column("last_message_at", TIMESTAMP, nullable=True),
        sa.Column("next_seq", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["human.id"], name=op.f("fk_cross_chat_created_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["human.id"], name=op.f("fk_cross_chat_owner_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cross_chat")),
        **MYSQL,
    )
    op.create_index(op.f("ix_cross_chat_owner_id"), "cross_chat", ["owner_id"])
    op.create_table(
        "cross_chat_participant",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("member_id", sa.String(length=40), nullable=False),
        sa.Column("joined_at", TIMESTAMP, nullable=False),
        sa.Column("window_after", BIG_ID, nullable=False),
        sa.Column("added_by", sa.String(length=40), nullable=True),
        sa.Column("left_at", TIMESTAMP, nullable=True),
        sa.Column("removed_by", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("here", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "here IS NOT FALSE", name=op.f("ck_cross_chat_participant_here_true_or_null")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["cross_chat.id"],
            name=op.f("fk_cross_chat_participant_conversation_id_cross_chat"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cross_chat_participant")),
        sa.UniqueConstraint(
            "conversation_id",
            "member_id",
            "here",
            name="uq_cross_chat_participant_one_stay",
        ),
        **MYSQL,
    )
    op.create_index(
        op.f("ix_cross_chat_participant_conversation_id"),
        "cross_chat_participant",
        ["conversation_id"],
    )
    op.create_index(
        op.f("ix_cross_chat_participant_member_id"), "cross_chat_participant", ["member_id"]
    )
    op.create_table(
        "cross_chat_message",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("seq", BIG_ID, nullable=False),
        sa.Column("author_id", sa.String(length=40), nullable=False),
        sa.Column("from_instance", sa.String(length=5), nullable=True),
        sa.Column("body", MARKDOWN_TEXT, nullable=True),
        sa.Column("sent_at", TIMESTAMP, nullable=False),
        sa.Column("mentions", JSON_VALUE, nullable=False),
        sa.Column("redacted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("redaction", JSON_VALUE, nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["cross_chat.id"],
            name=op.f("fk_cross_chat_message_conversation_id_cross_chat"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cross_chat_message")),
        sa.UniqueConstraint(
            "conversation_id", "seq", name="uq_cross_chat_message_conversation_id_seq"
        ),
        **MYSQL,
    )
    op.create_table(
        "cross_chat_read",
        sa.Column("member_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("last_seq", BIG_ID, nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["cross_chat.id"],
            name=op.f("fk_cross_chat_read_conversation_id_cross_chat"),
        ),
        sa.PrimaryKeyConstraint("member_id", "conversation_id", name=op.f("pk_cross_chat_read")),
        **MYSQL,
    )
    op.create_index(
        op.f("ix_cross_chat_read_conversation_id"), "cross_chat_read", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("cross_chat_read")
    op.drop_table("cross_chat_message")
    op.drop_table("cross_chat_participant")
    op.drop_index(op.f("ix_cross_chat_owner_id"), table_name="cross_chat")
    op.drop_table("cross_chat")
    op.drop_column("event", "actor_instance")
    op.drop_column("event", "actor_agent_id")
