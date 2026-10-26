"""Subtasks, related cards and the subtask proposal policy (§6.4).

Revision ID: 0048
Revises: 0027
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("subtasks", sa.String(16), nullable=False, server_default="proposed")
        )
    with op.batch_alter_table("card") as batch:
        batch.add_column(sa.Column("parent", sa.String(40), nullable=True))
        batch.create_foreign_key(op.f("fk_card_parent_card"), "card", ["parent"], ["id"])
        batch.create_index(op.f("ix_card_parent"), ["parent"], unique=False)


def downgrade() -> None:
    # Remove the FK before its index: MariaDB can use that index for the FK.
    with op.batch_alter_table("card") as batch:
        batch.drop_constraint(op.f("fk_card_parent_card"), type_="foreignkey")
        batch.drop_index(op.f("ix_card_parent"))
        batch.drop_column("parent")
    with op.batch_alter_table("project") as batch:
        batch.drop_column("subtasks")
