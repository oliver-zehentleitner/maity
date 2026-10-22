"""The host a join link was built on (docs/api.md §1.1, §3.1).

`join_link.via` is `join` (the optional join host) or `public`; the server default
fills the joins that exist when this runs, which were all built on the public URL.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("via", sa.String(length=16), server_default="public", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("via")
