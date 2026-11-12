"""The workspace after a stop (docs/api.md §15.5): a placement's retention time, which clone
of it is meant, the runner's latest report on that clone, and a removal asked by hand.

Every existing placement gets the default retention `24h` and its first clone (`1`); no
report exists yet, so the outcome columns start null, and no removal is asked.

Revision ID: 20261112180000_workspace_retain
Revises: 20261112150000_nudged_through
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261112180000_workspace_retain"
down_revision: str | None = "20261112150000_nudged_through"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
COLUMNS = (
    "workspace_retention",
    "workspace_epoch",
    "workspace_state",
    "workspace_reason",
    "workspace_unsaved",
    "workspace_size_bytes",
    "workspace_removes_at",
    "workspace_outcome_epoch",
    "workspace_reported_at",
    "remove_requested_at",
)


def upgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "workspace_retention", sa.String(length=16), nullable=False, server_default="24h"
            )
        )
        batch_op.add_column(
            sa.Column("workspace_epoch", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("workspace_state", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("workspace_reason", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("workspace_unsaved", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("workspace_size_bytes", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("workspace_removes_at", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("workspace_outcome_epoch", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("workspace_reported_at", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("remove_requested_at", TIMESTAMP, nullable=True))


def downgrade() -> None:
    # Columns only, no index: nothing a foreign key needs goes with them.
    with op.batch_alter_table("placement", schema=None) as batch_op:
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
