"""The owner's open `Update now` requests on a runner (docs/api.md §15.16).

`runner.update_requests` holds `[{tool, requested_at}]`, one entry per tool, null until the
owner asks. The runner reads it with `GET /runner` and the hub drops an entry when the runner
reports that request carried out.

Revision ID: 20261114100000_runner_updates
Revises: 20261114020000_sealed_verifiers
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE

revision: str = "20261114100000_runner_updates"
down_revision: str | None = "20261114020000_sealed_verifiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runner", schema=None) as batch_op:
        batch_op.add_column(sa.Column("update_requests", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runner", schema=None) as batch_op:
        batch_op.drop_column("update_requests")
