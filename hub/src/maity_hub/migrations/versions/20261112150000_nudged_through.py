"""The open read cycle of the unread nudge, per stay (docs/api.md §9.2 "The unread nudge"):
`conversation_participant.unread_nudged_through`, the `newest_seq` of the last `chat_unread`
written for that stay. The hub writes it with each nudge, under the project lock, and reads it
with the stay; finding the open cycle in the event log instead could not be both bounded and
exact across worker processes (review of #1512). The upgrade fills it from the nudges already
written: for each, the open stay of its recipient in its chat takes the highest `newest_seq`.
Its cost: per project with an agent, one index range over that project's `chat_unread` events
(about one per agent and chat per read cycle), two lookup maps held in memory (agent
memberships and open stays), and one UPDATE per open stay that has a nudge. It is idempotent.
The downgrade drops the column only; the hub before it reads the cycle from the log again.

Revision ID: 20261112150000_nudged_through
Revises: 20261112090000_firewall_lists
Create Date: 2026-11-12
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from maity_hub.types import BIG_ID

revision: str = "20261112150000_nudged_through"
down_revision: str | None = "20261112090000_firewall_lists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_event = sa.table(
    "event",
    sa.column("seq", sa.BigInteger),
    sa.column("project_id", sa.String),
    sa.column("kind", sa.String),
    sa.column("subject_type", sa.String),
    sa.column("subject_id", sa.String),
    sa.column("audience", sa.JSON),
    sa.column("payload", sa.JSON),
)
_membership = sa.table(
    "membership",
    sa.column("id", sa.Integer),
    sa.column("project_id", sa.String),
    sa.column("agent_id", sa.String),
)
_participant = sa.table(
    "conversation_participant",
    sa.column("id", sa.Integer),
    sa.column("conversation_id", sa.String),
    sa.column("membership_id", sa.Integer),
    sa.column("here", sa.Boolean),
    sa.column("unread_nudged_through", sa.BigInteger),
)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def upgrade() -> None:
    op.add_column(
        "conversation_participant", sa.Column("unread_nudged_through", BIG_ID, nullable=True)
    )
    conn = op.get_bind()
    agents = {
        (row.project_id, row.agent_id): row.id
        for row in conn.execute(
            sa.select(_membership.c.id, _membership.c.project_id, _membership.c.agent_id).where(
                _membership.c.agent_id.is_not(None)
            )
        )
    }
    stays = {
        (row.conversation_id, row.membership_id): row.id
        for row in conn.execute(
            sa.select(
                _participant.c.id, _participant.c.conversation_id, _participant.c.membership_id
            ).where(_participant.c.here.is_(True))
        )
    }
    # Project by project, so the read is the index range (project_id, kind, seq) of each
    # project's nudges, not a scan of the whole event table; one UPDATE per open stay that has
    # a nudge. Setting the highest `newest_seq` again gives the same value: idempotent.
    newest: dict[int, int] = {}
    for project_id in sorted({project for project, _ in agents}):
        nudges = conn.execute(
            sa.select(_event.c.subject_id, _event.c.audience, _event.c.payload).where(
                _event.c.project_id == project_id,
                _event.c.kind == "chat_unread",
                _event.c.subject_type == "conversation",
            )
        )
        for row in nudges:
            seq = int((_json(row.payload) or {}).get("newest_seq") or 0)
            for token in _json(row.audience) or []:
                if not isinstance(token, str) or not token.startswith("member:"):
                    continue
                membership = agents.get((project_id, token.removeprefix("member:")))
                stay = stays.get((row.subject_id, membership)) if membership else None
                if stay is not None:
                    newest[stay] = max(newest.get(stay, 0), seq)
    for stay, seq in newest.items():
        conn.execute(
            _participant.update().where(_participant.c.id == stay).values(unread_nudged_through=seq)
        )


def downgrade() -> None:
    with op.batch_alter_table("conversation_participant") as batch:
        batch.drop_column("unread_nudged_through")
