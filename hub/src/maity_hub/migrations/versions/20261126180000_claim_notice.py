"""An outsider's claim request on the requests it files (docs/api.md §6.5, "The lapse" and
"The outside owner's notice"; §7 `claim_request_id`, `claim_notice`).

- `request.claim_request_id`: the `clr-` id on the `decision` request a waiting claim
  request files to `trust:admin` when it lapses, and on the owner's notice. No foreign key,
  as for `claim_request.lapse_request_id`.
- `request.claim_notice`: `{claim_request_id, reason, decided_by}` on the owner's notice of
  a decline or a lapse; null on every other request.

Both nullable, no backfill: no request filed before carries either. The downgrade drops
both, and with them what they say on the requests filed since.

Revision ID: 20261126180000_claim_notice
Revises: 20261126090000_outside_claims
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261126180000_claim_notice"
down_revision: str | None = "20261126090000_outside_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = 40
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("claim_request_id", sa.String(ID), nullable=True))
        batch_op.add_column(sa.Column("claim_notice", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("claim_notice")
        batch_op.drop_column("claim_request_id")
