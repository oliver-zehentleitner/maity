"""The forge's budget per source, shared by every replica (hub/context/replicas.md 83da2bfa).

UNLOGGED on PostgreSQL: a crash or a failover empties it, and the next answer of the forge says
again what is left. Only PostgreSQL writes it, the other databases run one replica.

Revision ID: 20261102090000_forge_budget
Revises: 20261102080000_public_page_data
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261102090000_forge_budget"
down_revision: str | None = "20261102080000_public_page_data"
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
    op.create_table(
        "forge_budget",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=True),
        sa.Column("remaining", sa.Integer(), nullable=True),
        sa.Column("reset", sa.Float(), nullable=True),
        sa.Column("until", sa.Float(), nullable=False),
        sa.Column("seen_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_forge_budget")),
        prefixes=["UNLOGGED"] if op.get_bind().dialect.name == "postgresql" else [],
        **MYSQL,
    )


def downgrade() -> None:
    op.drop_table("forge_budget")
