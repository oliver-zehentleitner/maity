"""The instance a request is addressed to (docs/api.md §7).

`request.to_instance` is the instance id of an instance address in `to`
(`agt-b#wqe2`), as the caller wrote it: the audience of the request's events resolves it
again when it is written (a replaced instance's address reaches its successor, §8.2), the
request shows what was asked. `NULL` for every request that exists when this runs, which
were all addressed to a member, a role or the owner.

Revision ID: 0100
Revises: 0098
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0100"
down_revision: str | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("to_instance", sa.String(length=5), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("to_instance")
