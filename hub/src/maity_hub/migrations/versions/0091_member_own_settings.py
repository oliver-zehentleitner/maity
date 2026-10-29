"""A human member's own settings in a project (docs/api.md §6.2).

`own_settings` holds the member's overrides of their personal defaults for this project,
`{not_listening: {minutes}}` the first; `NULL` (every existing membership) reads as no
override.

Revision ID: 0091
Revises: 0086
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0091"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("own_settings", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("own_settings")
