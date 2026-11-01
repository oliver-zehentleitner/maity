"""A proxy's request for the owner's go on one governance call (docs/api.md §2.3, §7).

`request.action` holds the call as asked and the hash of its body. `action_used_at` is apart
from it so that the call's transaction spends the go with a conditional update, which a JSON
field would not give on every database; `action_used_seq` names the event of that call.

Revision ID: 20261101140000_request_action
Revises: 20261101130000_card_approvals
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE, UtcDateTime

revision: str = "20261101140000_request_action"
down_revision = "20261101130000_card_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("request") as batch:
        batch.add_column(sa.Column("action", JSON_VALUE))
        batch.add_column(sa.Column("action_used_at", UtcDateTime()))
        batch.add_column(sa.Column("action_used_seq", sa.BigInteger()))


def downgrade() -> None:
    with op.batch_alter_table("request") as batch:
        batch.drop_column("action_used_seq")
        batch.drop_column("action_used_at")
        batch.drop_column("action")
