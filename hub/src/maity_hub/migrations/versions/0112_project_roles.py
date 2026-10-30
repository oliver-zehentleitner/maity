"""Project roles (docs/api.md §2.3 "Project roles", #506).

`project.roles` holds a project's own roles, null for none. `membership.role_base` is the
built-in role whose scopes a membership's `role` has; every membership so far holds a
built-in role, so its base is the role itself.

Revision ID: 0112
Revises: 0107
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0112"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("roles", JSON_VALUE, nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role_base", sa.String(24), nullable=True))
    membership = sa.table("membership", sa.column("role"), sa.column("role_base"))
    op.get_bind().execute(sa.update(membership).values(role_base=membership.c.role))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.alter_column("role_base", existing_type=sa.String(24), nullable=False)


def downgrade() -> None:
    # Before this revision every role was a built-in one: a project role becomes its base
    # wherever it is named, so no reader meets a name it does not know.
    bind = op.get_bind()
    project = sa.table("project", sa.column("id"), sa.column("roles", JSON_VALUE))
    for project_id, roles in bind.execute(sa.select(project.c.id, project.c.roles)).all():
        for role in roles or []:
            for name in ("membership", "join_link", "invitation"):
                rows = sa.table(name, sa.column("project_id"), sa.column("role"))
                bind.execute(
                    sa.update(rows)
                    .where(rows.c.project_id == project_id, rows.c.role == role["name"])
                    .values(role=role["base"])
                )
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("role_base")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("roles")
