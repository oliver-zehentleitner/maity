"""Where the ticker's merge announcements start (docs/api.md §17.4).

`ticker_source.merges_since` is the moment `settings.ticker.enabled` was switched on:
the probe announces the merges after it and nothing older. `scanned_until` is the
moment up to which every merge has been read; a round cut by its page bound leaves
`resume_page` and `round_started`, and the next round goes on from there. A project
that has the
ticker on already gets the moment of this upgrade: merges from before it are not
announced, as for a project switched on today.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-23
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0020"
down_revision: str | None = "0019"
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
        "ticker_source",
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("merges_since", TIMESTAMP, nullable=False),
        sa.Column("scanned_until", TIMESTAMP, nullable=True),
        sa.Column("resume_page", sa.Integer(), nullable=True),
        sa.Column("round_started", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_ticker_source_project_id_project")
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_ticker_source")),
        **TABLE_OPTIONS,
    )
    conn = op.get_bind()
    project = sa.table("project", sa.column("id", sa.String), sa.column("settings", JSON_VALUE))
    source = sa.table(
        "ticker_source", sa.column("project_id", sa.String), sa.column("merges_since", TIMESTAMP)
    )
    now = datetime.now(UTC).replace(tzinfo=None)  # stored naive UTC, as UtcDateTime does
    for row in conn.execute(sa.select(project.c.id, project.c.settings)):
        settings = (
            row.settings if isinstance(row.settings, dict) else json.loads(row.settings or "{}")
        )
        if (settings.get("ticker") or {}).get("enabled"):
            conn.execute(sa.insert(source).values(project_id=row.id, merges_since=now))


def downgrade() -> None:
    op.drop_table("ticker_source")
