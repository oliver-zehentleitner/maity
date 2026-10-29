"""The role `manager` (docs/api.md §2.3 "The manager", §5.3, §6.2).

`membership.line_consent`: true while the member's cross-owner `reports_to` edge was
consented with a manager's rights and the boss still holds the role `manager`; false
for every existing row, since no edge before this named those rights (§6.2).
`membership.paused_line` and `credential.paused_line`: whether the pause stored beside
it was set by a manager under `line:lead`, which decides who lifts it (§5.3); `paused_by`
alone names the principal, not the right it acted under, and a manager may be an admin
agent at the same time. False for every existing pause, none of which a manager set.

Re-chained at merge time on the coordinator's call: `down_revision` is the head of the
branch this one started from and follows whatever head `main` has when it lands.

Revision ID: 0078
Revises: 0066
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("membership") as batch:
        batch.add_column(
            sa.Column("line_consent", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(
            sa.Column("paused_line", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    with op.batch_alter_table("credential") as batch:
        batch.add_column(
            sa.Column("paused_line", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("credential") as batch:
        batch.drop_column("paused_line")
    with op.batch_alter_table("membership") as batch:
        batch.drop_column("paused_line")
        batch.drop_column("line_consent")
