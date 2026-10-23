"""Forwarding and claiming a decision request (docs/api.md §7).

`request.humans_only` says only a human answers it (§2.3); existing requests read as
false, as before. `holder_member` and `holder_pool` hold who has a `decision` request
after its first forward: a member, or the admins as a pool until one claims it; both
null while `to` still holds it, so no existing row needs a value. `forwarding` lists
each step `{action, from, to, by, reason, at}`, oldest first.

Revision ID: 0039
Revises: 0026
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("humans_only", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("holder_member", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("holder_pool", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("forwarding", JSON_VALUE, nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_request_holder_member_membership"), "membership", ["holder_member"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_request_holder_member_membership"), type_="foreignkey")
        batch_op.drop_column("forwarding")
        batch_op.drop_column("holder_pool")
        batch_op.drop_column("holder_member")
        batch_op.drop_column("humans_only")
