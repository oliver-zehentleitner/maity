"""Who waits in a group chat for their owner's yes (docs/api.md §9.6, "Waiting").

`conversation_participant.waiting_for` holds the human of each side an agent waits for, `[]`
once it is admitted, and null on a human and on an agent of the chat's only side; `waiting`
is whether that list holds anyone. `chat_access.lapsed_at` is when the hub saw an allow
entry's `until` pass.

The data step is the fourth way in §9.6, "this section ships": every agent of another owner
than someone in an open group chat waits for that someone's side, whatever entries exist,
until its owner answers. A side is a human on their own, or an agent's owner; a bridge
serving a participant across owners counts on its owner's side.

Revision ID: 20261113010000_firewall_waiting
Revises: 20261112190000_join_seq
Create Date: 2026-11-12
"""

from collections import defaultdict
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
    _wait()


def _wait() -> None:
    conn = op.get_bind()
    p = sa.table(
        "conversation_participant",
        sa.column("id", sa.Integer),
        sa.column("conversation_id", sa.String),
        sa.column("membership_id", sa.Integer),
        sa.column("here", sa.Boolean),
        sa.column("waiting_for", JSON_VALUE),
        sa.column("waiting", sa.Boolean),
    )
    c = sa.table("conversation", sa.column("id", sa.String), sa.column("closed_at", sa.DateTime))
    m = sa.table(
        "membership",
        sa.column("id", sa.Integer),
        sa.column("agent_id", sa.String),
        sa.column("human_id", sa.String),
    )
    a = sa.table("agent_profile", sa.column("id", sa.String), sa.column("owner_id", sa.String))
    b = sa.table(
        "bridge",
        sa.column("served", sa.Integer),
        sa.column("bridge", sa.Integer),
        sa.column("cross_owner", sa.Boolean),
        sa.column("live", sa.Boolean),
    )
    rows = conn.execute(
        sa.select(p.c.id, p.c.conversation_id, p.c.membership_id, m.c.agent_id, m.c.human_id)
        .select_from(p.join(m, m.c.id == p.c.membership_id).join(c, c.c.id == p.c.conversation_id))
        .where(p.c.here.is_(True), c.c.closed_at.is_(None))
        .order_by(p.c.id)
    ).all()
    if not rows:
        return
    owners = dict(conn.execute(sa.select(a.c.id, a.c.owner_id)).all())
    bridged: dict[int, list[int]] = defaultdict(list)
    for served, bridge in conn.execute(
        sa.select(b.c.served, b.c.bridge).where(b.c.cross_owner.is_(True), b.c.live.is_(True))
    ):
        bridged[served].append(bridge)
    bridge_owners = {
        mid: owners.get(agent_id)
        for mid, agent_id in conn.execute(
            sa.select(m.c.id, m.c.agent_id).where(
                m.c.id.in_({x for v in bridged.values() for x in v})
            )
        )
        if agent_id
    }
    sides: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        side = owners.get(row.agent_id) if row.agent_id else row.human_id
        if side:
            sides[row.conversation_id].add(side)
        for bridge in bridged.get(row.membership_id, []):
            bridge_side = bridge_owners.get(bridge)
            if bridge_side:
                sides[row.conversation_id].add(bridge_side)
    for row in rows:
        if not row.agent_id:
            continue
        own = owners.get(row.agent_id)
        others = sorted(s for s in sides[row.conversation_id] if s != own)
        if others:
            conn.execute(
                sa.update(p).where(p.c.id == row.id).values(waiting_for=others, waiting=True)
            )


def downgrade() -> None:
    op.drop_index("ix_chat_access_until", table_name="chat_access")
    with op.batch_alter_table("chat_access", schema=None) as batch_op:
        batch_op.drop_column("lapsed_at")
    with op.batch_alter_table("conversation_participant", schema=None) as batch_op:
        batch_op.drop_column("waiting")
        batch_op.drop_column("waiting_for")
