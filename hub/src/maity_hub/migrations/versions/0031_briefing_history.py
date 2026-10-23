"""A briefing's versions (docs/api.md §6.2).

The membership carries who wrote its current briefing, its version and when it was
written; every version is kept in `member_briefing`. An agent membership that exists
already starts at version 1 with its current text, by an unknown writer at its
`joined_at`; a human membership has no briefing and stays at version 0.

Revision ID: 0031
Revises: 0020
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0031"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def _first_versions() -> None:
    bind = op.get_bind()
    membership = sa.table(
        "membership",
        sa.column("id", sa.Integer),
        sa.column("agent_id", sa.String),
        sa.column("briefing", sa.Text),
        sa.column("joined_at", TIMESTAMP),
        sa.column("briefing_version", sa.Integer),
        sa.column("briefing_updated_at", TIMESTAMP),
    )
    history = sa.table(
        "member_briefing",
        sa.column("membership_id", sa.Integer),
        sa.column("version", sa.Integer),
        sa.column("text", sa.Text),
        sa.column("at", TIMESTAMP),
    )
    rows = bind.execute(
        sa.select(membership.c.id, membership.c.briefing, membership.c.joined_at).where(
            membership.c.agent_id.is_not(None)
        )
    ).all()
    for row in rows:
        bind.execute(
            sa.update(membership)
            .where(membership.c.id == row.id)
            .values(briefing_version=1, briefing_updated_at=row.joined_at)
        )
        bind.execute(
            sa.insert(history).values(
                membership_id=row.id, version=1, text=row.briefing, at=row.joined_at
            )
        )


def upgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("briefing_version", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("briefing_by", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("briefing_updated_at", TIMESTAMP, nullable=True))
    op.create_table(
        "member_briefing",
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", MARKDOWN_TEXT, nullable=True),
        sa.Column("by", sa.String(length=40), nullable=True),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_member_briefing_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("membership_id", "version", name=op.f("pk_member_briefing")),
        **TABLE_OPTIONS,
    )
    _first_versions()


def downgrade() -> None:
    # The table takes its keys along; MariaDB refuses to drop an index a foreign key
    # needs first.
    op.drop_table("member_briefing")
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("briefing_updated_at")
        batch_op.drop_column("briefing_by")
        batch_op.drop_column("briefing_version")
