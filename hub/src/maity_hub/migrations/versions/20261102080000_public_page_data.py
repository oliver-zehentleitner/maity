"""What a visitor's dashboard reads, stored beside the page's HTML (docs/api.md §16.9).

The hub clears and renders every page when it starts with pages on, so a row without `view` is
never served; the columns stay nullable for the rows of an instance with pages off.

Revision ID: 20261102080000_public_page_data
Revises: 20261102010000_worker_run
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE

revision: str = "20261102080000_public_page_data"
down_revision = "20261102010000_worker_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("public_page") as batch:
        batch.add_column(sa.Column("view", sa.String(20)))
        batch.add_column(sa.Column("data", JSON_VALUE))


def downgrade() -> None:
    with op.batch_alter_table("public_page") as batch:
        batch.drop_column("data")
        batch.drop_column("view")
