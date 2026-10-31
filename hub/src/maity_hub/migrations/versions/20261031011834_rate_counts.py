"""The counts of the rate limits, breakers and guess counters, shared by every replica.

`rate_count` holds a count per bucket (one limit), subject (the limit's key) and fixed window;
a breaker's "shut until" is a row of its own (hub/context/replicas.md 2bd65fec, `shared_counts`).
On PostgreSQL it is UNLOGGED: a crash or a failover empties it, which lets through at most one
window's worth again. The other databases create it as an ordinary table and keep the counts in
the process. Nothing is copied: the process held nothing worth keeping.

Revision ID: 20261031011834_rate_counts
Revises: 20261031052946_dormant_agent_ins
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261031011834_rate_counts"
down_revision: str | None = "20261031052946_dormant_agent_ins"
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
        "rate_count",
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("window_start", TIMESTAMP, nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", "subject", "window_start", name=op.f("pk_rate_count")),
        prefixes=["UNLOGGED"] if op.get_bind().dialect.name == "postgresql" else [],
        **MYSQL,
    )


def downgrade() -> None:
    op.drop_table("rate_count")
