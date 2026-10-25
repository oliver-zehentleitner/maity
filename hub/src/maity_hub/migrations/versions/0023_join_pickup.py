"""The runner's join pickup and supervised sessions (docs/api.md §15.9, §15.11).

`join_link` records the placement, the runner and the generation of a pickup;
`agent_session.supervisor` records `maity-runner/<version>` for a session a runner
supervises.

Revision ID: 0023
Revises: 0042
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.add_column(sa.Column("placement_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("runner_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("generation", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_join_link_placement_id_placement"), "placement", ["placement_id"], ["id"]
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_join_link_runner_id_runner"), "runner", ["runner_id"], ["id"]
        )
        batch_op.create_index(
            batch_op.f("ix_join_link_placement_id"), ["placement_id"], unique=False
        )
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("supervisor", sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.drop_column("supervisor")
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        # The foreign keys first: MariaDB refuses to drop an index a foreign key needs.
        batch_op.drop_constraint(batch_op.f("fk_join_link_runner_id_runner"), type_="foreignkey")
        batch_op.drop_constraint(
            batch_op.f("fk_join_link_placement_id_placement"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_join_link_placement_id"))
        batch_op.drop_column("generation")
        batch_op.drop_column("runner_id")
        batch_op.drop_column("placement_id")
