"""An invitation by handle (docs/api.md §3.4): `invitation` gains the handle as typed at issue,
the account it is bound to (`invitee_id`), the personal consent request in which that person
answers (`request_id`) and the time of their `no` (`declined_at`). The index on `invitee_id` and
`created_at` serves the cap per invitee and day.

The downgrade revokes every invitation by handle that is still open or was declined, at the time
it ran or of the `no`: an older hub knows neither, and would show such an invitation as an open
link that nobody holds (it was never given a `url`) or a declined one as open. The open personal
requests they filed are withdrawn by the older hub itself, whose `close_request` withdraws a
request whose proposal kind it does not know. Then the columns go, each foreign key before its
index: MariaDB uses that index for the key.

Revision ID: 20261109200000_invite_by_handle
Revises: 20261108230000_expert_role
Create Date: 2026-11-09
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20261109200000_invite_by_handle"
down_revision: str | None = "20261108230000_expert_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_invitation = sa.table(
    "invitation",
    sa.column("id", sa.String),
    sa.column("handle", sa.String),
    sa.column("used_at", sa.DateTime),
    sa.column("revoked_at", sa.DateTime),
    sa.column("voided_at", sa.DateTime),
    sa.column("declined_at", sa.DateTime),
)


def upgrade() -> None:
    with op.batch_alter_table("invitation") as batch:
        batch.add_column(sa.Column("handle", sa.String(64), nullable=True))
        batch.add_column(sa.Column("invitee_id", sa.String(40), nullable=True))
        batch.add_column(sa.Column("request_id", sa.String(40), nullable=True))
        batch.add_column(sa.Column("declined_at", sa.DateTime(), nullable=True))
        # The index first, so MariaDB serves the key on `invitee_id` with it.
        batch.create_index(
            "ix_invitation_invitee_id_created_at", ["invitee_id", "created_at"], unique=False
        )
        batch.create_foreign_key(
            op.f("fk_invitation_invitee_id_human"), "human", ["invitee_id"], ["id"]
        )
        batch.create_foreign_key(
            op.f("fk_invitation_request_id_request"), "request", ["request_id"], ["id"]
        )


def downgrade() -> None:
    c = _invitation.c
    now = datetime.now(UTC).replace(tzinfo=None)
    conn = op.get_bind()
    conn.execute(
        _invitation.update()
        .where(c.handle.isnot(None), c.declined_at.isnot(None), c.revoked_at.is_(None))
        .values(revoked_at=c.declined_at)
    )
    conn.execute(
        _invitation.update()
        .where(
            c.handle.isnot(None),
            c.used_at.is_(None),
            c.revoked_at.is_(None),
            c.voided_at.is_(None),
        )
        .values(revoked_at=now)
    )
    with op.batch_alter_table("invitation") as batch:
        batch.drop_constraint(op.f("fk_invitation_request_id_request"), type_="foreignkey")
        batch.drop_constraint(op.f("fk_invitation_invitee_id_human"), type_="foreignkey")
        batch.drop_index("ix_invitation_invitee_id_created_at")
        batch.drop_column("declined_at")
        batch.drop_column("request_id")
        batch.drop_column("invitee_id")
        batch.drop_column("handle")
