"""Who listens, shared by every replica: the open long-polls and the pods that hold them.

`long_poll` holds one row per open wait, keyed by a fresh `wait_id`, with what `is_listening` is
asked with (`listening_key`: the agent session's id, or the runner's listening key) and the pod
holding it; `hub_pod` is each pod's heartbeat. A wait whose pod has not been seen for 45 s does
not count (hub/context/replicas.md 387c2409, point 4, `listening`). On PostgreSQL both are
UNLOGGED: a crash or a failover empties them, and each process's heartbeat writes its open waits
again within 15 s. SQLite and MariaDB create ordinary tables and keep the registry in the process.

Revision ID: 20261031125530_long_polls
Revises: 20261031070700_project_links
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261031125530_long_polls"
down_revision: str | None = "20261031070700_project_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def _unlogged() -> list[str]:
    return ["UNLOGGED"] if op.get_bind().dialect.name == "postgresql" else []


def upgrade() -> None:
    op.create_table(
        "hub_pod",
        sa.Column("pod", sa.String(length=64), nullable=False),
        sa.Column("seen_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("pod", name=op.f("pk_hub_pod")),
        prefixes=_unlogged(),
        **MYSQL,
    )
    op.create_table(
        "long_poll",
        sa.Column("wait_id", sa.String(length=32), nullable=False),
        sa.Column("listening_key", sa.String(length=255), nullable=False),
        sa.Column("pod", sa.String(length=64), nullable=False),
        sa.Column("opened_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("wait_id", name=op.f("pk_long_poll")),
        prefixes=_unlogged(),
        **MYSQL,
    )
    op.create_index("ix_long_poll_key", "long_poll", ["listening_key"])
    op.create_index("ix_long_poll_pod", "long_poll", ["pod"])


def downgrade() -> None:
    op.drop_index("ix_long_poll_pod", table_name="long_poll")
    op.drop_index("ix_long_poll_key", table_name="long_poll")
    op.drop_table("long_poll")
    op.drop_table("hub_pod")
