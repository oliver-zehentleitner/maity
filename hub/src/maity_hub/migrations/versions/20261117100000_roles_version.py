"""A project's roles list carries a version (docs/api.md §2.3 "Version.").

`project.roles_version` starts at 0 and grows by one with every `PUT …/roles` that changes
the list, in the same write as `project.roles`; a `PUT` names it as `base_version` and a
stale one is `conflict`. Projects at the upgrade start at 0, whatever roles they hold: no
client has read a version yet, so none can be stale.

Revision ID: 20261117100000_roles_version
Revises: 20261115000000_address_where
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261117100000_roles_version"
down_revision: str | None = "20261115000000_address_where"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("roles_version", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("roles_version")
