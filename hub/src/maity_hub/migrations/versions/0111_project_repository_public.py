"""Whether the forge reported a project's repository public (docs/api.md §16.9, §11.4).

`project.repository_public` is null until the hub looked, which counts as private; the probe
sets it on each of its rounds for a project with a public page.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 0111
Revises: 0110
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0111"
down_revision: str | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("repository_public", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("repository_public")
