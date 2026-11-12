"""Where a membership's notifications begin, stored with it: `membership.joined_seq`, the
project's newest event seq when the membership was made (hub/context/notifications.md).

Before, every bell read found it again with `max(event.seq)` over the project's events at or
before `joined_at`: on PostgreSQL a scan of `event` on each read. The hub now writes it with
each new membership (`events.newest_seq`); this revision fills it for the memberships there,
removed ones included, with that same query, so a member's items stay exactly what they were.

The backfill goes by membership id in bounded batches and fills only rows still without a
value, so a run that stopped part way is safe to start again; the column is added only when
missing and made NOT NULL at the end. On MariaDB each batch commits on its own (DDL commits
there anyway); on PostgreSQL and SQLite it stays inside the chain's one transaction, which
`migrations/env.py` keeps so a failed run leaves the schema the running hub expects. The
downgrade drops the column; the hub before it reads the position from the log again.

Revision ID: 20261112190000_join_seq
Revises: 20261112170000_notif_recipients
Create Date: 2026-11-12
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext

import sqlalchemy as sa
from alembic import op

from maity_hub.types import BIG_ID

revision: str = "20261112190000_join_seq"
down_revision: str | None = "20261112170000_notif_recipients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH = 500  # memberships per batch

event = sa.table(
    "event",
    sa.column("seq", sa.BigInteger),
    sa.column("project_id", sa.String),
    sa.column("at", sa.DateTime),
)
membership = sa.table(
    "membership",
    sa.column("id", sa.Integer),
    sa.column("project_id", sa.String),
    sa.column("joined_at", sa.DateTime),
    sa.column("joined_seq", sa.BigInteger),
)


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("membership")}
    if "joined_seq" not in columns:  # a run that stopped on MariaDB may have added it
        op.add_column("membership", sa.Column("joined_seq", BIG_ID, nullable=True))
    backfill()
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.alter_column("joined_seq", existing_type=BIG_ID, nullable=False)


def backfill(batch: int = BATCH) -> int:
    """Fill `joined_seq` where it is still null, `batch` memberships at a time, with the
    query the bell ran on each read until now; returns how many rows it filled."""
    filled = 0
    while True:
        with _each_batch_commits():
            bind = op.get_bind()
            ids = list(
                bind.execute(
                    sa.select(membership.c.id)
                    .where(membership.c.joined_seq.is_(None))
                    .order_by(membership.c.id)
                    .limit(batch)
                ).scalars()
            )
            if not ids:
                return filled
            found = bind.execute(
                sa.select(membership.c.id, sa.func.coalesce(sa.func.max(event.c.seq), 0))
                .select_from(membership)
                .outerjoin(
                    event,
                    sa.and_(
                        event.c.project_id == membership.c.project_id,
                        event.c.at <= membership.c.joined_at,
                    ),
                )
                .where(membership.c.id.in_(ids))
                .group_by(membership.c.id)
            ).all()
            bind.execute(
                membership.update()
                .where(membership.c.id == sa.bindparam("row_id"))
                .values(joined_seq=sa.bindparam("seq")),
                [{"row_id": row_id, "seq": int(seq)} for row_id, seq in found],
            )
            filled += len(found)


@contextmanager
def _each_batch_commits() -> Iterator[None]:
    """On MariaDB, where DDL commits anyway, one batch's update commits alone; elsewhere the
    chain's transaction holds it (module docstring)."""
    context = op.get_context()
    mariadb = context.dialect.name in ("mariadb", "mysql")
    with context.autocommit_block() if mariadb else nullcontext():
        yield


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("joined_seq")
