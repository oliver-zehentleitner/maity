"""Landing variants and campaigns: what §16.7.2 stores (docs/api.md).

`instance_landing.variants` and `.campaigns` are the admin's setting; `pending_registration.origin`
is the campaign link a registration came by until its address is verified; `campaign_origin` keeps
it with the account until the first agent exchange or 30 days; `campaign_count` holds the daily
sums (views, registrations, activations) per variant and campaign, `""` for none.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261031065451_landing_variants
Revises: 20261031011834_rate_counts
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "20261031065451_landing_variants"
down_revision: str | None = "20261031011834_rate_counts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "campaign_count",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("variant", sa.String(length=40), nullable=False),
        sa.Column("campaign", sa.String(length=40), nullable=False),
        sa.Column("views", sa.Integer(), server_default="0", nullable=False),
        sa.Column("registrations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("activations", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("day", "variant", "campaign", name=op.f("pk_campaign_count")),
        **MYSQL,
    )
    op.create_table(
        "campaign_origin",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("variant", sa.String(length=40), nullable=False),
        sa.Column("campaign", sa.String(length=40), nullable=True),
        sa.Column("registered_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_campaign_origin_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_campaign_origin")),
        **MYSQL,
    )
    with op.batch_alter_table("instance_landing", schema=None) as batch_op:
        batch_op.add_column(sa.Column("variants", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("campaigns", JSON_VALUE, nullable=True))
    with op.batch_alter_table("pending_registration", schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("pending_registration", schema=None) as batch_op:
        batch_op.drop_column("origin")
    with op.batch_alter_table("instance_landing", schema=None) as batch_op:
        batch_op.drop_column("campaigns")
        batch_op.drop_column("variants")
    op.drop_table("campaign_origin")
    op.drop_table("campaign_count")
