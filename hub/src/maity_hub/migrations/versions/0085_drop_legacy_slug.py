"""The slug a project had at the namespace migration is dropped (docs/api.md §6.25, §16.11).

`legacy_slug` froze the slug of every project at migration 0060 for the addresses outside the
API that predated the namespace (the old badge and swarm page, a forge's webhook). The
maintainer's rule for the alpha is to keep no such layer, so the addresses and the column
go. Downgrading adds the column back, empty: the frozen values are not recoverable.

Revision ID: 0085
Revises: 0084
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("legacy_slug")


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("legacy_slug", sa.String(length=64), nullable=True))
