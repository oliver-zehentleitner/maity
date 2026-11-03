"""The owner's digest records what it showed (docs/api.md §5.3): `request.not_listening`, the
lines a digest request shows, and `not_listening_seen`, what each owner answered `seen` to,
one row per human and instance. An open digest request filed before has no lines; the next
hour sees a change, withdraws it and files a new one, so nothing needs carrying over. Answers
given before this change recorded only their time; the next hour asks once more about what is
still away, which the owner then answers under the new rule. An index on `agent_session`
(credential, start) serves the digest's and the bell's look at each credential's latest session.
The downgrade drops all three; the credential's foreign key keeps the unique (credential, live).

Revision ID: 20261103210000_digest_seen
Revises: 20261103100000_session_confirmed
Create Date: 2026-11-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE, UtcDateTime

revision: str = "20261103210000_digest_seen"
down_revision: str | None = "20261103100000_session_confirmed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    with op.batch_alter_table("request") as batch:
        batch.add_column(sa.Column("not_listening", JSON_VALUE))
    op.create_table(
        "not_listening_seen",
        sa.Column("human_id", sa.String(40), sa.ForeignKey("human.id"), nullable=False),
        sa.Column("membership_id", sa.Integer(), sa.ForeignKey("membership.id"), nullable=False),
        sa.Column("instance", sa.String(5), nullable=False),
        sa.Column("last_seen_at", UtcDateTime(), nullable=False),
        sa.Column("since", UtcDateTime()),
        sa.PrimaryKeyConstraint("human_id", "membership_id", "instance"),
        sa.Index("ix_not_listening_seen_membership", "membership_id"),
        **MYSQL,
    )
    op.create_index(
        "ix_agent_session_credential_started", "agent_session", ["credential_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_session_credential_started", table_name="agent_session")
    # The table alone: its index goes with it, and dropping it first fails on MariaDB while
    # the foreign key needs it.
    op.drop_table("not_listening_seen")
    with op.batch_alter_table("request") as batch:
        batch.drop_column("not_listening")
