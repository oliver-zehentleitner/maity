"""A card's `needs`: which role it is for (docs/api.md §6.4).

Revision ID: 20261101120000_card_needs
Revises: 20261101050000_org_alias
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101120000_card_needs"
down_revision: str | None = "20261101050000_org_alias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card") as batch_op:
        batch_op.add_column(sa.Column("needs", sa.String(length=24), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("card") as batch_op:
        batch_op.drop_column("needs")
