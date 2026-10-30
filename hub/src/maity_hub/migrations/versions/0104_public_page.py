"""The public pages the hub rendered (docs/api.md §16.9).

`public_page` holds one row per address, the HTML as it is served, its ETag, a digest of the
inputs it was made from and when they last changed. A page that stops being public is a deleted
row, in the transaction that changed the input.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 0104
Revises: 0100
Create Date: 2026-10-30
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0104"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "public_page",
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("body", MARKDOWN_TEXT, nullable=False),
        sa.Column("etag", sa.String(length=80), nullable=False),
        sa.Column("inputs", sa.String(length=64), nullable=False),
        sa.Column("lastmod", TIMESTAMP, nullable=False),
        sa.Column("rendered_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("path", name=op.f("pk_public_page")),
        **OPTIONS,
    )
    op.create_index("ix_public_page_target", "public_page", ["kind", "target_id"], unique=False)


def downgrade() -> None:
    op.drop_table("public_page")  # whole, as every downgrade of a table here
