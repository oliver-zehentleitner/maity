"""Until when a human session was present in the web app (docs/api.md §18.4, §18.5).

`human_session.present_until` is set by `POST /me/presence` from a dashboard tab that is
visible and had input within ten minutes, and read only by the notification mail's hold.
It is null on every existing session: none has said it is present yet, so none holds mail.

Revision ID: 20261111150000_present_until
Revises: 20261111010000_expert_fields
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import UtcDateTime

revision: str = "20261111150000_present_until"
down_revision: str | None = "20261111010000_expert_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("present_until", UtcDateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("human_session", schema=None) as batch_op:
        batch_op.drop_column("present_until")
