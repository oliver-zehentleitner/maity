"""Bringing your own agent (docs/api.md §3.1, §6.1): the project's `member_agents` and
`member_agents_max`, and whether a join was created under that rule.

Projects that predate the fields read `on` and 3, as the contract says; every join made
before reads as an admin's.

Revision ID: 0066
Revises: 0075
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("member_agents", sa.String(8), server_default="on", nullable=False)
        )
        batch.add_column(
            sa.Column("member_agents_max", sa.Integer(), server_default="3", nullable=False)
        )
    with op.batch_alter_table("join_link") as batch:
        batch.add_column(
            sa.Column("member_rule", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("join_link") as batch:
        batch.drop_column("member_rule")
    with op.batch_alter_table("project") as batch:
        batch.drop_column("member_agents_max")
        batch.drop_column("member_agents")
