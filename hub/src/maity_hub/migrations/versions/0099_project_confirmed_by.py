"""Whose grants a project's repository confirmation put to use (docs/api.md §11.4).

`project.repository_confirmed_by` is the human whose forge grants the hub reads the repository
with: the namespace owner for a project of a human, the owner of the organisation who confirmed
for a project of an organisation. The confirmations that exist when this runs were all the
namespace owner's, and every project that carries one is a project of a human.

Revision ID: 0099
Revises: 0098
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0099"
down_revision: str | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("repository_confirmed_by", sa.String(length=40), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_project_repository_confirmed_by_human", "human", ["repository_confirmed_by"], ["id"]
        )
    op.execute(
        "UPDATE project SET repository_confirmed_by = owner_id "
        "WHERE repository_owner_confirmed = TRUE AND owner_id LIKE 'hum-%'"
    )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint("fk_project_repository_confirmed_by_human", type_="foreignkey")
        batch_op.drop_column("repository_confirmed_by")
