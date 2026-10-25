"""Availability: a member's limit, its availability policy and the outage the hub tracks;
the project's coordinator seats (docs/api.md §6.1, §6.12).

An agent's limit sits on its membership, a human's on the account (it applies to every
membership of it). `availability_state` and `availability_since` are the state the hub
last announced, so that a change is announced once; `outage_since` is when the current
outage began, the start the 24-hour lease bound counts from.

Revision ID: 0024
Revises: 0037
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0024"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("availability_policy", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("limit_until", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("limit_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("limit_source", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("limit_harness", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("limit_reason", MARKDOWN_TEXT, nullable=True))
        batch_op.add_column(sa.Column("limit_placement_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("availability_state", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("availability_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("outage_since", TIMESTAMP, nullable=True))
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(sa.Column("limit_until", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("limit_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("limit_reason", MARKDOWN_TEXT, nullable=True))
        batch_op.add_column(sa.Column("limit_show_reason_in", JSON_VALUE, nullable=True))
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "coordinator", sa.String(length=48), server_default="role:admin", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("coordinator_substitute", sa.String(length=40), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("coordinator_substitute")
        batch_op.drop_column("coordinator")
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("limit_show_reason_in")
        batch_op.drop_column("limit_reason")
        batch_op.drop_column("limit_since")
        batch_op.drop_column("limit_until")
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("outage_since")
        batch_op.drop_column("availability_since")
        batch_op.drop_column("availability_state")
        batch_op.drop_column("limit_placement_id")
        batch_op.drop_column("limit_reason")
        batch_op.drop_column("limit_harness")
        batch_op.drop_column("limit_source")
        batch_op.drop_column("limit_since")
        batch_op.drop_column("limit_until")
        batch_op.drop_column("availability_policy")
