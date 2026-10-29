"""A card imported from a forge issue says which (docs/api.md §6.14).

Revision ID: 0082
Revises: 0085
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0082"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("imported_from", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("imported_from")
