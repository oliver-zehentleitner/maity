"""Where an address change was asked from (docs/api.md §2.6.3, §18.4).

`notification_settings.pending_browser`, `pending_os` and `pending_ip` hold the requesting
session's browser, operating system and IP address beside the pending address, so the notice
to the old address names them once the new one is verified. They are cleared with the pending
address and once it expired. Rows pending at the upgrade start empty: their notice carries no
"From:" line, as before.

Revision ID: 20261115000000_address_where
Revises: 20261114200000_chat_verdict
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261115000000_address_where"
down_revision: str | None = "20261114200000_chat_verdict"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pending_browser", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("pending_os", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("pending_ip", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.drop_column("pending_ip")
        batch_op.drop_column("pending_os")
        batch_op.drop_column("pending_browser")
