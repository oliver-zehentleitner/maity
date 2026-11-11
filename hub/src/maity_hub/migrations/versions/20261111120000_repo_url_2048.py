"""A stored repository URL is at most 2048 characters (docs/api.md §6.1).

The column was 255. A nested GitLab path can pass that, and the value the
contract stores is 2048 characters. Existing rows are not normalised: a URL
stored before this change keeps its spelling, including a capital host or a
`.git` suffix. A later PATCH that sends that same URL stores the normalised
form, which is a different value, so the owner's confirmation is cleared.
The downgrade refuses while any stored URL is longer than the old column:
shortening one would name a different repository.

Revision ID: 20261111120000_repo_url_2048
Revises: 20261111010000_expert_fields
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261111120000_repo_url_2048"
down_revision: str | None = "20261111010000_expert_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = 255
_NEW = 2048


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.alter_column(
            "repository_url",
            existing_type=sa.String(length=_OLD),
            type_=sa.String(length=_NEW),
            existing_nullable=True,
        )


def downgrade() -> None:
    rows = op.get_bind().execute(
        sa.text("SELECT repository_url FROM project WHERE repository_url IS NOT NULL")
    )
    longer = sum(1 for (url,) in rows if len(url) > _OLD)
    if longer:
        raise RuntimeError(
            f"{longer} repository URL(s) are longer than {_OLD} characters; "
            "the previous column cannot hold them"
        )
    with op.batch_alter_table("project") as batch:
        batch.alter_column(
            "repository_url",
            existing_type=sa.String(length=_NEW),
            type_=sa.String(length=_OLD),
            existing_nullable=True,
        )
