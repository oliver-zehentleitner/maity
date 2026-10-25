"""Registration (docs/api.md §2.7, §16.4).

`human` gains `account_status` (`active` for every existing account, `pending` while a
registration waits for the operator), `registered_at` for an account made by
registration, and the accepted terms version with its time. `pending_registration`
holds a request whose address is not yet proven, for at most 24 hours;
`registration_block` an address that may not register until a date; `registration_lock`
is a row per address that serialises changes to its pending registrations.

Revision ID: 0047
Revises: 0025
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0047"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "account_status", sa.String(length=16), server_default="active", nullable=False
            )
        )
        batch_op.add_column(sa.Column("registered_at", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("terms_version", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("terms_accepted_at", TIMESTAMP, nullable=True))
    op.create_table(
        "pending_registration",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("address", sa.String(length=254), nullable=False),
        sa.Column("address_normalized", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("source_ip", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("language", sa.String(length=35), nullable=True),
        sa.Column("terms_version", sa.String(length=64), nullable=True),
        sa.Column("next", sa.String(length=2048), nullable=True),
        sa.Column("nonce_hash", sa.String(length=64), nullable=True),
        sa.Column("wrong_passwords", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("voided_at", TIMESTAMP, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_registration")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_pending_registration_address_normalized"),
        "pending_registration",
        ["address_normalized"],
        unique=False,
    )
    op.create_table(
        "registration_lock",
        sa.Column("address_normalized", sa.String(length=254), nullable=False),
        sa.PrimaryKeyConstraint("address_normalized", name=op.f("pk_registration_lock")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "registration_block",
        sa.Column("address_normalized", sa.String(length=254), nullable=False),
        sa.Column("until", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("address_normalized", name=op.f("pk_registration_block")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("registration_block")
    op.drop_table("registration_lock")
    op.drop_table("pending_registration")  # its index goes with it
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.drop_column("terms_accepted_at")
        batch_op.drop_column("terms_version")
        batch_op.drop_column("registered_at")
        batch_op.drop_column("account_status")
