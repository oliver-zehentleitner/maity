"""Notification settings (docs/api.md §18.4, §18.6).

`notification_settings` holds a human's browser and mail preferences, the address and
its verification, with the normalized verified address unique across accounts;
`address_lock` is the per-address lock that claiming an address takes.

Revision ID: 0064
Revises: 0060
Create Date: 2026-10-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0064"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("preferences", JSON_VALUE, nullable=False),
        sa.Column("address", sa.String(length=254), nullable=True),
        sa.Column("address_normalized", sa.String(length=254), nullable=True),
        sa.Column("address_status", sa.String(length=16), nullable=False),
        sa.Column("verified_at", TIMESTAMP, nullable=True),
        sa.Column("pending_address", sa.String(length=254), nullable=True),
        sa.Column("pending_nonce", sa.String(length=32), nullable=True),
        sa.Column("pending_expires_at", TIMESTAMP, nullable=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("hard_failures", sa.Integer(), nullable=False),
        sa.Column("disabled_at", TIMESTAMP, nullable=True),
        sa.Column("address_change", JSON_VALUE, nullable=True),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_notification_settings_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_notification_settings")),
        sa.UniqueConstraint(
            "address_normalized", name=op.f("uq_notification_settings_address_normalized")
        ),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "address_lock",
        sa.Column("address", sa.String(length=254), nullable=False),
        sa.PrimaryKeyConstraint("address", name=op.f("pk_address_lock")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("address_lock")
    op.drop_table("notification_settings")
