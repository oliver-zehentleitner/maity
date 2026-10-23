"""Notifications: account records, read marks, stored positions and watches (docs/api.md
§18.1–§18.3, §6.4).

`account_record` holds audit records about one human's own account, numbered in a
sequence of their own, never the event sequence. `notification_read` holds a human's
read marks on items from events. `notification_position` holds the vector behind a
position handle when the inline form would not fit. `card_watch` holds a human's own
watch on a card, by membership.

Revision ID: 0034
Revises: 0028
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0034"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def _human(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["human_id"], ["human.id"], name=op.f(f"fk_{table}_human_id_human")
    )


def upgrade() -> None:
    op.create_table(
        "account_record",
        sa.Column("n", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("data", JSON_VALUE, nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.Column("read_at", TIMESTAMP, nullable=True),
        sa.Column("read_by", sa.String(length=40), nullable=True),
        _human("account_record"),
        sa.PrimaryKeyConstraint("n", name=op.f("pk_account_record")),
        sqlite_autoincrement=True,
        **TABLE_OPTIONS,
    )
    op.create_index("ix_account_record_human", "account_record", ["human_id", "n"])
    op.create_table(
        "notification_read",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("seq", BIG_ID, nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        _human("notification_read"),
        sa.PrimaryKeyConstraint("human_id", "seq", name=op.f("pk_notification_read")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "notification_position",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("vector", JSON_VALUE, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("last_used_at", TIMESTAMP, nullable=False),
        _human("notification_position"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_position")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "card_watch",
        sa.Column("card_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["card.id"], name=op.f("fk_card_watch_card_id_card")),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_card_watch_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("card_id", "membership_id", name=op.f("pk_card_watch")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("card_watch")
    op.drop_table("notification_position")
    op.drop_table("notification_read")
    op.drop_index("ix_account_record_human", table_name="account_record")
    op.drop_table("account_record")
