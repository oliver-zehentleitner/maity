"""Who waits in a group chat for their owner's yes (docs/api.md §9.6, "Waiting").

`conversation_participant.waiting_for` holds the human of each side an agent waits for, `[]`
once it is admitted, and null on a human and on an agent of the chat's only side; `waiting`
is whether that list holds anyone. `chat_access.lapsed_at` is when the hub saw an allow
entry's `until` pass.

Schema only: no stay is marked here. Who waits is written by the hub, and only while the
agent firewall is switched on (`MAITY_AGENT_FIREWALL`, §9.6, "The switch"; req-5tngzfgp3nne o2):
at the start of a hub with the switch on (`chat_gate.switch_on`), honouring the owners' allow
entries, and on every change after. An instance that ran this revision with its former data step
(0.1.0a6) keeps the marks it wrote; with the switch off nothing reads them, and switching on
judges every open chat again.

Revision ID: 20261113010000_firewall_waiting
Revises: 20261112190000_join_seq
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE, UtcDateTime

revision: str = "20261113010000_firewall_waiting"
down_revision: str | None = "20261112190000_join_seq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_participant", schema=None) as batch_op:
        batch_op.add_column(sa.Column("waiting_for", JSON_VALUE, nullable=True))
        batch_op.add_column(
            sa.Column("waiting", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("chat_access", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lapsed_at", UtcDateTime(), nullable=True))
    op.create_index("ix_chat_access_until", "chat_access", ["kind", "lapsed_at", "until"])


def downgrade() -> None:
    op.drop_index("ix_chat_access_until", table_name="chat_access")
    with op.batch_alter_table("chat_access", schema=None) as batch_op:
        batch_op.drop_column("lapsed_at")
    with op.batch_alter_table("conversation_participant", schema=None) as batch_op:
        batch_op.drop_column("waiting")
        batch_op.drop_column("waiting_for")
