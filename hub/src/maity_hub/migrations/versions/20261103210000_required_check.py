"""A project names its required check: `repository_required_check` on the project
(docs/api.md §6.1 `repository.required_check`), null by default and for every project before
this change. The downgrade drops the column; the name is a setting, nothing derived from it is
stored elsewhere.

Revision ID: 20261103210000_required_check
Revises: 20261103100000_session_confirmed
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103210000_required_check"
down_revision: str | None = "20261103100000_session_confirmed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("repository_required_check", sa.String(200)))


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_column("repository_required_check")
