"""The history of a human's allow and deny entries (docs/api.md §9.6, "History").

One row per change of an entry and per answer to the request to chat with the human's agents,
numbered in the order written (`n`), the item as stored in `data`. A per-human table: deleted
with the account, in its export. A new table: nothing to carry over, and no backfill, since the
stored entries and requests do not say how an entry came about or what an answer ticked.

Revision ID: 20261118180000_access_history
Revises: 20261117230000_limit_override
Create Date: 2026-11-18
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE, UtcDateTime

revision: str = "20261118180000_access_history"
down_revision: str | None = "20261117230000_limit_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "chat_access_history",
        sa.Column("n", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("entry_id", sa.String(length=40), nullable=True),
        sa.Column("data", JSON_VALUE, nullable=False),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('entry', 'answer')", name=op.f("ck_chat_access_history_kind")),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_chat_access_history_human_id_human")
        ),
        sa.PrimaryKeyConstraint("n", name=op.f("pk_chat_access_history")),
        sa.UniqueConstraint("id", name=op.f("uq_chat_access_history_id")),
        sqlite_autoincrement=True,
        **MYSQL,
    )
    op.create_index(
        "ix_chat_access_history_human", "chat_access_history", ["human_id", "n"], unique=False
    )


def downgrade() -> None:
    # The table alone: no index of another table goes, so no foreign key loses its index.
    op.drop_index("ix_chat_access_history_human", table_name="chat_access_history")
    op.drop_table("chat_access_history")
