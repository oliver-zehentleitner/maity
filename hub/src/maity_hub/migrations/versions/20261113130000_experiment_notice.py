"""When a human confirmed the experiment notice (docs/api.md §5.1, "Experiment notice").

`human.experiment_notice_understood_at` is null until the person answers the notice with
"Understood", then the hub's time of the first confirmation. Existing accounts start null like
new ones, so they see the notice once too.

Revision ID: 20261113130000_experiment_notice
Revises: 20261113010000_firewall_waiting
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import UtcDateTime

revision: str = "20261113130000_experiment_notice"
down_revision: str | None = "20261113010000_firewall_waiting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("experiment_notice_understood_at", UtcDateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("experiment_notice_understood_at")
