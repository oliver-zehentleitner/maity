"""The nonces of signed requests in the database, shared by every replica (docs/api.md §2.2).

`request_nonce` holds each spent nonce until it can no longer be replayed; `nonce_epoch` holds one
row, the moment since which the nonces are known. On PostgreSQL both are UNLOGGED: a crash or a
failover empties them together, and the hub then refuses whatever was signed before
(hub/context/replicas.md 1c65bb74). The other databases create them as ordinary tables and keep
the window in the process. Nothing is copied: the process window held nothing worth keeping.

Revision ID: 20261030180344_request_nonces
Revises: 0112
Create Date: 2026-10-30
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261030180344_request_nonces"
down_revision: str | None = "0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    unlogged = ["UNLOGGED"] if op.get_bind().dialect.name == "postgresql" else []
    op.create_table(
        "nonce_epoch",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("since", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nonce_epoch")),
        prefixes=unlogged,
        **MYSQL,
    )
    op.create_table(
        "request_nonce",
        sa.Column("credential_id", sa.String(length=40), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("credential_id", "nonce", name=op.f("pk_request_nonce")),
        prefixes=unlogged,
        **MYSQL,
    )
    op.create_index(op.f("ix_request_nonce_expires_at"), "request_nonce", ["expires_at"])
    # The epoch from now on: a hub that starts on this schema refuses nothing signed after it,
    # and the first signed request does not have to set it (auth.nonces.epoch).
    epoch = sa.table("nonce_epoch", sa.column("id", sa.Integer), sa.column("since", TIMESTAMP))
    # On PostgreSQL the database's clock, as `auth.nonces.epoch` takes it; elsewhere the epoch is
    # not read (the window is in the process).
    now = (
        sa.func.timezone("UTC", sa.func.now())
        if unlogged
        else sa.literal(datetime.now(UTC).replace(tzinfo=None))
    )
    op.execute(epoch.insert().values(id=1, since=now))


def downgrade() -> None:
    op.drop_index(op.f("ix_request_nonce_expires_at"), table_name="request_nonce")
    op.drop_table("request_nonce")
    op.drop_table("nonce_epoch")
