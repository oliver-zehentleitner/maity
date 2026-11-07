"""A person can show their own numbers on their public page (docs/api.md §16.9).

`human.public_stats` defaults to false for every account, the existing ones included: the
numbers are shown only once the person turns them on, separately from `public_profile`.

Revision ID: 20261106180000_public_stats
Revises: 20261105120000_known_source
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261106180000_public_stats"
down_revision: str | None = "20261105120000_known_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("public_stats", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("public_stats")
