"""Mail: the admin's settings and the delivery counters (docs/api.md §16.2, §16.3).

`mail_setting` holds one row per field the instance admin set through `PATCH
/admin/settings/mail`; no row means the environment's value or the default. The SMTP
password is stored only as AES-256-GCM ciphertext with its nonce. `mail_delivery` holds
one row per mail handed to SMTP or held back, by budget kind and outcome, for the
counters of the last hour; no address and no content.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0020"
down_revision: str | None = "0019"
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


def upgrade() -> None:
    op.create_table(
        "mail_setting",
        sa.Column("field", sa.String(length=32), nullable=False),
        sa.Column("value", JSON_VALUE, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("field", name=op.f("pk_mail_setting")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "mail_delivery",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_delivery")),
        sqlite_autoincrement=True,
        **TABLE_OPTIONS,
    )
    op.create_index("ix_mail_delivery_at", "mail_delivery", ["at"])


def downgrade() -> None:
    op.drop_index("ix_mail_delivery_at", table_name="mail_delivery")
    op.drop_table("mail_delivery")
    op.drop_table("mail_setting")
