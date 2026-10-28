"""An agent session that is not listening (docs/api.md §5.3).

`events_at` is the session's last call for events or its resume; `last_seen_at` counts
every call, so it cannot tell whether the session still waits. An episode lives on the
session: when it started, the oldest event that was waiting (it ends when the
acknowledged cursor reaches it) and the personal request filed to the profile's owner.

Revision ID: 0068
Revises: 0060
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0068"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("events_at", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("not_listening_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("not_listening_seq", BIG_ID, nullable=True))
        batch_op.add_column(
            sa.Column("not_listening_request_id", sa.String(length=40), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.drop_column("not_listening_request_id")
        batch_op.drop_column("not_listening_seq")
        batch_op.drop_column("not_listening_since")
        batch_op.drop_column("events_at")
