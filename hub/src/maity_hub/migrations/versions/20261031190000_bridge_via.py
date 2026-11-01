"""A bridge's call recorded on the event and the card's history (docs/api.md §2.3, "The
bridge"): `actor_bridge` names the bridge, its instance and the connection, `{member_id,
instance, bridge_id}`, beside the served agent as the actor. A message carries it in its
payload and an answer in its stored answer, so neither needs a column.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261031190000_bridge_via
Revises: 20261031180000_bridges
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031190000_bridge_via"
down_revision: str | None = "20261031180000_bridges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    for table in ("event", "card_history"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("actor_bridge", JSON_VALUE, nullable=True))


def downgrade() -> None:
    for table in ("card_history", "event"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("actor_bridge")
