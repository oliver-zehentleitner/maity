"""Instance settings and mail (docs/api.md §2.6.6, §16.2, §16.3).

`instance_setting` holds one row per name the instance admin set (names from the
registry in `maity_hub.instance_settings`); no row means the environment's value or the
default. `instance_secret` holds the admin-set secrets sealed with `MAITY_SECRET_KEY`
(today the SMTP password), never a setting. `mail_delivery` holds one row per mail
handed to SMTP or held back, by budget kind and outcome, for the counters of the last
hour; no address and no content.

A downgrade drops all three: the admin then sets the mail values and the SMTP password
again.

Revision ID: 0026
Revises: 0020
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0026"
down_revision: str | None = "0020"
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
        "instance_setting",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", JSON_VALUE, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["human.id"], name=op.f("fk_instance_setting_updated_by_human")
        ),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_instance_setting")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "instance_secret",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("sealed", sa.Text(), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["human.id"], name=op.f("fk_instance_secret_updated_by_human")
        ),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_instance_secret")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "mail_delivery",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_delivery")),
        sqlite_autoincrement=True,
        **TABLE_OPTIONS,
    )
    op.create_index("ix_mail_delivery_at", "mail_delivery", ["at"])


def downgrade() -> None:
    op.drop_index("ix_mail_delivery_at", table_name="mail_delivery")
    op.drop_table("mail_delivery")
    op.drop_table("instance_secret")
    op.drop_table("instance_setting")
