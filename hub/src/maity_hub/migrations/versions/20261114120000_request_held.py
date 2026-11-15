"""The agents a request is held for (docs/api.md §7, §9.6).

`request.held` lists the agents of other owners that a request's `to` reached without their
owner's yes when it was filed: it stays out of their inbox and resume packet and they cannot
answer it. Null for every request filed before, as for one that held nobody.

Revision ID: 20261114120000_request_held
Revises: 20261113200000_sf_day_revoked_by
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE

revision: str = "20261114120000_request_held"
down_revision: str | None = "20261113200000_sf_day_revoked_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("held", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("held")
