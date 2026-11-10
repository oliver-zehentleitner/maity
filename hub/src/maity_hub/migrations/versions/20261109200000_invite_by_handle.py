"""An invitation by handle (docs/api.md §3.4): `invitation` gains the bound account's handle at
issue (`handle`), the account itself (`invitee_id`), the personal consent request in which that
person answers (`request_id`) and the time of their `no` (`declined_at`). The index on
`invitee_id` and `created_at` serves the cap per invitee and day.

The downgrade first withdraws every open consent request an invitation by handle filed, as the
hub's own `close_request` withdraws one: `withdrawn_at`, a `withdraw_reason`, the card snapshot a
closed personal request keeps (`task_snapshot`), no actor, and the person's account record
`personal_request_withdrawn`, so their inbox shows it closed. An older hub cannot do it: nothing
there closes them, and the person's own withdrawal fails, as its registry does not know the
proposal kind `invitation`. Then it revokes every invitation by handle that is still open or was
declined, at the time it ran or of the `no`: an older hub knows neither, and would show such an
invitation as an open link that nobody holds (it was never given a `url`) or a declined one as
open. Then the columns go, each foreign key before its index: MariaDB uses that index for the
key.

Revision ID: 20261109200000_invite_by_handle
Revises: 20261108230000_expert_role
Create Date: 2026-11-09
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE

revision: str = "20261109200000_invite_by_handle"
down_revision: str | None = "20261108230000_expert_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WITHDRAWN = "the hub was downgraded to a version without invitations by handle"

_invitation = sa.table(
    "invitation",
    sa.column("id", sa.String),
    sa.column("handle", sa.String),
    sa.column("request_id", sa.String),
    sa.column("used_at", sa.DateTime),
    sa.column("revoked_at", sa.DateTime),
    sa.column("voided_at", sa.DateTime),
    sa.column("declined_at", sa.DateTime),
)
_request = sa.table(
    "request",
    sa.column("id", sa.String),
    sa.column("status", sa.String),
    sa.column("personal", sa.Boolean),
    sa.column("to_human", sa.String),
    sa.column("project_id", sa.String),
    sa.column("org_id", sa.String),
    sa.column("task_id", sa.String),
    sa.column("task_snapshot", JSON_VALUE),
    sa.column("withdrawn_at", sa.DateTime),
    sa.column("withdraw_reason", sa.Text),
    sa.column("changed_by_credential", sa.String),
    sa.column("changed_via", sa.String),
)
_card = sa.table(
    "card",
    sa.column("id", sa.String),
    sa.column("title", sa.String),
    sa.column("status", sa.String),
)
_account_record = sa.table(
    "account_record",
    sa.column("human_id", sa.String),
    sa.column("type", sa.String),
    sa.column("data", sa.JSON),
    sa.column("at", sa.DateTime),
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


def _withdraw_requests(conn: sa.Connection, now: datetime) -> None:
    """Withdraw the open consent requests of invitations by handle (the module's docstring)."""
    r = _request.c
    rows = conn.execute(
        sa.select(r.id, r.personal, r.to_human, r.project_id, r.org_id, r.task_id)
        .select_from(_request.join(_invitation, _invitation.c.request_id == r.id))
        .where(_invitation.c.handle.isnot(None), r.status == "open")
        .order_by(r.id)
    ).all()
    for row in rows:
        snapshot = None
        if row.task_id is not None:
            card = conn.execute(
                sa.select(_card.c.id, _card.c.title, _card.c.status).where(
                    _card.c.id == row.task_id
                )
            ).one()
            snapshot = {"id": card.id, "title": card.title, "status": card.status}
        values: dict[str, object] = {
            "status": "withdrawn",
            "withdrawn_at": now,
            "withdraw_reason": WITHDRAWN,
            "changed_by_credential": None,
            "changed_via": None,
        }
        if row.personal:
            values["task_snapshot"] = snapshot
        conn.execute(_request.update().where(r.id == row.id, r.status == "open").values(**values))
        if not row.personal or row.to_human is None:
            continue
        # After the person's latest record, as maity_hub.notifications.records.write keeps them.
        latest = conn.execute(
            sa.select(sa.func.max(_account_record.c.at)).where(
                _account_record.c.human_id == row.to_human
            )
        ).scalar()
        conn.execute(
            _account_record.insert().values(
                human_id=row.to_human,
                type="personal_request_withdrawn",
                data={
                    "request_id": row.id,
                    "project_id": row.project_id,
                    "org_id": row.org_id,
                    "status": "withdrawn",
                },
                at=max(now, latest) if latest is not None else now,
            )
        )


def downgrade() -> None:
    c = _invitation.c
    now = datetime.now(UTC).replace(tzinfo=None)
    conn = op.get_bind()
    _withdraw_requests(conn, now)
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
