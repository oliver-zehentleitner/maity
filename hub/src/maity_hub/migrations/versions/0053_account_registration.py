"""Accounts that wait for approval (docs/api.md §2.7.5, §16.4).

`account_registration` keeps, for an account registration made under `approval:
operator`, what the instance admin decides on — the address, the source, when it
expires — and the decision: `pending`, `active`, `rejected` or `expired`. A rejected or
expired account is deleted; its row stays, so a second decision is told it came late.

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0053"
down_revision: str | None = "0052"
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
        "account_registration",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("address", sa.String(length=254), nullable=False),
        sa.Column("address_normalized", sa.String(length=254), nullable=False),
        sa.Column("source_ip", sa.String(length=64), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_at", TIMESTAMP, nullable=True),
        sa.Column("decided_by", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_account_registration")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_account_registration_address_normalized"),
        "account_registration",
        ["address_normalized"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_account_registration_address_normalized"), table_name="account_registration"
    )
    op.drop_table("account_registration")
