"""A human's forge access (docs/api.md §11.4): links to installations of the instance's
GitHub App, and the human's own token.

`forge_link` holds one row per linked installation, unique per forge and installation,
with the account it is on, what it covers and its status. `forge_link_state` holds the
hash of a link's `state` while it is under way, bound to the session that started it.
No installation token is stored: they live in the hub's memory only. `forge_token`
holds a human's own fine-grained token, sealed with `MAITY_SECRET_KEY`.

Revision ID: 0073
Revises: 0071
Create Date: 2026-10-28
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0073"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "forge_link",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("forge", sa.String(length=16), nullable=False),
        sa.Column("installation_id", BIG_ID, nullable=False),
        sa.Column("account_id", BIG_ID, nullable=False),
        sa.Column("account_login", sa.String(length=64), nullable=False),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("repository_selection", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("linked_at", TIMESTAMP, nullable=False),
        sa.Column("checked_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_forge_link_human_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forge_link")),
        sa.UniqueConstraint(
            "forge", "installation_id", name=op.f("uq_forge_link_forge_installation_id")
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(op.f("ix_forge_link_human_id"), "forge_link", ["human_id"])
    op.create_table(
        "forge_link_state",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_forge_link_state_human_id_human")
        ),
        sa.PrimaryKeyConstraint("state_hash", name=op.f("pk_forge_link_state")),
        **TABLE_OPTIONS,
    )
    op.create_index(op.f("ix_forge_link_state_human_id"), "forge_link_state", ["human_id"])
    op.create_table(
        "forge_token",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("forge", sa.String(length=16), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("token_sealed", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("set_at", TIMESTAMP, nullable=False),
        sa.Column("checked_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_forge_token_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_forge_token")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("forge_token")
    op.drop_index(op.f("ix_forge_link_state_human_id"), table_name="forge_link_state")
    op.drop_table("forge_link_state")
    op.drop_index(op.f("ix_forge_link_human_id"), table_name="forge_link")
    op.drop_table("forge_link")
