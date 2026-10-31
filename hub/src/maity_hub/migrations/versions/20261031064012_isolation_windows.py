"""The hidden windows of an isolation lifted with `hide_isolation_events` (docs/api.md §6.2).

`membership.isolated_from_seq` is the seq where the current isolation's window would start
(null while free); `membership.isolation_windows` is the list of `{from_seq, to_seq}` windows
the agent may never read, null for none.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261031064012_isolation_windows
Revises: 20261031052946_dormant_agent_ins
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031064012_isolation_windows"
down_revision: str | None = "20261031052946_dormant_agent_ins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("isolated_from_seq", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("isolation_windows", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("isolation_windows")
        batch_op.drop_column("isolated_from_seq")
