"""Notification mail: what was mailed, and when each digest left (docs/api.md §18.5).

`mail_item_sent` holds one row per human and item a notification mail carried, so an
item goes out once. `notification_mail_state` holds when a human's last hourly and daily
digest left.

Revision ID: 0043
Revises: 0036
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0043"
down_revision: str | None = "0036"
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
        "mail_item_sent",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("item", sa.String(length=40), nullable=False),
        sa.Column("mailed_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_mail_item_sent_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", "item", name=op.f("pk_mail_item_sent")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "notification_mail_state",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("hourly_at", TIMESTAMP, nullable=True),
        sa.Column("daily_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_notification_mail_state_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_notification_mail_state")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("notification_mail_state")
    op.drop_table("mail_item_sent")
