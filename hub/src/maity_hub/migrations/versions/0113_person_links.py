"""A person's website and their names on the networks, and who sees them (docs/api.md §16.9).

`human.website` is an https URL, `human.social` an object of names (never URLs), and
`human.links_visible` says who sees them: `private` until the person chooses.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 0113
Revises: 0105
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0113"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(sa.Column("website", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("social", JSON_VALUE, nullable=True))
        batch_op.add_column(
            sa.Column(
                "links_visible", sa.String(length=24), server_default="private", nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("links_visible")
        batch_op.drop_column("social")
        batch_op.drop_column("website")
