"""Personal requests: the hub's requests to the human who owns an agent profile, member of
the project or not (docs/api.md §7).

`to_kind` gains `profile_owner` with `to_profile` and `to_human`; `personal` marks them
and `task_snapshot` keeps a closed one's card as it was.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)

TO_SHAPE_BEFORE = (
    "(to_kind = 'member' AND to_member IS NOT NULL AND to_role IS NULL)"
    " OR (to_kind = 'role' AND to_role IS NOT NULL AND to_member IS NULL)"
    " OR (to_kind = 'owner' AND to_member IS NULL AND to_role IS NULL)"
)
TO_SHAPE = (
    "(to_kind = 'member' AND to_member IS NOT NULL AND to_role IS NULL AND to_human IS NULL)"
    " OR (to_kind = 'role' AND to_role IS NOT NULL AND to_member IS NULL AND to_human IS NULL)"
    " OR (to_kind = 'owner' AND to_member IS NULL AND to_role IS NULL AND to_human IS NULL)"
    " OR (to_kind = 'profile_owner' AND to_profile IS NOT NULL AND to_human IS NOT NULL"
    " AND to_member IS NULL AND to_role IS NULL)"
)
PERSONAL_SHAPE = (
    "(personal AND to_kind = 'profile_owner') OR (NOT personal AND to_kind <> 'profile_owner')"
)


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("to_profile", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("to_human", sa.String(length=40), nullable=True))
        batch_op.add_column(
            sa.Column("personal", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("task_snapshot", JSON_VALUE, nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_request_to_profile_agent_profile"),
            "agent_profile",
            ["to_profile"],
            ["id"],
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_request_to_human_human"), "human", ["to_human"], ["id"]
        )
        batch_op.create_index("ix_request_to_human_status", ["to_human", "status"], unique=False)
        batch_op.drop_constraint(batch_op.f("ck_request_to_shape"), type_="check")
        batch_op.create_check_constraint(batch_op.f("ck_request_to_shape"), TO_SHAPE)
        batch_op.create_check_constraint(batch_op.f("ck_request_personal_shape"), PERSONAL_SHAPE)


def downgrade() -> None:
    op.execute("DELETE FROM request WHERE personal")  # no earlier schema can hold them
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_request_personal_shape"), type_="check")
        batch_op.drop_constraint(batch_op.f("ck_request_to_shape"), type_="check")
        batch_op.create_check_constraint(batch_op.f("ck_request_to_shape"), TO_SHAPE_BEFORE)
        # The foreign key first: MariaDB refuses to drop an index a foreign key needs.
        batch_op.drop_constraint(batch_op.f("fk_request_to_human_human"), type_="foreignkey")
        batch_op.drop_index("ix_request_to_human_status")
        batch_op.drop_constraint(
            batch_op.f("fk_request_to_profile_agent_profile"), type_="foreignkey"
        )
        batch_op.drop_column("task_snapshot")
        batch_op.drop_column("personal")
        batch_op.drop_column("to_human")
        batch_op.drop_column("to_profile")
