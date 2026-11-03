"""A holder that stops (docs/api.md §6.5): `holder_stalled` and `claim_expired`.

The hub says so and changes nothing: no claim is released and no lease moves. Both go to the
member the agent reports to, the admins and the profile's owner when a member (as
`member_not_listening`, `not_listening.audience_of`), and to the holding instance through its
`instance:` token, which these two kinds never wake (`events.wakes`).

`holder_stalled` comes from three places: a limit that starts (`availability.set_agent_limit`),
a revocation that is not a replacement (`auth.leaks.revoke`), and the start of a not-listening
episode (`not_listening.check`). `claim_expired` comes from the minute worker: one event per
holder and pass for the claims whose `lease_until` passed since it last looked
(`card.lease_expiry_reported` holds the `lease_until` it named).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.events import emit, lock_project, transaction

log = logging.getLogger(__name__)

HOLDER_STALLED = "holder_stalled"
CLAIM_EXPIRED = "claim_expired"
KINDS = frozenset({HOLDER_STALLED, CLAIM_EXPIRED})


def _held(conn: Connection, membership_id: int, instance: str | None) -> list[Any]:
    """The cards the holder holds in its project, oldest id first: an instance's, or with
    `instance` None the claims a bridge holds for the agent."""
    c = t.card.c
    where = c.claim_instance == instance if instance is not None else c.claim_instance.is_(None)
    return list(
        conn.execute(
            select(c.id, c.title, c.lease_until)
            .where(c.claim_holder == membership_id, where)
            .order_by(c.id)
        )
    )


def _latest_session(conn: Connection, membership_id: int, instance: str) -> Any | None:
    """The instance's credential and its latest session, or None without either."""
    row = conn.execute(
        select(
            t.credential.c.revoked_at,
            t.agent_session.c.id,
            t.agent_session.c.last_seen_at,
            t.agent_session.c.ended_at,
        )
        .join(t.agent_session, t.agent_session.c.credential_id == t.credential.c.id)
        .where(t.credential.c.membership_id == membership_id, t.credential.c.instance == instance)
        .order_by(t.agent_session.c.started_at.desc())
        .limit(1)
    ).first()
    return row


def _limit(member: Any, now: datetime) -> dict[str, Any] | None:
    if member.limit_until is None or member.limit_until <= now:
        return None
    return {"reason": member.limit_reason, "until": clock.rfc3339(member.limit_until)}


def _payload(
    conn: Connection, member: Any, instance: str | None, cards: list[Any], cause: str
) -> dict[str, Any]:
    """`{member_id, instance, session_id, tasks, reason, limit?, last_seen_at}` (§6.5).
    `reason`: `session_ended` when the session was revoked, else `limit` while one runs, else
    the cause."""
    now = clock.now()
    session = _latest_session(conn, member.id, instance) if instance is not None else None
    limit = _limit(member, now)
    revoked = session is not None and session.revoked_at is not None
    payload: dict[str, Any] = {
        "member_id": member.agent_id,
        "instance": instance,
        "session_id": session.id if session is not None else None,
        "tasks": [
            {
                "id": c.id,
                "title": c.title,
                "lease_until": clock.rfc3339(c.lease_until) if c.lease_until else None,
            }
            for c in cards
        ],
        "reason": "session_ended" if revoked else ("limit" if limit is not None else cause),
        "last_seen_at": (clock.rfc3339(session.last_seen_at) if session is not None else None),
    }
    if limit is not None:
        payload["limit"] = limit
    return payload


def _emit(
    conn: Connection, member: Any, instance: str | None, kind: str, cards: list[Any], cause: str
) -> None:
    from maity_hub.not_listening import audience_of

    audience = audience_of(conn, member)
    if instance is not None:
        audience.append(f"instance:{member.agent_id}#{instance}")
    emit(
        conn,
        member.project_id,
        kind,
        audience,
        _payload(conn, member, instance, cards, cause),
        subject=("member", member.agent_id),
    )


def _member(conn: Connection, membership_id: int) -> Any:
    return conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()


def stalled(conn: Connection, membership_id: int, instance: str, cause: str) -> None:
    """`holder_stalled` for one instance, when it holds a claim in its project."""
    cards = _held(conn, membership_id, instance)
    if cards:
        member = _member(conn, membership_id)
        if member.agent_id is not None:
            _emit(conn, member, instance, HOLDER_STALLED, cards, cause)


def limit_started(conn: Connection, membership_id: int) -> None:
    """A limit started for the agent: one event per instance that holds a claim (§6.5)."""
    instances = conn.execute(
        select(t.card.c.claim_instance)
        .where(t.card.c.claim_holder == membership_id, t.card.c.claim_instance.is_not(None))
        .distinct()
        .order_by(t.card.c.claim_instance)
    ).scalars()
    for instance in list(instances):
        stalled(conn, membership_id, instance, "limit")


def revoked(conn: Connection, credential_id: str, reason: str) -> None:
    """The instance's session ended by a revocation (§6.5). A replacement (`replaced`) moves
    the claims to the new instance and says nothing."""
    if reason == "replaced":
        return
    row = conn.execute(
        select(t.credential.c.membership_id, t.credential.c.instance).where(
            t.credential.c.id == credential_id
        )
    ).first()
    if row is not None:
        stalled(conn, row.membership_id, row.instance, "session_ended")


def expire(engine: Engine, now: datetime | None = None) -> None:
    """The minute's pass: `claim_expired` once per holder for the claims whose lease passed
    since the last pass named them, each claim once per expiry (§6.5)."""
    now = now or clock.now()
    c = t.card.c
    with engine.connect() as conn:
        due = conn.execute(
            select(c.claim_holder, c.claim_instance, t.membership.c.project_id)
            .join(t.membership, t.membership.c.id == c.claim_holder)
            .where(
                c.claim_holder.is_not(None),
                c.lease_until.is_not(None),
                c.lease_until < now,
                (c.lease_expiry_reported.is_(None)) | (c.lease_expiry_reported != c.lease_until),
            )
            .distinct()
        ).all()
    for holder, instance, project_id in sorted(due, key=lambda r: (r[2], r[0], r[1] or "")):
        with transaction(engine) as conn:
            lock_project(conn, project_id)
            _expire_one(conn, int(holder), instance, now)


def _expire_one(conn: Connection, membership_id: int, instance: str | None, now: datetime) -> None:
    c = t.card.c
    where = c.claim_instance == instance if instance is not None else c.claim_instance.is_(None)
    cards = list(
        conn.execute(
            select(c.id, c.title, c.lease_until)
            .where(
                c.claim_holder == membership_id,
                where,
                c.lease_until.is_not(None),
                c.lease_until < now,
                (c.lease_expiry_reported.is_(None)) | (c.lease_expiry_reported != c.lease_until),
            )
            .order_by(c.id)
        )
    )
    if not cards:
        return  # renewed or released since the look outside the lock
    for card in cards:
        conn.execute(
            update(t.card).where(c.id == card.id).values(lease_expiry_reported=card.lease_until)
        )
    member = _member(conn, membership_id)
    if member.agent_id is None:
        return  # a human's lease: nobody to tell about an agent (§6.5 names agents)
    _emit(conn, member, instance, CLAIM_EXPIRED, cards, "lease_expired")
