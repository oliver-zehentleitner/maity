"""What revoking a runner does to its agents (docs/api.md §6.1, §15.3).

A project's `on_runner_revoke` (`keep`, `stop` or `inherit`; projects made before take
`inherit`). A runner credential records the placements its revocation stopped, which
the runner learns from its next call (`stopped`). An agent credential that a stop
revokes after the placement's grace carries when and by whom (`revoke_due_at`,
`revoke_due_by`) until it is revoked.

Revision ID: 0030
Revises: 0042
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0030"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "on_runner_revoke", sa.String(length=16), server_default="inherit", nullable=False
            )
        )
    with op.batch_alter_table("runner_credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stopped", JSON_VALUE, nullable=True))
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revoke_due_at", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("revoke_due_by", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_column("revoke_due_by")
        batch_op.drop_column("revoke_due_at")
    with op.batch_alter_table("runner_credential", schema=None) as batch_op:
        batch_op.drop_column("stopped")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("on_runner_revoke")
