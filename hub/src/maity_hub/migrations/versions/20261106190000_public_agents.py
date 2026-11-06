"""A person chooses which of their agents their agents page lists (docs/api.md §16.9).

`human.public_agents` is `public_projects` for every account, the existing ones included: the
page lists the agents that have a page until the person chooses `all`.

Revision ID: 20261106190000_public_agents
Revises: 20261106180000_public_stats
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261106190000_public_agents"
down_revision: str | None = "20261106180000_public_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "public_agents",
                sa.String(length=16),
                server_default="public_projects",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("public_agents")
