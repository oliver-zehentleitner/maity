"""A request that concerns an organisation and no project (docs/api.md §7, §6.26).

An organisation's invitation is a personal `consent` request to the invited human with
`project: null` and `org: {id, handle}`. So `request.project_id` and `request.asked_by` (a
membership) become nullable, `request.org_id` names the organisation and
`request.asked_by_human` the human who invites, whom the invited human must see. A check
keeps it to that case: no project means an organisation, a personal request and no asking
membership. The downgrade removes the requests that have no project (and what refers to
them), as they cannot exist before this revision.

Re-chained at merge time: `down_revision` is the head of the chain this branch started
from and follows whatever head `main` has when it lands.

Revision ID: 0088
Revises: 0087
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPE = "project_id IS NOT NULL OR (org_id IS NOT NULL AND personal AND asked_by IS NULL)"


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("asked_by_human", sa.String(length=40), nullable=True))
        batch_op.alter_column("project_id", existing_type=sa.String(length=40), nullable=True)
        batch_op.alter_column("asked_by", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(op.f("fk_request_org_id_org"), "org", ["org_id"], ["id"])
        batch_op.create_foreign_key(
            op.f("fk_request_asked_by_human_human"), "human", ["asked_by_human"], ["id"]
        )
        batch_op.create_check_constraint(op.f("ck_request_scope_known"), SCOPE)


def downgrade() -> None:
    request = sa.table("request", sa.column("id", sa.String), sa.column("project_id", sa.String))
    invitation = sa.table(
        "org_invitation", sa.column("request_id", sa.String), sa.column("id", sa.String)
    )
    projectless = sa.select(request.c.id).where(request.c.project_id.is_(None))
    op.execute(
        invitation.update().where(invitation.c.request_id.in_(projectless)).values(request_id=None)
    )
    op.execute(request.delete().where(request.c.project_id.is_(None)))
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_request_scope_known"), type_="check")
        batch_op.drop_constraint(op.f("fk_request_asked_by_human_human"), type_="foreignkey")
        batch_op.drop_constraint(op.f("fk_request_org_id_org"), type_="foreignkey")
        batch_op.alter_column("asked_by", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("project_id", existing_type=sa.String(length=40), nullable=False)
        batch_op.drop_column("asked_by_human")
        batch_op.drop_column("org_id")
