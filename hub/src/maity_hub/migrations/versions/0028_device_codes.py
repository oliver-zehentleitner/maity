"""Device codes and the device cookie (docs/api.md §2.6.2, §2.6.5).

`device_code` holds a code made by one session, redeemed by one new browser and
approved by number matching; the code and the pending cookie only as `sha256`.
`human_device` holds the device cookie's values per human, also hashed; it decides
nothing and only says whether a browser signed in to that account before.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
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
        "device_code",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("pending_hash", sa.String(length=64), nullable=True),
        sa.Column("redeemed_at", TIMESTAMP, nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("browser", sa.String(length=64), nullable=True),
        sa.Column("os", sa.String(length=64), nullable=True),
        sa.Column("new_device", sa.Boolean(), nullable=True),
        sa.Column("match_number", sa.Integer(), nullable=True),
        sa.Column("choices", JSON_VALUE, nullable=True),
        sa.Column("next", sa.String(length=512), nullable=True),
        sa.Column("approved_at", TIMESTAMP, nullable=True),
        sa.Column("session_public_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_device_code_human_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_code")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_device_code_code_hash")),
        sa.UniqueConstraint("pending_hash", name=op.f("uq_device_code_pending_hash")),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_device_code_human_id", "device_code", ["human_id"])
    op.create_index("ix_device_code_session_hash", "device_code", ["session_hash"])
    op.create_table(
        "human_device",
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_human_device_human_id_human")
        ),
        sa.PrimaryKeyConstraint("value_hash", "human_id", name=op.f("pk_human_device")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("human_device")
    # The indexes go with the table; MariaDB refuses to drop one a foreign key needs.
    op.drop_table("device_code")
