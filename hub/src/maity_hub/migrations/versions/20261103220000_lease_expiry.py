"""`card.lease_expiry_reported`: the `lease_until` the last `claim_expired` named
(docs/api.md §6.5), so that a claim counts once per expiry. A lease that ran out before the
upgrade is marked as reported, so the first pass names only what expires from then on and
does not report every old claim at once. The downgrade drops the column.

Revision ID: 20261103220000_lease_expiry
Revises: 20261103210000_digest_seen
Create Date: 2026-11-03
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from maity_hub.types import UtcDateTime

revision: str = "20261103220000_lease_expiry"
down_revision: str | None = "20261103210000_digest_seen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card") as batch:
        batch.add_column(sa.Column("lease_expiry_reported", UtcDateTime()))
    card = sa.table(
        "card",
        sa.column("lease_until", UtcDateTime()),
        sa.column("claim_holder", sa.Integer()),
        sa.column("lease_expiry_reported", UtcDateTime()),
    )
    op.execute(
        card.update()
        .where(card.c.claim_holder.is_not(None), card.c.lease_until < datetime.now(UTC))
        .values(lease_expiry_reported=card.c.lease_until)
    )


def downgrade() -> None:
    with op.batch_alter_table("card") as batch:
        batch.drop_column("lease_expiry_reported")
