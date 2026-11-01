"""A card's `approvals`: the two signatures under `reviewer_and_tester` (docs/api.md §6.4).

The downgrade also turns the two done authorities the older schema's hub does not know into
`reviewer`, the nearest one it does.

Revision ID: 20261101130000_card_approvals
Revises: 20261101050000_org_alias
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261101130000_card_approvals"
down_revision: str | None = "20261101050000_org_alias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("card") as batch_op:
        batch_op.add_column(sa.Column("approvals", JSON_VALUE, nullable=True))


def downgrade() -> None:
    project = sa.table("project", sa.column("done_authority"))
    op.execute(
        project.update()
        .where(project.c.done_authority.in_(("tester", "reviewer_and_tester")))
        .values(done_authority="reviewer")
    )
    with op.batch_alter_table("card") as batch_op:
        batch_op.drop_column("approvals")
