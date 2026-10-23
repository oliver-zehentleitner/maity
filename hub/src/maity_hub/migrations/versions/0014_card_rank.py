"""A card's place within its status column (docs/api.md §6.4).

`card.rank` is set by the hub only, on a move; null for every card until it is first
placed, which orders it after the ranked ones by `created_at`.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rank", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("rank")
