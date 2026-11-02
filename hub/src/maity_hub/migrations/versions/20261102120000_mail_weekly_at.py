"""The weekly digest's clock (docs/api.md §18.4 `weekly`): when the human's last weekly
digest pass ran, NULL before any. The new defaults need no data change: only what a human
set is stored (context/notifications.md da12f2b5).

Revision ID: 20261102120000_mail_weekly_at
Revises: 20261102100000_project_probe_via
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import UtcDateTime

revision: str = "20261102120000_mail_weekly_at"
down_revision: str | None = "20261102100000_project_probe_via"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification_mail_state") as batch:
        batch.add_column(sa.Column("weekly_at", UtcDateTime()))


def downgrade() -> None:
    with op.batch_alter_table("notification_mail_state") as batch:
        batch.drop_column("weekly_at")
