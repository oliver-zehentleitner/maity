"""An expert's two membership fields (docs/api.md §2.3 "The expert", §6.2, §17.3).

`membership.expert_for` is what the expert answers about, plain text of at most 120
characters. `membership.expert_sources` is the list of path prefixes it learned, in the
form of §6.2 areas, at most 20. Both are null on every existing membership: no member was
an expert with fields before, and the hub shows null as no text and no sources.

Revision ID: 20261111010000_expert_fields
Revises: 20261109200000_invite_by_handle
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261111010000_expert_fields"
down_revision: str | None = "20261109200000_invite_by_handle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("expert_for", sa.String(length=480), nullable=True))
        batch_op.add_column(
            sa.Column(
                "expert_sources",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("expert_sources")
        batch_op.drop_column("expert_for")
