"""A human's stars (docs/api.md §5.1 "Stars"): the ordered ids of the public projects they keep
as tabs without a membership. NULL, every existing account's value, is no star. The downgrade
drops the column and the stars with it.

Revision ID: 20261118090000_starred
Revises: 20261117230000_limit_override
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE

revision: str = "20261118090000_starred"
down_revision: str | None = "20261117230000_limit_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("human", sa.Column("starred", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("human") as batch:
        batch.drop_column("starred")
