"""Cover by a substitute (docs/api.md §6.12): what moved for whom, on cards and requests,
and the cover a membership is under.

Revision ID: 0083
Revises: 0104
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0083"
down_revision: str | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cover", JSON_VALUE, nullable=True))
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cover", JSON_VALUE, nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cover_state", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("cover_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_membership_cover_by_membership"), "membership", ["cover_by"], ["id"]
        )
        batch_op.add_column(sa.Column("cover_since", TIMESTAMP, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("cover_since")
        batch_op.drop_constraint(
            batch_op.f("fk_membership_cover_by_membership"), type_="foreignkey"
        )
        batch_op.drop_column("cover_by")
        batch_op.drop_column("cover_state")
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_column("cover")
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("cover")
