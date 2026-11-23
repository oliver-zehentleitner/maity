"""`policy.own_approvals`, `policy.own_agents` and `membership.joined_outside` (docs/api.md
§6.1, §2.3 "Own approvals").

`project.own_approvals` is the number of own approvals outsiders' work needs, null for the
default 1; `project.own_agents` is `owners`, `members` or `{"owners_of": [human ids]}`, null
for `members`. `membership.joined_outside` marks an agent membership made while the agent's
owner held no membership of the project; it is never cleared.

Existing rows are set from the membership history, as the exchange would have set them: an
agent membership is marked when its owner held no membership of its project at the agent's
`joined_at`. A removal keeps its row with `joined_at` and `removed_at`, and a rejoin is a
new row, so no owner row spanning that moment means the owner was no member then; an agent
whose profile is gone is marked too. One set-based `UPDATE … WHERE NOT EXISTS`, which
PostgreSQL, MariaDB (11.4 checked) and SQLite all take for the table they update
(hub/context/persistence.md 319da070).

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261123140000_own_approvals
Revises: 20261123120000_acct_lock_rows
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261123140000_own_approvals"
down_revision: str | None = "20261123120000_acct_lock_rows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("own_approvals", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("own_agents", JSON_VALUE, nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("joined_outside", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    _mark_existing()


def _mark_existing() -> None:
    membership = sa.table(
        "membership",
        sa.column("project_id", sa.String),
        sa.column("human_id", sa.String),
        sa.column("agent_id", sa.String),
        sa.column("joined_at", sa.DateTime),
        sa.column("removed_at", sa.DateTime),
        sa.column("joined_outside", sa.Boolean),
    )
    profile = sa.table(
        "agent_profile", sa.column("id", sa.String), sa.column("owner_id", sa.String)
    )
    owner = membership.alias("owner_row")
    held_then = (
        sa.select(sa.literal(1))
        .select_from(profile.join(owner, owner.c.human_id == profile.c.owner_id))
        .where(
            profile.c.id == membership.c.agent_id,
            owner.c.project_id == membership.c.project_id,
            owner.c.joined_at <= membership.c.joined_at,
            sa.or_(owner.c.removed_at.is_(None), owner.c.removed_at > membership.c.joined_at),
        )
        .correlate(membership)
    )
    op.get_bind().execute(
        sa.update(membership)
        .where(membership.c.agent_id.is_not(None), ~sa.exists(held_then))
        .values(joined_outside=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("joined_outside")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("own_agents")
        batch_op.drop_column("own_approvals")
