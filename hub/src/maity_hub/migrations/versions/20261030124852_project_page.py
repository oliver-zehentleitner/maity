"""A project's public page: the choice and the text (docs/api.md §16.9).

`project.public_page` is `off` until the namespace owner turns it on, `public_about` the
Markdown text on it (at most 4 KiB, checked by the API).

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261030124852_project_page
Revises: 20261030125107_person_links
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261030124852_project_page"
down_revision: str | None = "20261030125107_person_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("public_page", sa.String(length=8), server_default="off", nullable=False)
        )
        batch_op.add_column(sa.Column("public_about", MARKDOWN_TEXT, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("public_about")
        batch_op.drop_column("public_page")
