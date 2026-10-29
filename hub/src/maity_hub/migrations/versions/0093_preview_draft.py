"""Drafts of the landing page and the legal pages (docs/api.md §16.7, §16.7.1).

`preview_draft` holds a draft the instance admin posted to see it before saving: bound to the
admin's session, kept ten minutes, at most twenty per session. It is not part of the setting.

Revision ID: 0093
Revises: 0096
Create Date: 2026-10-29
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0093"
down_revision: str | None = "0096"
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
        "preview_draft",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("page", sa.String(length=16), nullable=True),
        sa.Column("payload", JSON_VALUE, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preview_draft")),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_preview_draft_session", "preview_draft", ["session", "created_at"])


def downgrade() -> None:
    op.drop_table("preview_draft")
