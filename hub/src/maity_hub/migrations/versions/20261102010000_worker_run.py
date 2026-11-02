"""Who runs a worker's pass, and since when: one row per worker, claimed by a compare-and-set
(hub/context/replicas.md 24489a9c, `worker_runs`). Logged, unlike `hub_pod`: `started_at` is what
keeps a pass to once per interval, though a lost row costs no more than one early pass. Only
PostgreSQL writes it, the other databases run one replica.

Revision ID: 20261102010000_worker_run
Revises: 20261102000000_interface_lang
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261102010000_worker_run"
down_revision: str | None = "20261102000000_interface_lang"
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
        "worker_run",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("pod", sa.String(length=64), nullable=False),
        sa.Column("lease_until", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_worker_run")),
        **MYSQL,
    )


def downgrade() -> None:
    op.drop_table("worker_run")
