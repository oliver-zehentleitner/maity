"""Mentions on cards and requests, and a human's latest login (docs/api.md §8.6, §16.1).

`card.mentions` and `request.mentions` hold what the hub resolved from the scanned text
at write time; null for what was written before this ran, which reads as no mentions.
`human.last_login_at` stays null until the next successful login.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mentions", JSON_VALUE, nullable=True))
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mentions", JSON_VALUE, nullable=True))
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_login_at", TIMESTAMP, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("last_login_at")
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("mentions")
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("mentions")
