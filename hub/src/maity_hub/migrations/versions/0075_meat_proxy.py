"""A human's switch "I am a meat proxy" (docs/api.md §5.2).

`human.meat_proxy`: whether the human said so in their profile; off for every
existing human.

Revision ID: 0075
Revises: 0071
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human") as batch_op:
        batch_op.add_column(
            sa.Column("meat_proxy", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("human") as batch_op:
        batch_op.drop_column("meat_proxy")
