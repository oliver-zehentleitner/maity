"""Opt-in project badge (docs/api.md §6.20).

Revision ID: 0046
Revises: 0030
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("badge", sa.String(20), server_default="off", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_column("badge")
