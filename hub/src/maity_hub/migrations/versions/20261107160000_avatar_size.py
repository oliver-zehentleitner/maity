"""Public pictures, their sizes, an agent's motif and its generated picture (docs/api.md §6.10).

`avatar_size` keeps a size scaled once from the stored `avatar_image` row whose `ETag` was
`base_etag`; it is filled at the first request for that size, so the table starts empty.
`avatar_image.etag` gets an index, since the public address finds a picture by its digest.
`agent_profile.avatar_motif` holds the motif an agent chose, none for every existing one.
`avatar_image` takes the source `generated`, and the upgrade draws that picture for every
agent profile there is, deleted ones included (they show it after their upload is gone).

Revision ID: 20261107160000_avatar_size
Revises: 20261107100000_start_tabs
Create Date: 2026-11-07
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from maity_hub import avatar_generated, images
from maity_hub.types import UtcDateTime

revision: str = "20261107160000_avatar_size"
down_revision: str | None = "20261107100000_start_tabs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMAGE_BYTES = sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}
WITH_GENERATED = "source IN ('uploaded', 'forge', 'generated')"
WITHOUT_GENERATED = "source IN ('uploaded', 'forge')"
BATCH = 200

avatar_image = sa.table(
    "avatar_image",
    sa.column("owner_id", sa.String(40)),
    sa.column("source", sa.String(16)),
    sa.column("data", IMAGE_BYTES),
    sa.column("etag", sa.String(80)),
    sa.column("updated_at", UtcDateTime),
)
agent_profile = sa.table("agent_profile", sa.column("id", sa.String(40)))


def upgrade() -> None:
    op.create_table(
        "avatar_size",
        sa.Column("owner_id", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("base_etag", sa.String(length=80), nullable=False),
        sa.Column("data", IMAGE_BYTES, nullable=False),
        sa.Column("etag", sa.String(length=80), nullable=False),
        sa.CheckConstraint("size IN (32, 64, 128)", name=op.f("ck_avatar_size_size")),
        sa.PrimaryKeyConstraint("owner_id", "source", "size", name=op.f("pk_avatar_size")),
        **TABLE_OPTIONS,
    )
    with op.batch_alter_table("avatar_image") as batch_op:
        batch_op.drop_constraint(op.f("ck_avatar_image_source"), type_="check")
        batch_op.create_check_constraint(op.f("ck_avatar_image_source"), WITH_GENERATED)
        batch_op.create_index(op.f("ix_avatar_image_etag"), ["etag"], unique=False)
    with op.batch_alter_table("agent_profile") as batch_op:
        batch_op.add_column(sa.Column("avatar_motif", sa.String(length=32), nullable=True))
    conn = op.get_bind()
    ids = sorted(conn.execute(sa.select(agent_profile.c.id)).scalars())
    now = datetime.now(UTC)
    for start in range(0, len(ids), BATCH):
        rows = []
        for agent_id in ids[start : start + BATCH]:
            png = avatar_generated.draw(agent_id)
            rows.append(
                {
                    "owner_id": agent_id,
                    "source": "generated",
                    "data": png,
                    "etag": images.etag(png),
                    "updated_at": now,
                }
            )
        op.bulk_insert(avatar_image, rows)


def downgrade() -> None:
    op.execute(avatar_image.delete().where(avatar_image.c.source == "generated"))
    with op.batch_alter_table("agent_profile") as batch_op:
        batch_op.drop_column("avatar_motif")
    with op.batch_alter_table("avatar_image") as batch_op:
        batch_op.drop_index(op.f("ix_avatar_image_etag"))
        batch_op.drop_constraint(op.f("ck_avatar_image_source"), type_="check")
        batch_op.create_check_constraint(op.f("ck_avatar_image_source"), WITHOUT_GENERATED)
    op.drop_table("avatar_size")
