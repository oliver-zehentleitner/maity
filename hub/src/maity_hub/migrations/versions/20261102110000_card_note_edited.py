"""A note's edit mark: `{by, at, reason}` of the latest edit, NULL before any. No earlier text
is kept (context/cards.md 0e6b3b31).

Revision ID: 20261102110000_card_note_edited
Revises: 20261102100000_project_probe_via
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE

revision: str = "20261102110000_card_note_edited"
down_revision: str | None = "20261102100000_project_probe_via"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card_note") as batch:
        batch.add_column(sa.Column("edited", JSON_VALUE))


def downgrade() -> None:
    with op.batch_alter_table("card_note") as batch:
        batch.drop_column("edited")
