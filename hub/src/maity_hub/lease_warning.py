"""Before a lease runs out (docs/api.md §6.5): `claim_lease_expiring` and the renewal.

A holder that only listens renews nothing (§2.4), so its leases run out while it is still at
work. The minute worker warns it: one event per holder and pass for the claims whose
`lease_until` is still ahead but at most `warn_seconds` away, each claim once per lease period
(`card.lease_warning_reported` holds the `lease_until` it named). Every write of a new
`lease_until` (a call's renewal, a limit's hold, a claim, a cover, a takeover) differs from the
value named, so it arms the warning again without being told.

The event goes to the holder alone: the holding instance by its `instance:` token, or for the
claims a bridge holds the served agent by `member:`. It wakes the holder and never waits for it
(`not_listening.waits_for`): a holder that does not answer is reported when the lease runs out.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.cards import open_claims
from maity_hub.events import emit, lock_project, transaction
from maity_hub.holder_stalled import _latest_session

KIND = "claim_lease_expiring"
FLOOR = 120  # seconds: the shortest lead a warning gets
CAP = 300  # seconds: the longest, also how far ahead the pass looks at all


def warn_seconds(lease_seconds: int) -> int:
    """`min(300, max(120, lease_seconds / 10))`, the tenth rounded down to whole seconds: the
    threshold and the payload's `warn_seconds` alike (§6.5)."""
    return min(CAP, max(FLOOR, lease_seconds // 10))


def _unwarned() -> Any:
    c = t.card.c
    return (c.lease_warning_reported.is_(None)) | (c.lease_warning_reported != c.lease_until)


def _due(cards: list[Any], now: datetime, lease_seconds: int) -> list[Any]:
    """The claims within the project's warning time and not yet past (§6.5): a lease that ran
    out is `claim_expired`'s."""
    horizon = now + timedelta(seconds=warn_seconds(lease_seconds))
    return [card for card in cards if now < card.lease_until <= horizon]


def warn(engine: Engine, now: datetime | None = None) -> None:
    """The minute's pass: `claim_lease_expiring` once per holder for its claims within the
    warning time, each claim once per lease period (§6.5)."""
    now = now or clock.now()
    c = t.card.c
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                c.claim_holder,
                c.claim_instance,
                c.lease_until,
                t.membership.c.project_id,
                t.project.c.lease_seconds,
            )
            .join(t.membership, t.membership.c.id == c.claim_holder)
            .join(t.project, t.project.c.id == t.membership.c.project_id)
            .where(
                open_claims(None),
                c.lease_until.is_not(None),
                c.lease_until > now,
                c.lease_until <= now + timedelta(seconds=CAP),
                _unwarned(),
            )
        ).all()
    due = {
        (row.project_id, int(row.claim_holder), row.claim_instance)
        for row in rows
        if _due([row], now, row.lease_seconds)
    }
    for project_id, holder, instance in sorted(due, key=lambda r: (r[0], r[1], r[2] or "")):
        with transaction(engine) as conn:
            lock_project(conn, project_id)
            _warn_one(conn, holder, instance, now)


def _warn_one(conn: Connection, membership_id: int, instance: str | None, now: datetime) -> None:
    c = t.card.c
    lease_seconds = conn.execute(
        select(t.project.c.lease_seconds)
        .join(t.membership, t.membership.c.project_id == t.project.c.id)
        .where(t.membership.c.id == membership_id)
    ).scalar_one()
    held = conn.execute(
        select(c.id, c.title, c.lease_until)
        .where(
            open_claims(membership_id, instance=instance), c.lease_until.is_not(None), _unwarned()
        )
        .order_by(c.id)
    ).all()
    cards = _due(list(held), now, lease_seconds)
    if not cards:
        return  # renewed, released or warned since the look outside the lock
    for card in cards:
        conn.execute(
            update(t.card).where(c.id == card.id).values(lease_warning_reported=card.lease_until)
        )
    member = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    if member.agent_id is None:
        return  # a human's lease: §6.5 warns agents, as `claim_expired` reports them
    session = _latest_session(conn, member.id, instance) if instance is not None else None
    audience = (
        [f"instance:{member.agent_id}#{instance}"]
        if instance is not None
        else [f"member:{member.agent_id}"]  # a bridge's claims: the served agent (§2.3)
    )
    emit(
        conn,
        member.project_id,
        KIND,
        audience,
        {
            "member_id": member.agent_id,
            "instance": instance,
            "session_id": session.id if session is not None else None,
            "tasks": [
                {"id": card.id, "title": card.title, "lease_until": clock.rfc3339(card.lease_until)}
                for card in cards
            ],
            "warn_seconds": warn_seconds(lease_seconds),
        },
        subject=("member", member.agent_id),
    )


def held(conn: Connection, membership_id: int, instance: str | None) -> list[dict[str, Any]]:
    """The claims `POST …/claims/renew` answers with: the caller's, oldest id first, with the
    lease its call has just renewed (§6.5)."""
    c = t.card.c
    return [
        {
            "task_id": row.id,
            "title": row.title,
            "lease_until": clock.rfc3339(row.lease_until) if row.lease_until else None,
        }
        for row in conn.execute(
            select(c.id, c.title, c.lease_until)
            .where(open_claims(membership_id, instance=instance))
            .order_by(c.id)
        )
    ]
