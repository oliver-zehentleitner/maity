"""A human's start tabs (docs/api.md §5.1 "Start tabs"): the ordered project ids a browser
with no tabs of its own opens. NULL, every existing account's value, opens every membership,
as the dashboard did before. The downgrade drops the column and the lists with it.

Revision ID: 20261107100000_start_tabs
Revises: 20261107090000_public_agents
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE

revision: str = "20261107100000_start_tabs"
down_revision: str | None = "20261107090000_public_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("human", sa.Column("start_tabs", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("human") as batch:
        batch.drop_column("start_tabs")
