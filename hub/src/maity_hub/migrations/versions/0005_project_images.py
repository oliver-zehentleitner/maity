"""A project's logo and banner (docs/api.md §11.2).

One row per project, kind (`logo`, `banner`) and source (`uploaded`, `forge`):
the image a project admin uploaded, and the forge's image as the hub last read
it. The bytes are a binary column, LONGBLOB on MySQL/MariaDB, whose BLOB holds
64 KiB only; an image is at most 1 MiB. A forge row without data records that
the forge had none when it was checked.

Self-contained: the types are spelled out here, as in 0002.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# maity_hub.types.UtcDateTime stores naive UTC; microseconds on MySQL/MariaDB.
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
IMAGE_BYTES = sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql", "mariadb")


def upgrade() -> None:
    op.create_table(
        "project_image",
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("data", IMAGE_BYTES, nullable=True),
        sa.Column("content_type", sa.String(length=32), nullable=True),
        sa.Column("etag", sa.String(length=80), nullable=True),
        sa.Column("checked_at", TIMESTAMP, nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('logo', 'banner')", name=op.f("ck_project_image_kind")),
        sa.CheckConstraint("source IN ('uploaded', 'forge')", name=op.f("ck_project_image_source")),
        sa.CheckConstraint(
            "source = 'forge' OR data IS NOT NULL", name=op.f("ck_project_image_upload_has_data")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_project_image_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["membership.id"], name=op.f("fk_project_image_uploaded_by_membership")
        ),
        sa.PrimaryKeyConstraint("project_id", "kind", "source", name=op.f("pk_project_image")),
        mariadb_charset="utf8mb4",
        mariadb_collate="utf8mb4_bin",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )


def downgrade() -> None:
    op.drop_table("project_image")
