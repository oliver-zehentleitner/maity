"""The owner's digest request has neither project nor organisation (docs/api.md §5.3, §7).

`ck_request_scope_known` allowed a request without a project only when it concerns an
organisation. The digest of agent instances that are not listening concerns every project
of the human's agents at once: personal, filed by the hub, with no asker at all. No row
changes; a downgrade deletes the digest requests, which the old constraint refuses.

Revision ID: 0108
Revises: 0107
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "project_id IS NOT NULL OR (org_id IS NOT NULL AND personal AND asked_by IS NULL)"
NEW = (
    "project_id IS NOT NULL"
    " OR (org_id IS NOT NULL AND personal AND asked_by IS NULL)"
    " OR (org_id IS NULL AND personal AND filed_by = 'hub' AND asked_by IS NULL"
    " AND asked_by_human IS NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_request_scope_known"), type_="check")
        batch_op.create_check_constraint(op.f("ck_request_scope_known"), NEW)


def downgrade() -> None:
    request = sa.table(
        "request",
        sa.column("project_id", sa.String),
        sa.column("org_id", sa.String),
    )
    op.execute(request.delete().where(request.c.project_id.is_(None), request.c.org_id.is_(None)))
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_request_scope_known"), type_="check")
        batch_op.create_check_constraint(op.f("ck_request_scope_known"), OLD)
