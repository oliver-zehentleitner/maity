"""Avatars: a member's picture, by account or profile and source (docs/api.md §6.10).

`avatar_image` holds the re-encoded PNG of an upload (and later the forge's image) per
`hum-`/`agt-` id; no row means the client draws the generated avatar.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
IMAGE_BYTES = sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "avatar_image",
        sa.Column("owner_id", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("data", IMAGE_BYTES, nullable=False),
        sa.Column("etag", sa.String(length=80), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint("source IN ('uploaded', 'forge')", name=op.f("ck_avatar_image_source")),
        sa.PrimaryKeyConstraint("owner_id", "source", name=op.f("pk_avatar_image")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("avatar_image")
