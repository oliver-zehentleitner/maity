"""Durable onboarding version and one check-in per membership (§6.1).

Revision ID: 0042
Revises: 0039 (rechain at merge; reservation approved by the coordinator)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0042"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("onboarding_version", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("membership") as batch:
        batch.add_column(sa.Column("onboarded_at", TIMESTAMP, nullable=True))
    # A historical claim already means work started. Keep the first timestamp, even if
    # its card was released/closed or claimed on the member's behalf.
    bind = op.get_bind()
    events = sa.table(
        "event",
        sa.column("project_id", sa.String),
        sa.column("kind", sa.String),
        sa.column("at", TIMESTAMP),
        sa.column("payload", sa.JSON),
    )
    membership = sa.table(
        "membership",
        sa.column("project_id", sa.String),
        sa.column("agent_id", sa.String),
        sa.column("onboarded_at", TIMESTAMP),
        sa.column("joined_at", TIMESTAMP),
        sa.column("removed_at", TIMESTAMP),
    )
    for row in bind.execute(
        sa.select(events).where(events.c.kind == "task_claimed").order_by(events.c.at)
    ):
        holder = (row.payload or {}).get("holder")
        if isinstance(holder, str):
            bind.execute(
                sa.update(membership)
                .where(
                    membership.c.project_id == row.project_id,
                    membership.c.agent_id == holder,
                    membership.c.onboarded_at.is_(None),
                    membership.c.joined_at <= row.at,
                    sa.or_(membership.c.removed_at.is_(None), membership.c.removed_at >= row.at),
                )
                .values(onboarded_at=row.at)
            )


def downgrade() -> None:
    with op.batch_alter_table("membership") as batch:
        batch.drop_column("onboarded_at")
    with op.batch_alter_table("project") as batch:
        batch.drop_column("onboarding_version")
