"""`card.lease_warning_reported`: the `lease_until` the last `claim_lease_expiring` named
(docs/api.md §6.5), so that a claim is warned once per lease period. Nothing is backfilled: a
warning only names a lease that is still ahead and at most 300 seconds away, so the first pass
warns at most one event per holder whose lease is about to run out, which is its purpose. The
downgrade drops the column.

Revision ID: 20261110120000_lease_warning
Revises: 20261109200000_invite_by_handle
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import UtcDateTime

revision: str = "20261110120000_lease_warning"
down_revision: str | None = "20261109200000_invite_by_handle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card") as batch:
        batch.add_column(sa.Column("lease_warning_reported", UtcDateTime()))


def downgrade() -> None:
    with op.batch_alter_table("card") as batch:
        batch.drop_column("lease_warning_reported")
