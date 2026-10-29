"""A merge closes the loop (docs/api.md §6.6, §6.1 `merged_closes`).

`project.merged_closes` is the policy (`notify` by default, `auto`). On the card,
`merge_report` names the report a merge was observed on (a digest of the report as the
agent sent it) and `merge_told` whether `task_merged` went out for it: once per report,
and caught up when the card returns to `review` with the same report.

Revision ID: 0070
Revises: 0068
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("merged_closes", sa.String(length=8), nullable=False, server_default="notify")
        )
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("merge_report", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("merge_told", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("merge_told")
        batch_op.drop_column("merge_report")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("merged_closes")
