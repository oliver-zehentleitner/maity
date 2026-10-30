"""The digest of the generated rules text a project's version last counted (docs/api.md §6.9).

`project.rules_text_digest`: the hub's own text is a rules input, and a start with other text
bumps `rules_version` once per project. Null for every project that exists when this runs, so
the first start after it counts the text once, as a hub that never recorded one should.

Revision ID: 0109
Revises: 0083
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0109"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch_op:
        batch_op.add_column(sa.Column("rules_text_digest", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project") as batch_op:
        batch_op.drop_column("rules_text_digest")
