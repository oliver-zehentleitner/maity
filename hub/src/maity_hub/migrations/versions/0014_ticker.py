"""The change ticker: dedupe keys and subscriptions (docs/api.md §17).

An item is an event of kind `ticker`. `ticker_dedupe` holds each automatic or manual
item's `dedupe_key` under a unique (project, key) so that two sources observing the
same merge, deploy or release write one item (§17.7). `ticker_subscription` holds one
membership's follow and mute lists (§17.8); no row means both empty.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "ticker_dedupe",
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("seq", BIG_ID, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_ticker_dedupe_project_id_project")
        ),
        sa.PrimaryKeyConstraint("project_id", "dedupe_key", name=op.f("pk_ticker_dedupe")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "ticker_subscription",
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("follow", JSON_VALUE, nullable=False),
        sa.Column("mute", JSON_VALUE, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_ticker_subscription_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("membership_id", name=op.f("pk_ticker_subscription")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("ticker_subscription")
    op.drop_table("ticker_dedupe")
