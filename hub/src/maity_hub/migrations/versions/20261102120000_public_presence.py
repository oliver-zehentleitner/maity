"""A person can keep their online status off the public pages (docs/api.md §16.9).

`human.public_presence` defaults to true: the public pages of the person's projects name them
as online; off, they are neither named nor counted there.

Revision ID: 20261102120000_public_presence
Revises: 20261102110000_profiles_public
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102120000_public_presence"
down_revision: str | None = "20261102110000_profiles_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("public_presence", sa.Boolean(), server_default=sa.true(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("public_presence")
