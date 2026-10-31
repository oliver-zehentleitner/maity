"""A join names whose work the new agent continues and where the hand-over is (§3.1, §5.2).

`join_link.takes_over` (an agent id) and `.handover` (`{kind, id}`) are what the human's join
carried; the exchange copies them to `membership.takes_over` (`{member_id, handle, name}` as
they were then, kept after the other member is removed) and `membership.handover`. No text of
the hand-over is stored.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261031150000_join_takes_over
Revises: 20261031112210_agent_owners
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031150000_join_takes_over"
down_revision: str | None = "20261031112210_agent_owners"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.add_column(sa.Column("takes_over", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("handover", JSON_VALUE, nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("takes_over", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("handover", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("handover")
        batch_op.drop_column("takes_over")
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("handover")
        batch_op.drop_column("takes_over")
