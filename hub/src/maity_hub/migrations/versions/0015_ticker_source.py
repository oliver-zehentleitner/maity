"""Where the ticker's merge announcements start (docs/api.md §17.4).

`ticker_source.merges_since` is the moment `settings.ticker.enabled` was switched on:
the probe announces the merges after it and nothing older.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0015"
down_revision: str | None = "0014"
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
    op.create_table(
        "ticker_source",
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("merges_since", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_ticker_source_project_id_project")
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_ticker_source")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("ticker_source")
