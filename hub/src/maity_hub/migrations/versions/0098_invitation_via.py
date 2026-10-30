"""The host an invitation's link was built on (docs/api.md §1.1, §3.4).

`invitation.via` is `join` (the optional join host) or `public`, as `join_link.via` is;
the server default fills the invitations that exist when this runs, which were all built
on the public URL.

Revision ID: 0098
Revises: 0088
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0098"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("invitation", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("via", sa.String(length=16), server_default="public", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("invitation", schema=None) as batch_op:
        batch_op.drop_column("via")
