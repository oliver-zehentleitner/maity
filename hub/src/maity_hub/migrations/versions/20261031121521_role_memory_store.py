"""Role memory has its own project-local name and quota (docs/api.md §19.2).

Revision ID: 20261031121521_role_memory_store
Revises: 20261031112210_agent_owners
Create Date: 2026-10-31 13:15:23.237985
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261031121521_role_memory_store"
down_revision: str | None = "20261031112210_agent_owners"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memory_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(length=24), nullable=True))
        batch_op.drop_constraint(op.f("ck_memory_entry_store_shape"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_memory_entry_store_shape"),
            "(store = 'team' AND team_membership IS NOT NULL AND role IS NULL)"
            " OR (store = 'role' AND team_membership IS NULL AND role IS NOT NULL)"
            " OR (store = 'community' AND team_membership IS NULL AND role IS NULL)",
        )
        batch_op.create_index("ix_memory_entry_role", ["project_id", "role", "created_at"])


def downgrade() -> None:
    entries = sa.table("memory_entry", sa.column("store"))
    if (
        op.get_bind()
        .execute(sa.select(entries.c.store).where(entries.c.store == "role").limit(1))
        .first()
    ):
        raise RuntimeError("cannot downgrade while role memory history exists")
    with op.batch_alter_table("memory_entry", schema=None) as batch_op:
        batch_op.drop_index("ix_memory_entry_role")
        batch_op.drop_constraint(op.f("ck_memory_entry_store_shape"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_memory_entry_store_shape"),
            "(store = 'team' AND team_membership IS NOT NULL)"
            " OR (store = 'community' AND team_membership IS NULL)",
        )
        batch_op.drop_column("role")
