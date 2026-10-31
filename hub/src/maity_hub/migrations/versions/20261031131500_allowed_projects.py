"""`agent_profile.allowed_projects` (docs/api.md §6.3 "Allowed projects").

Null lets the agent go to any project; a list of at most 200 full names limits the projects it
may join, by any way a membership or an instance comes to be.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261031131500_allowed_projects
Revises: 20261031121521_role_memory_store
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031131500_allowed_projects"
down_revision: str | None = "20261031121521_role_memory_store"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("agent_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("allowed_projects", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_profile", schema=None) as batch_op:
        batch_op.drop_column("allowed_projects")
