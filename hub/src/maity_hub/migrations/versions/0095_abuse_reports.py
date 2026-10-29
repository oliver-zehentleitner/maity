"""Abuse reports (docs/api.md §16.8): what someone reported, with a copy of it as they could
read it, until an instance admin resolves it or it expires.

Revision ID: 0095
Revises: 0094
Create Date: 2026-10-29
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "abuse_report",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("reporter", sa.String(length=40), nullable=False),
        sa.Column("account_id", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("snapshot", JSON_VALUE, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=True),
        sa.Column("note", TEXT, nullable=True),
        sa.Column("resolved_by", sa.String(length=40), nullable=True),
        sa.Column("resolved_at", TIMESTAMP, nullable=True),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.Column("purged_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["human.id"], name=op.f("fk_abuse_report_account_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_abuse_report")),
        **OPTIONS,
    )
    op.create_index(
        op.f("ix_abuse_report_account_id"), "abuse_report", ["account_id"], unique=False
    )
    op.create_index(
        "ix_abuse_report_status_created", "abuse_report", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    # The table goes with its indexes; MariaDB refuses to drop an index the foreign key on
    # `account_id` still needs (as 0061 and 0077 do).
    op.drop_table("abuse_report")
