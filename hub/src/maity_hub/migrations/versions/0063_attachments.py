"""Attachments (docs/api.md §8.7): the metadata of a file a message carries.

The bytes are in the blob store, never here. `message_seq` is null while an upload is
pending; a deletion keeps the row as a tombstone and removes the blob.

Revision ID: 0063
Revises: 0058
Create Date: 2026-10-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0063"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "attachment",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("size", BIG_ID, nullable=False),
        sa.Column("type", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", TIMESTAMP, nullable=False),
        sa.Column("message_seq", BIG_ID, nullable=True),
        sa.Column("deleted_at", TIMESTAMP, nullable=True),
        sa.Column("deleted_by", sa.String(length=40), nullable=True),
        sa.Column("deleted_reason", sa.String(length=16), nullable=True),
        sa.CheckConstraint("kind IN ('image', 'file')", name=op.f("ck_attachment_kind")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_attachment_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["membership.id"], name=op.f("fk_attachment_uploaded_by_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachment")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_attachment_project_pending",
        "attachment",
        ["project_id", "message_seq", "uploaded_at"],
        unique=False,
    )
    op.create_index(
        "ix_attachment_uploaded_by", "attachment", ["uploaded_by", "message_seq"], unique=False
    )
    op.create_index("ix_attachment_message_seq", "attachment", ["message_seq"], unique=False)


def downgrade() -> None:
    # The table takes its indexes with it; dropping them first fails on MariaDB, where
    # the foreign keys use the composite indexes.
    op.drop_table("attachment")
