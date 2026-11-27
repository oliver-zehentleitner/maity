"""The lock of one target's public pages on MySQL/MariaDB (tsk-pwqhg0d0tznn,
hub/context/public-pages.md): `public_page_lock`, one row per target, keyed by the sha256 of the
lock's name (`public_page:{kind}:{target_id}`). A render, a takedown and the cleanup lock the row
(`SELECT … FOR UPDATE`, made if absent) until their transaction ends, as PostgreSQL holds an
advisory lock; before, the lock was a no-op off PostgreSQL. Made on every engine so the schema
stays one; on PostgreSQL and SQLite it stays empty. Empty at the upgrade: the rows are made at
first use. The downgrade drops the table, and the lock off PostgreSQL with it.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261127204153_public_page_lock
Revises: 20261125120000_steward_role
Create Date: 2026-11-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20261127204153_public_page_lock"
down_revision: str | None = "20261125120000_steward_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "public_page_lock",
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("digest", name=op.f("pk_public_page_lock")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("public_page_lock")
