"""The setup options of a project and the cards made for them (docs/api.md §6.21).

`setup` holds the three booleans chosen at creation and the ids of the setup cards the
hub created (`null` until it did); projects made before it read `null`.

Revision ID: 0081
Revises: 0084
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("setup", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("setup")
