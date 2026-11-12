"""A forgotten password reset by mail (docs/api.md §2.10): the password generation and the
reset links' tables.

`human.password_generation` moves with every password change; a reset link carries the one it
was made under and dies when it moves. 0 on every existing human: no link has been made yet.
`password_reset` holds each link's `sha256(nonce)` for single use, `password_reset_wrong` each
wrong code at a reset, counted per human over 24 hours. Both start empty.

Revision ID: 20261112110000_password_reset
Revises: 20261111150000_present_until
Create Date: 2026-11-12
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261112110000_password_reset"
down_revision: str | None = "20261111150000_present_until"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("password_generation", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "password_reset",
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("used_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_password_reset_human_id_human")
        ),
        sa.PrimaryKeyConstraint("nonce_hash", name=op.f("pk_password_reset")),
        **MYSQL,
    )
    op.create_index("ix_password_reset_human_id", "password_reset", ["human_id"])
    op.create_table(
        "password_reset_wrong",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_password_reset_wrong_human_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_wrong")),
        **MYSQL,
    )
    op.create_index("ix_password_reset_wrong_human_at", "password_reset_wrong", ["human_id", "at"])


def downgrade() -> None:
    # The indexes go with the tables: MariaDB refuses to drop one alone while a foreign key
    # needs it (error 1553).
    op.drop_table("password_reset_wrong")
    op.drop_table("password_reset")
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("password_generation")
