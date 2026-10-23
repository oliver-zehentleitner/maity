"""Deleting an agent profile (docs/api.md §6.3).

A deleted profile keeps its row as a tombstone (`deleted_at`), so that every event,
report and removed member that names it still resolves. Its handle is free for a new
profile of the same owner at once: the handle is unique per owner among the profiles
that are not deleted, through the hub's at-most-one marker (`live`, true or NULL; NULL
never collides), which every engine enforces the same way.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("agent_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", TIMESTAMP, nullable=True))
        batch_op.add_column(
            sa.Column("live", sa.Boolean(), server_default=sa.true(), nullable=True)
        )
    op.execute(sa.text("UPDATE agent_profile SET live = :yes").bindparams(yes=True))
    with op.batch_alter_table("agent_profile", schema=None) as batch_op:
        # The new key first: on MariaDB the owner's foreign key needs an index that
        # starts with owner_id at every moment.
        batch_op.create_unique_constraint(
            op.f("uq_agent_profile_owner_id_handle_live"), ["owner_id", "handle", "live"]
        )
        batch_op.drop_constraint(op.f("uq_agent_profile_owner_id_handle"), type_="unique")
        batch_op.create_check_constraint(
            op.f("ck_agent_profile_live_true_or_null"), "live IS NOT FALSE"
        )


def _free_handles() -> None:
    """Before the old key comes back: a deleted profile whose handle a newer profile of
    the same owner took gets its id appended to it (`handle~<id>`), the only way the
    old one-handle-per-owner key can hold again."""
    bind = op.get_bind()
    profile = sa.table(
        "agent_profile",
        sa.column("id", sa.String),
        sa.column("owner_id", sa.String),
        sa.column("handle", sa.String),
        sa.column("deleted_at", TIMESTAMP),
    )
    rows = bind.execute(
        sa.select(profile.c.id, profile.c.owner_id, profile.c.handle, profile.c.deleted_at)
    ).all()
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        seen[(row.owner_id, row.handle)] = seen.get((row.owner_id, row.handle), 0) + 1
    for row in rows:
        if row.deleted_at is not None and seen[(row.owner_id, row.handle)] > 1:
            bind.execute(
                sa.update(profile)
                .where(profile.c.id == row.id)
                .values(handle=f"{row.handle}~{row.id}"[:64])  # the column holds 64
            )


def downgrade() -> None:
    _free_handles()
    with op.batch_alter_table("agent_profile", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_agent_profile_live_true_or_null"), type_="check")
        batch_op.create_unique_constraint(
            op.f("uq_agent_profile_owner_id_handle"), ["owner_id", "handle"]
        )
        batch_op.drop_constraint(op.f("uq_agent_profile_owner_id_handle_live"), type_="unique")
    with op.batch_alter_table("agent_profile", schema=None) as batch_op:
        batch_op.drop_column("live")
        batch_op.drop_column("deleted_at")
