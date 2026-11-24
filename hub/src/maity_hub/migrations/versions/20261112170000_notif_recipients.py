"""The humans a message may make a notification of (§18.1): `notification_recipient`.

`events.emit` writes a row per human with the message from now on; the notifications read
these rows instead of matching each event's JSON as text (hub/context/notifications.md
fc79a4a6). The backfill covers the messages of the notifications' window (30 days), the only
ones read; older messages are never an item, so they get no row.

The backfill goes by `seq` in bounded batches and skips rows already there, so a run that
stopped part way is safe to start again. On MariaDB each batch commits on its own (DDL commits
there anyway); on PostgreSQL and SQLite it stays inside the chain's one transaction, which
`migrations/env.py` keeps so a failed run leaves the schema the running hub expects. The rows
are read the way `events.notification_recipients` reads a new message, inlined here so a
later change there does not change what this revision wrote.

Revision ID: 20261112170000_notif_recipients
Revises: 20261112150000_nudged_through
Create Date: 2026-11-12
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "20261112170000_notif_recipients"
down_revision: str | None = "20261112150000_nudged_through"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}

WINDOW = timedelta(days=30)  # notifications.items.WINDOW when this revision was written
BATCH = 2000  # message events per batch
HUMAN = "hum-"

event = sa.table(
    "event",
    sa.column("seq", BIG_ID),
    sa.column("project_id", sa.String(40)),
    sa.column("kind", sa.String(32)),
    sa.column("at", TIMESTAMP),
    sa.column("audience", JSON_VALUE),
    sa.column("conversation_id", sa.String(40)),
    sa.column("payload", JSON_VALUE),
)
human = sa.table("human", sa.column("id", sa.String(40)))
recipient = sa.table(
    "notification_recipient",
    sa.column("human_id", sa.String(40)),
    sa.column("seq", BIG_ID),
    sa.column("project_id", sa.String(40)),
    sa.column("at", TIMESTAMP),
    sa.column("chat", sa.Boolean()),
    sa.column("mention", sa.Boolean()),
)


def upgrade() -> None:
    bind = op.get_bind()
    # Each piece only when missing: on MariaDB every DDL statement commits alone, so a run
    # that stopped may have left the table without its index, or both.
    if not sa.inspect(bind).has_table("notification_recipient"):
        op.create_table(
            "notification_recipient",
            sa.Column("human_id", sa.String(length=40), nullable=False),
            sa.Column("seq", BIG_ID, nullable=False),
            sa.Column("project_id", sa.String(length=40), nullable=False),
            sa.Column("at", TIMESTAMP, nullable=False),
            sa.Column("chat", sa.Boolean(), nullable=False),
            sa.Column("mention", sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(
                ["human_id"], ["human.id"], name=op.f("fk_notification_recipient_human_id_human")
            ),
            sa.ForeignKeyConstraint(
                ["seq"], ["event.seq"], name=op.f("fk_notification_recipient_seq_event")
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["project.id"],
                name=op.f("fk_notification_recipient_project_id_project"),
            ),
            sa.PrimaryKeyConstraint("seq", "human_id", name=op.f("pk_notification_recipient")),
            **MYSQL,
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("notification_recipient")}
    if "ix_notification_recipient_window" not in indexes:
        op.create_index(
            "ix_notification_recipient_window",
            "notification_recipient",
            ["human_id", "project_id", "at", "seq"],
        )
    backfill(datetime.now(UTC).replace(tzinfo=None) - WINDOW)


def backfill(since: datetime, batch: int = BATCH) -> int:
    """Rows for the message events at or after `since` (naive UTC), `batch` events at a
    time; returns how many rows it wrote."""
    written, after = 0, None
    while True:
        with _each_batch_commits():
            bind = op.get_bind()
            query = (
                sa.select(
                    event.c.seq,
                    event.c.project_id,
                    event.c.at,
                    event.c.audience,
                    event.c.conversation_id,
                    event.c.payload,
                )
                .where(event.c.kind == "message", event.c.at >= since)
                .order_by(event.c.seq)
                .limit(batch)
            )
            if after is not None:
                query = query.where(event.c.seq > after)
            messages = bind.execute(query).all()
            if not messages:
                return written
            after = messages[-1].seq
            wanted = [
                {"seq": message.seq, "project_id": message.project_id, "at": message.at, **row}
                for message in messages
                for row in _recipients(message.audience, message.conversation_id, message.payload)
            ]
            if not wanted:
                continue
            seqs = sorted({row["seq"] for row in wanted})
            there = {
                (row.human_id, row.seq)
                for row in bind.execute(
                    sa.select(recipient.c.human_id, recipient.c.seq).where(
                        recipient.c.seq.in_(seqs)
                    )
                )
            }
            known = set(
                bind.execute(
                    sa.select(human.c.id).where(
                        human.c.id.in_(sorted({row["human_id"] for row in wanted}))
                    )
                ).scalars()
            )
            rows = [
                row
                for row in wanted
                if row["human_id"] in known and (row["human_id"], row["seq"]) not in there
            ]
            if rows:
                bind.execute(recipient.insert(), rows)
                written += len(rows)


@contextmanager
def _each_batch_commits() -> Iterator[None]:
    """On MariaDB, where DDL commits anyway, one batch's insert commits alone; elsewhere the
    chain's transaction holds it (module docstring)."""
    context = op.get_context()
    mariadb = context.dialect.name in ("mariadb", "mysql")
    with context.autocommit_block() if mariadb else nullcontext():
        yield


def _recipients(audience: Any, conversation_id: str | None, payload: Any) -> list[dict[str, Any]]:
    chat = (
        {
            token.removeprefix("member:")
            for token in audience or []
            if isinstance(token, str) and token.startswith(f"member:{HUMAN}")
        }
        if conversation_id is not None
        else set()
    )
    mentions = (payload or {}).get("mentions") if isinstance(payload, dict) else None
    mention = {
        m["member_id"]
        for m in mentions or []
        if isinstance(m, dict)
        and isinstance(m.get("member_id"), str)
        and m["member_id"].startswith(HUMAN)
    }
    return [
        {"human_id": human_id, "chat": human_id in chat, "mention": human_id in mention}
        for human_id in sorted(chat | mention)
    ]


def downgrade() -> None:
    # The index goes with the table: MariaDB refuses to drop one alone while a foreign key
    # needs it (error 1553).
    op.drop_table("notification_recipient")
