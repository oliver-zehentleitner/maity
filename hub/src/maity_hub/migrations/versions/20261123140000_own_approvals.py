"""`policy.own_approvals`, `policy.own_agents` and `membership.joined_outside` (docs/api.md
§6.1, §2.3 "Own approvals").

`project.own_approvals` is the number of own approvals outsiders' work needs, null for the
default 1; `project.own_agents` is `owners`, `members` or `{"owners_of": [human ids]}`, null
for `members`. `membership.joined_outside` marks an agent membership made while the agent's
owner held no membership of the project; it is never cleared.

Existing rows are set once from the owners as they stand now: an agent membership whose
owner holds no active membership of its project is marked. An agent whose owner became a
member before this migration ran is not marked, since nothing recorded how it joined. The
rows are read and written in Python, not by one `UPDATE … WHERE NOT EXISTS (SELECT … FROM
membership)`, which MariaDB refuses for the table it updates.

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
CHUNK = 500


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
    conn = op.get_bind()
    membership = sa.table(
        "membership",
        sa.column("id", sa.Integer),
        sa.column("project_id", sa.String),
        sa.column("human_id", sa.String),
        sa.column("agent_id", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("joined_outside", sa.Boolean),
    )
    profile = sa.table(
        "agent_profile", sa.column("id", sa.String), sa.column("owner_id", sa.String)
    )
    agents = conn.execute(
        sa.select(membership.c.id, membership.c.project_id, profile.c.owner_id)
        .select_from(membership.outerjoin(profile, profile.c.id == membership.c.agent_id))
        .where(membership.c.agent_id.is_not(None))
    ).all()
    members = {
        (row.project_id, row.human_id)
        for row in conn.execute(
            sa.select(membership.c.project_id, membership.c.human_id).where(
                membership.c.human_id.is_not(None), membership.c.active.is_(True)
            )
        )
    }
    marked = [
        row.id
        for row in agents
        if row.owner_id is None or (row.project_id, row.owner_id) not in members
    ]
    for start in range(0, len(marked), CHUNK):
        conn.execute(
            sa.update(membership)
            .where(membership.c.id.in_(marked[start : start + CHUNK]))
            .values(joined_outside=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("joined_outside")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("own_agents")
        batch_op.drop_column("own_approvals")
