"""A dormant agent instance (docs/api.md §6.17, "A dormant instance").

`credential.dormant_since` and `dormant_by` are both set while the instance is put to rest
and both null while it is awake. `dormant_by` is a member id (`agt-…` the instance itself,
`hum-…` its owner or an admin).

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261031052946_dormant_agent_ins
Revises: 20261030180344_request_nonces
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261031052946_dormant_agent_ins"
down_revision: str | None = "20261030180344_request_nonces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dormant_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("dormant_by", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_column("dormant_by")
        batch_op.drop_column("dormant_since")
