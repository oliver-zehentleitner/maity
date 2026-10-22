"""Briefing on joins and memberships (docs/api.md §3.1, §5.2, §6.2).

`join_link.briefing` holds what the human wrote for the agent until the
exchange; `membership.briefing` is where it lives from then on, editable by
`PATCH …/members/{id}`. Both are Markdown, at most 16 KiB (checked by the API).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.add_column(sa.Column("briefing", MARKDOWN_TEXT, nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("briefing", MARKDOWN_TEXT, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("briefing")
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("briefing")
