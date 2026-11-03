"""A session's confirmation is its own: `confirmed_at` and `confirmed_by` on the session
(docs/api.md §2.6.5). Before this change a sign-in counted as confirmed while its
`session_created` record was marked read, and only an allowed session could mark it, so every
such read mark was a confirmation. The upgrade carries each one over: `confirmed_at` is the
time of the read mark, `confirmed_by` the session that made it. A record without `read_by`
was not read by a session and confirms nothing. The downgrade drops the columns. A session
confirmed after the upgrade had its record marked read by the same call, so the old rule reads
it as confirmed too, as long as that record exists with its `read_by`: every completed sign-in
writes one, and a read mark always sets `read_at` and `read_by` together.

Revision ID: 20261103100000_session_confirmed
Revises: 20261102230000_card_note_version
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from maity_hub.types import UtcDateTime

revision: str = "20261103100000_session_confirmed"
down_revision: str | None = "20261102230000_card_note_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("human_session") as batch:
        batch.add_column(sa.Column("confirmed_at", UtcDateTime()))
        batch.add_column(sa.Column("confirmed_by", sa.String(40)))
    record = sa.table(
        "account_record",
        sa.column("type", sa.String()),
        sa.column("data", JSON_VALUE),
        sa.column("read_at", UtcDateTime()),
        sa.column("read_by", sa.String()),
    )
    session = sa.table(
        "human_session",
        sa.column("public_id", sa.String()),
        sa.column("confirmed_at", UtcDateTime()),
        sa.column("confirmed_by", sa.String()),
    )
    # One statement, joined on the record's session id, so the exclusive lock the column
    # change takes on `human_session` is held for one pass, not one round trip per mark.
    op.execute(
        session.update()
        .where(
            record.c.type == "session_created",
            record.c.read_at.is_not(None),
            record.c.read_by.is_not(None),
            session.c.public_id == record.c.data["session_id"].as_string(),
            session.c.confirmed_at.is_(None),
        )
        .values(confirmed_at=record.c.read_at, confirmed_by=record.c.read_by)
    )


def downgrade() -> None:
    with op.batch_alter_table("human_session") as batch:
        batch.drop_column("confirmed_by")
        batch.drop_column("confirmed_at")
