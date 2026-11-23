"""Every human has its `account_lock` row (hub/context/account.md).

0076 made a row for every human then; the humans made since got theirs on first need, inside
the transaction that first locked it, which let two such transactions deadlock on each other's
uncommitted insert (#1532). The row is now made with the account, and this backfills it for
every human still without one. The downgrade keeps the rows: the code before this revision
reads an existing row as it would one it made itself.

Revision ID: 20261123120000_acct_lock_rows
Revises: 20261121130000_plc_effort
Create Date: 2026-11-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261123120000_acct_lock_rows"
down_revision: str | None = "20261121130000_plc_effort"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO account_lock (human_id) SELECT id FROM human"
        " WHERE NOT EXISTS (SELECT 1 FROM account_lock WHERE account_lock.human_id = human.id)"
    )


def downgrade() -> None:
    pass  # the rows stay: 0076's table and rows, and harmless to the code before
