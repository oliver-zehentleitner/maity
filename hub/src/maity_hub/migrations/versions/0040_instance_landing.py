"""The instance's landing page (docs/api.md §16.7).

One row, `id = 'landing'`, written by the instance admin: whether the dashboard's root
shows it to visitors who are not signed in, its title, Markdown and button, and who
changed it when. No row is the default: disabled.

Revision ID: 0040
Revises: 0044
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0040"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
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
        "instance_landing",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("markdown", MARKDOWN_TEXT, nullable=True),
        sa.Column("cta", JSON_VALUE, nullable=True),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instance_landing")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("instance_landing")
