"""The namespace owner's confirmation of the project's repository (docs/api.md §11.4).

`project.repository_owner_confirmed`: whether the namespace owner confirmed the
repository URL the project carries now for the owner's own forge grants. Every
change of the URL and every transfer sets it back to false; existing projects
start unconfirmed.

Revision ID: 0071
Revises: 0064
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch_op:
        batch_op.add_column(
            sa.Column(
                "repository_owner_confirmed",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("project") as batch_op:
        batch_op.drop_column("repository_owner_confirmed")
