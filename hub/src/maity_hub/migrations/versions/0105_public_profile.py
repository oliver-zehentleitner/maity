"""A person's public page: the choice and the text (docs/api.md §16.9).

`human.public_profile` is false until the person turns their page on, `public_bio` the plain
text of at most 280 characters on it.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 0105
Revises: 0104
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0105"
down_revision: str | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("public_profile", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("public_bio", sa.String(length=280), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("public_bio")
        batch_op.drop_column("public_profile")
