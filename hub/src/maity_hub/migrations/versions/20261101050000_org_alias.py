"""An organisation's handle aliases (docs/api.md §6.24, §6.26): a rename files the handle given
up in `handle_alias`, under a column of its own beside the human's and the profile's.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261101050000_org_alias
Revises: 20261101010000_event_watcher
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101050000_org_alias"
down_revision: str | None = "20261101010000_event_watcher"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ONE_OF_THREE = (
    "(human_id IS NOT NULL AND agent_id IS NULL AND org_id IS NULL)"
    " OR (human_id IS NULL AND agent_id IS NOT NULL AND org_id IS NULL)"
    " OR (human_id IS NULL AND agent_id IS NULL AND org_id IS NOT NULL)"
)
ONE_OF_TWO = "(human_id IS NULL) <> (agent_id IS NULL)"


def upgrade() -> None:
    with op.batch_alter_table("handle_alias") as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.String(length=40), nullable=True))
        batch_op.create_foreign_key(op.f("fk_handle_alias_org_id_org"), "org", ["org_id"], ["id"])
        batch_op.drop_constraint(op.f("ck_handle_alias_one_id"), type_="check")
        batch_op.create_check_constraint(op.f("ck_handle_alias_one_id"), ONE_OF_THREE)


def downgrade() -> None:
    alias = sa.table("handle_alias", sa.column("org_id"))
    op.execute(alias.delete().where(alias.c.org_id.is_not(None)))
    with op.batch_alter_table("handle_alias") as batch_op:
        batch_op.drop_constraint(op.f("ck_handle_alias_one_id"), type_="check")
        batch_op.create_check_constraint(op.f("ck_handle_alias_one_id"), ONE_OF_TWO)
        batch_op.drop_constraint(op.f("fk_handle_alias_org_id_org"), type_="foreignkey")
        batch_op.drop_column("org_id")
