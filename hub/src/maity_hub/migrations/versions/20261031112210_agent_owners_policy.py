"""`policy.agent_owners` and `policy.outside_roles` (docs/api.md §6.1, §6.2).

`project.agent_owners` is `members` or `anyone`, null while nobody set it (it then follows the
public page); `project.outside_roles` is the list of roles an agent of an owner from outside may
hold, null for the default `["coder"]`.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261031112210_agent_owners_policy
Revises: 20261031064012_isolation_windows
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031112210_agent_owners_policy"
down_revision: str | None = "20261031064012_isolation_windows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_owners", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("outside_roles", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("outside_roles")
        batch_op.drop_column("agent_owners")
