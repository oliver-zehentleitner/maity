"""A project's `released_at`: set once, when the probe first finds a release's tag (§6.1).

A project that existed before gets it from the tags the probe has already found: of every
release card whose `v<version>` tag is stored as found, the earliest observation. The cache
keeps the latest observation of each ref, so this is the time it was last seen, not first;
no earlier time is recorded anywhere. A project without such a tag stays `null`. No event is
emitted for the backfill.

Revision ID: 0097
Revises: 0095
Create Date: 2026-10-29
"""

import json
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0097"
down_revision: str | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")

_project = sa.table("project", sa.column("id", sa.String), sa.column("released_at", sa.DateTime))
_card = sa.table(
    "card",
    sa.column("project_id", sa.String),
    sa.column("kind", sa.String),
    sa.column("release_version", sa.String),
)
_observation = sa.table(
    "forge_observation",
    sa.column("project_id", sa.String),
    sa.column("kind", sa.String),
    sa.column("ref", sa.String),
    sa.column("observed_at", sa.DateTime),
    sa.column("data", sa.JSON),
)


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("released_at", TIMESTAMP, nullable=True))
    conn = op.get_bind()
    releases = {
        (row.project_id, f"v{row.release_version}")
        for row in conn.execute(
            sa.select(_card.c.project_id, _card.c.release_version).where(
                _card.c.kind == "release", _card.c.release_version.is_not(None)
            )
        )
    }
    first: dict[str, datetime] = {}
    for row in conn.execute(
        sa.select(
            _observation.c.project_id,
            _observation.c.ref,
            _observation.c.observed_at,
            _observation.c.data,
        ).where(_observation.c.kind == "tag")
    ):
        data = json.loads(row.data) if isinstance(row.data, str) else row.data
        if (row.project_id, row.ref) not in releases or not (data or {}).get("found"):
            continue
        if row.project_id not in first or row.observed_at < first[row.project_id]:
            first[row.project_id] = row.observed_at
    for project_id, moment in first.items():
        conn.execute(
            _project.update().where(_project.c.id == project_id).values(released_at=moment)
        )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("released_at")
