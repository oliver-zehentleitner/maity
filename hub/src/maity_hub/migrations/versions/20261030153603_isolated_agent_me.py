"""An agent member a human isolated (docs/api.md §6.2, "Isolation").

`membership.isolated_reason`, `isolated_since` and `isolated_by` are all null while the
agent is free, and all set while it is isolated.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261030153603_isolated_agent_me
Revises: 20261030124852_project_page
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261030153603_isolated_agent_me"
down_revision: str | None = "20261030124852_project_page"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("isolated_reason", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("isolated_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("isolated_by", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("isolated_by")
        batch_op.drop_column("isolated_since")
        batch_op.drop_column("isolated_reason")
