"""`project.swarm_public` goes with the public swarm page (docs/api.md §6.22, §16.9).

The swarm is a statistic in the project's Overview now; whether the world sees the team's
numbers is the project's one choice to have a public page. A downgrade brings the column
back as `off` for every project: what was `on` before is not kept.

Revision ID: 0102
Revises: 0100
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0102"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_column("swarm_public")


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("swarm_public", sa.String(8), server_default="off", nullable=False)
        )
