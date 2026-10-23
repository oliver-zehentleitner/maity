"""What a consent request applies on its go (docs/api.md §2.3 ᵃ).

`request.proposal` is `{"kind": …}` for a request filed by a registered proposal kind
(`maity_hub.proposals`), null for every other request.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("proposal", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("proposal")
