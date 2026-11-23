"""A placement may name a profile that is not a member yet (docs/api.md §15.6).

`placement.agent_id` names a profile of the creator's own that had no active membership in
the project when it was placed; the join fields stay in `new_profile`, as for a new profile,
until the first pickup's exchange makes the membership (§15.9). Null for every existing row.
`ix_placement_agent_id` serves the foreign key and the cascades that close such placements:
a membership's removal and a profile's deletion (§6.2, §6.3). `ck_placement_names_an_agent`
takes the new column as a third way to name the agent. The slug is `plc_agent_id`, as
`alembic_version` holds 32 characters.

A downgrade restores the old check and therefore refuses while a placement names its agent by
`agent_id` alone, closed ones included, which only a database restore removes.

Revision ID: 20261120205253_plc_agent_id
Revises: 20261118090000_starred
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261120205253_plc_agent_id"
down_revision: str | None = "20261118090000_starred"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WITH_AGENT_ID = "membership_id IS NOT NULL OR new_handle IS NOT NULL OR agent_id IS NOT NULL"
WITHOUT_AGENT_ID = "membership_id IS NOT NULL OR new_handle IS NOT NULL"


def upgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_id", sa.String(length=40), nullable=True))
        batch_op.create_index(batch_op.f("ix_placement_agent_id"), ["agent_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_placement_agent_id_agent_profile"), "agent_profile", ["agent_id"], ["id"]
        )
        batch_op.drop_constraint(batch_op.f("ck_placement_names_an_agent"), type_="check")
        batch_op.create_check_constraint(batch_op.f("ck_placement_names_an_agent"), WITH_AGENT_ID)


def downgrade() -> None:
    placement = sa.table(
        "placement",
        sa.column("membership_id", sa.Integer),
        sa.column("new_handle", sa.String),
        sa.column("agent_id", sa.String),
    )
    alone = (
        op.get_bind()
        .execute(
            sa.select(placement.c.agent_id).where(
                placement.c.agent_id.is_not(None),
                placement.c.membership_id.is_(None),
                placement.c.new_handle.is_(None),
            )
        )
        .first()
    )
    if alone is not None:
        raise RuntimeError(
            "a placement names its agent by agent_id alone (a profile placed while not a "
            "member, never picked up); the old check cannot hold it (docs/api.md §15.6)"
        )
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_placement_names_an_agent"), type_="check")
        batch_op.create_check_constraint(
            batch_op.f("ck_placement_names_an_agent"), WITHOUT_AGENT_ID
        )
        batch_op.drop_constraint(
            batch_op.f("fk_placement_agent_id_agent_profile"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_placement_agent_id"))
        batch_op.drop_column("agent_id")
