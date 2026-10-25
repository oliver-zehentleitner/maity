"""Invitations for humans (docs/api.md §3.4).

`invitation` holds what an invitation grants — one project, one role, an optional
address it is bound to and a note — with the token's hash, its expiry and what became
of it: used, revoked, or voided because its issuer lost the authority it needs.

Revision ID: 0052
Revises: 0032
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0052"
down_revision: str | None = "0032"
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
        "invitation",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=254), nullable=True),
        sa.Column("address_normalized", sa.String(length=254), nullable=True),
        sa.Column("note", sa.String(length=1024), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("used_at", TIMESTAMP, nullable=True),
        sa.Column("used_by", sa.String(length=40), nullable=True),
        sa.Column("revoked_at", TIMESTAMP, nullable=True),
        sa.Column("voided_at", TIMESTAMP, nullable=True),
        sa.Column("void_reason", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_invitation_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["human.id"], name=op.f("fk_invitation_created_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["used_by"], ["human.id"], name=op.f("fk_invitation_used_by_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitation")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitation_token_hash")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_invitation_address_normalized"),
        "invitation",
        ["address_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_invitation_project_id_created_at",
        "invitation",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_invitation_project_id_created_at", table_name="invitation")
    op.drop_index(op.f("ix_invitation_address_normalized"), table_name="invitation")
    op.drop_table("invitation")
