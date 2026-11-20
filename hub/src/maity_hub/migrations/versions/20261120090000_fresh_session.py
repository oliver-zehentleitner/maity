"""A reset of a placement (docs/api.md §15.6): the generation whose start takes a fresh
harness session instead of resuming the last one.

`placement.fresh_session_generation` is null until the first reset and is never cleared: the
placement reads `fresh_session` true only while its `generation` equals it, so every later
new generation ends the reset without a write. Nothing to carry over.

Revision ID: 20261120090000_fresh_session
Revises: 20261118180000_access_history
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120090000_fresh_session"
down_revision: str | None = "20261118180000_access_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fresh_session_generation", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.drop_column("fresh_session_generation")
