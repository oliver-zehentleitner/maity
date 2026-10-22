"""Signing per project, and the path of a credential's last use (docs/api.md §2.2, §10).

`project.signing` is `optional` or `required`; the server default fills the
projects that exist when this runs. `credential.last_used_via` is `bearer`
or `signed`, written together with `last_used_at`, and stays null until the
next call.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("signing", sa.String(length=16), server_default="optional", nullable=False)
        )
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_used_via", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_column("last_used_via")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("signing")
