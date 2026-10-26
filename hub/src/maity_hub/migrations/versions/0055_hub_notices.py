"""Hub-filed notices (docs/api.md §7, §15.7).

`request.filed_by` is `hub` on a personal request the hub files on an agent's behalf:
the notice of an agent's outage. A placement keeps its open outage — since when, and the
notice filed for it — so that later reports of the same outage file nothing.

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("filed_by", sa.String(length=8), nullable=True))
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.add_column(sa.Column("outage_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("outage_request_id", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.drop_column("outage_request_id")
        batch_op.drop_column("outage_since")
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("filed_by")
