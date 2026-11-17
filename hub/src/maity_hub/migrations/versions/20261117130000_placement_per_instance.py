"""Several active placements per membership, one per instance (docs/api.md §15.5).

`uq_placement_membership_id_active` goes: a membership may hold as many active placements as
its `max_instances` lets it, which the hub counts at creation. In its place
`uq_placement_credential_id_active` keeps one active placement per agent credential, with the
same True-or-NULL marker (a placement before its first pickup has no credential, and NULL never
collides). `ix_placement_membership_id` is created first: on MariaDB the membership's foreign
key needs an index that starts with `membership_id` at every moment.

A downgrade restores the old key and therefore refuses while a membership holds two active
placements: close one of them first.

Revision ID: 20261117130000_placement_per_instance
Revises: 20261115000000_address_where
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261117130000_placement_per_instance"
down_revision: str | None = "20261115000000_address_where"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_placement_membership_id"), ["membership_id"])
        batch_op.create_unique_constraint(
            batch_op.f("uq_placement_credential_id_active"), ["credential_id", "active"]
        )
        batch_op.drop_constraint(batch_op.f("uq_placement_membership_id_active"), type_="unique")


def downgrade() -> None:
    placement = sa.table(
        "placement", sa.column("membership_id", sa.Integer), sa.column("active", sa.Boolean)
    )
    doubled = (
        op.get_bind()
        .execute(
            sa.select(placement.c.membership_id)
            .where(placement.c.active.is_(True), placement.c.membership_id.is_not(None))
            .group_by(placement.c.membership_id)
            .having(sa.func.count() > 1)
        )
        .first()
    )
    if doubled is not None:
        raise RuntimeError(
            "a membership holds more than one active placement; close all but one of them "
            "before this downgrade (docs/api.md §15.5)"
        )
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            batch_op.f("uq_placement_membership_id_active"), ["membership_id", "active"]
        )
        batch_op.drop_constraint(batch_op.f("uq_placement_credential_id_active"), type_="unique")
        batch_op.drop_index(batch_op.f("ix_placement_membership_id"))
