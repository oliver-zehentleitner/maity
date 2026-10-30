"""The cursors a replacing instance's `handover` is cut from (docs/api.md §5.2, §6.17).

`credential.exchange_seq` is the project's newest event when the exchange created the instance,
`first_after` and `first_cursor` are `events.after` and `events.cursor` of its first resume
packet. The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261030164936_handover_cursors
Revises: 0106
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261030164936_handover_cursors"
down_revision: str | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("exchange_seq", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("first_after", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("first_cursor", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_column("first_cursor")
        batch_op.drop_column("first_after")
        batch_op.drop_column("exchange_seq")
