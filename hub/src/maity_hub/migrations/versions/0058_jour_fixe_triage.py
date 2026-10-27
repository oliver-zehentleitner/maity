"""The jour fixe's triage (docs/api.md §20.6): a decision request the hub filed for a
proposal, and a card it opened for an adopted one, name their round and proposal.

Revision ID: 0058
Revises: 0055
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("jour_fixe", JSON_VALUE, nullable=True))
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("jour_fixe", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("jour_fixe")
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("jour_fixe")
