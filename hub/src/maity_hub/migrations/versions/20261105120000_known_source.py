"""Where a human's sign-ins completed: `known_source` holds, per human, a keyed fingerprint of
each source address a sign-in completed from and the time of the last one (docs/api.md §2.1).
Past the limit of wrong passwords, the password signs in only from such a source. The
fingerprint is an HMAC of the address, never the address; a row goes 30 days after its last
sign-in and with the account (§2.9). The key is derived from `MAITY_SECRET_KEY`, or where none is
set from the per-address lock's pepper, which the hub makes at first use (`addresses.prepare`);
this migration makes no key. The downgrade drops the table: until a sign-in completes again, no
source is known, and the password waits out the window from everywhere.

Revision ID: 20261105120000_known_source
Revises: 20261105090000_restricted_text
Create Date: 2026-11-05
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261105120000_known_source"
down_revision: str | None = "20261105090000_restricted_text"
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
        "known_source",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("last_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_known_source_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", "fingerprint", name=op.f("pk_known_source")),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_known_source_last_at", "known_source", ["last_at"])


def downgrade() -> None:
    op.drop_index("ix_known_source_last_at", table_name="known_source")
    op.drop_table("known_source")
