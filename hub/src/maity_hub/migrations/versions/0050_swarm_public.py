"""Whether the project's swarm page is public (docs/api.md §6.1, §6.22).

Revision ID: 0050
Revises: 0046 (rechain at merge; the number reserved by the coordinator)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("swarm_public", sa.String(8), server_default="off", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_column("swarm_public")
