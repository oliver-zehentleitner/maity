"""The Keep the Why policy of a project (docs/api.md §6.1, §6.23).

`keep_the_why_policy` holds what a human with `project:admin` set (`required` or
`optional`); `NULL` means nobody did, and the project reads `required` under the memory
provider `keep-the-why`, `optional` otherwise. `keep_the_why_defaults` (`adopt` or `ask`)
says whether a joining agent takes the repository's personal defaults; projects made
before read `adopt`. The memory provider itself stays in `keep_the_why`.

Revision ID: 0079
Revises: 0077
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("keep_the_why_policy", sa.String(length=16), nullable=True))
        batch_op.add_column(
            sa.Column(
                "keep_the_why_defaults",
                sa.String(length=8),
                server_default="adopt",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("keep_the_why_defaults")
        batch_op.drop_column("keep_the_why_policy")
