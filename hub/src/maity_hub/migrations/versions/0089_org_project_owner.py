"""A project's namespace owner may be an organisation (docs/api.md §6.25, §6.26).

`project.owner_id` and `project_alias.owner_id` stay the one id every reader uses, now a
`hum-…` or an `org-…`, and lose their foreign key to `human`. The integrity moves to two new
columns, `owner_human_id` (to `human`) and `owner_org_id` (to `org`), exactly one set, and a
check keeps the three in step. Existing rows are human-owned: `owner_human_id` is `owner_id`.

`membership.org_keep` and `org_keep_trust` mark a membership the hub keeps for an owner of the
organisation that owns the project: `created` (it ends with the ownership) or `raised` (it
returns to `org_keep_trust`). The downgrade ends the organisation-owned projects' ownership
by deleting nothing: it refuses while one exists, as the old schema cannot name its owner.

Re-chained at merge time: `down_revision` is the head of the chain this branch started
from and follows whatever head `main` has when it lands.

Revision ID: 0089
Revises: 0088
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_SHAPE = (
    "(owner_human_id IS NOT NULL AND owner_org_id IS NULL AND owner_id = owner_human_id)"
    " OR (owner_human_id IS NULL AND owner_org_id IS NOT NULL AND owner_id = owner_org_id)"
)
KEEP_SHAPE = (
    "(org_keep IS NULL AND org_keep_trust IS NULL)"
    " OR (org_keep = 'created' AND org_keep_trust IS NULL)"
    " OR (org_keep = 'raised' AND org_keep_trust IS NOT NULL)"
)


def _owner_columns(table: str, fk_owner: str) -> None:
    op.add_column(table, sa.Column("owner_human_id", sa.String(length=40), nullable=True))
    op.add_column(table, sa.Column("owner_org_id", sa.String(length=40), nullable=True))
    op.execute(f"UPDATE {table} SET owner_human_id = owner_id")
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(fk_owner), type_="foreignkey")
        batch_op.create_foreign_key(
            op.f(f"fk_{table}_owner_human_id_human"), "human", ["owner_human_id"], ["id"]
        )
        batch_op.create_foreign_key(
            op.f(f"fk_{table}_owner_org_id_org"), "org", ["owner_org_id"], ["id"]
        )
        batch_op.create_check_constraint(op.f(f"ck_{table}_owner_shape"), OWNER_SHAPE)


def upgrade() -> None:
    _owner_columns("project", "fk_project_owner_id_human")
    _owner_columns("project_alias", "fk_project_alias_owner_id_human")
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("org_keep", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("org_keep_trust", sa.String(length=16), nullable=True))
        batch_op.create_check_constraint(op.f("ck_membership_org_keep_shape"), KEEP_SHAPE)


def _drop_owner_columns(table: str, fk_owner: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(f"ck_{table}_owner_shape"), type_="check")
        batch_op.drop_constraint(op.f(f"fk_{table}_owner_org_id_org"), type_="foreignkey")
        batch_op.drop_constraint(op.f(f"fk_{table}_owner_human_id_human"), type_="foreignkey")
        batch_op.drop_column("owner_org_id")
        batch_op.drop_column("owner_human_id")
        batch_op.create_foreign_key(op.f(fk_owner), "human", ["owner_id"], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    owned = bind.execute(sa.text("SELECT COUNT(*) FROM project WHERE owner_org_id IS NOT NULL"))
    if owned.scalar_one():
        raise RuntimeError(
            "organisations own projects: transfer them to humans before downgrading below 0089"
        )
    op.execute("DELETE FROM project_alias WHERE owner_org_id IS NOT NULL")
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_membership_org_keep_shape"), type_="check")
        batch_op.drop_column("org_keep_trust")
        batch_op.drop_column("org_keep")
    _drop_owner_columns("project_alias", "fk_project_alias_owner_id_human")
    _drop_owner_columns("project", "fk_project_owner_id_human")
