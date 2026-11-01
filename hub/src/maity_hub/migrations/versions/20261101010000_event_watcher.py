"""The private list of who an event reached through a watch (docs/api.md §6.4).

`event_watcher` holds one row per event and membership on it, fixed when the event is written,
stored apart from the event and never served.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261101010000_event_watcher
Revises: 20261031180000_bridges
Create Date: 2026-11-01
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20261101010000_event_watcher"
down_revision: str | None = "20261031180000_bridges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "event_watcher",
        sa.Column("seq", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["seq"], ["event.seq"], name=op.f("fk_event_watcher_seq_event")),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_event_watcher_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("seq", "membership_id", name=op.f("pk_event_watcher")),
        **MYSQL,
    )


def downgrade() -> None:
    op.drop_table("event_watcher")
