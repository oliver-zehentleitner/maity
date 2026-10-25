"""Single-use mailed sign-in links and browser-bound codes (§2.6.3).

Revision ID: 0043
Revises: 0037
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0043"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "email_sign_in",
        sa.Column("nonce_hash", sa.String(64), primary_key=True),
        sa.Column("pending_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("human_id", sa.String(40), sa.ForeignKey("human.id"), nullable=False),
        sa.Column("address_epoch", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("next_path", sa.String(512), nullable=False),
        sa.Column("code_mac", sa.String(64)),
        sa.Column("wrong_codes", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("used_at", TIMESTAMP),
        **OPTIONS,
    )
    op.create_index("ix_email_sign_in_human_id", "email_sign_in", ["human_id"])
    op.create_table(
        "email_sign_in_day",
        sa.Column("human_id", sa.String(40), sa.ForeignKey("human.id"), primary_key=True),
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("wrong_codes", sa.Integer(), nullable=False),
        **OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("email_sign_in_day")
    op.drop_index("ix_email_sign_in_human_id", table_name="email_sign_in")
    op.drop_table("email_sign_in")
