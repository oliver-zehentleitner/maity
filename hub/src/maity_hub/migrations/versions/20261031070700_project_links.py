"""A project's links to issues, wiki, discussions and chat (docs/api.md §6.11, §16.9).

`project.links` is a JSON object with up to four keys (`issues`, `wiki`, `discussions`,
`chat`), each an https URL, set under `project:admin`; absent where none is set.

Revision ID: 20261031070700_project_links
Revises: 20261031150000_join_takes_over
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031070700_project_links"
down_revision: str | None = "20261031150000_join_takes_over"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("links", JSON_VALUE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("links")
