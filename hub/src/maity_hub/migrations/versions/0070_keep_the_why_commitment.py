"""The Keep the Why commitment of an agent instance (docs/api.md §6.23).

An instance (a credential) confirms once; its deadline is fixed by its first resume while
the policy is `required`. The reminder and the owner's request are sent once per
outstanding commitment, which these columns remember.

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ktw_acknowledged_at", TIMESTAMP, nullable=True))
        batch_op.add_column(
            sa.Column("ktw_acknowledged_session", sa.String(length=40), nullable=True)
        )
        batch_op.add_column(sa.Column("ktw_acknowledge_by", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("ktw_session_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("ktw_reminded_at", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("ktw_request_id", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_column("ktw_request_id")
        batch_op.drop_column("ktw_reminded_at")
        batch_op.drop_column("ktw_session_id")
        batch_op.drop_column("ktw_acknowledge_by")
        batch_op.drop_column("ktw_acknowledged_session")
        batch_op.drop_column("ktw_acknowledged_at")
