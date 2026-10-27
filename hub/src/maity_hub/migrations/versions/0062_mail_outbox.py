"""The mail outbox (docs/api.md §16.2, §18.5, §18.7).

`mail_outbox` holds mail waiting for the mail worker, written in the transaction that
decides it. `status` is `waiting`, `sending` (claimed by one process), `sent`, `failed` or
`dropped`; `not_before` is when a row is next due, and while it is `sending` the deadline
of the claim.

Revision ID: 0062
Revises: 0063
Create Date: 2026-10-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0062"
down_revision: str | None = "0063"
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
        "mail_outbox",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=True),
        sa.Column("recipient", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("headers", JSON_VALUE, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("not_before", TIMESTAMP, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_mail_outbox_human_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_outbox")),
        sqlite_autoincrement=True,
        **TABLE_OPTIONS,
    )
    op.create_index("ix_mail_outbox_due", "mail_outbox", ["status", "not_before"])


def downgrade() -> None:
    op.drop_index("ix_mail_outbox_due", table_name="mail_outbox")
    op.drop_table("mail_outbox")
