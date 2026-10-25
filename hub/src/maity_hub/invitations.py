"""Invitations for humans (docs/api.md §3.4): what an invitation is, when it admits, and
who hears of it.

An invitation is for one person, one project and one role; it is used once and it
expires. Whether it still admits — open, its project not closed, its issuer still
holding the authority it needs — is one predicate, used by the page, by accepting and by
registration (§2.7.1), so the three never disagree.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.events import Actor, emit
from maity_hub.policy import CLOSED_STATES
from maity_hub.ratelimit import Limiter
from maity_hub.scopes import has_scope

TTL_DEFAULT, TTL_MIN, TTL_MAX = 86_400, 60, 604_800
NOTE_MAX = 1024  # bytes of UTF-8
LISTED_FOR = timedelta(days=30)  # a used, revoked, voided or expired one stays listed
PER_PROJECT = Limiter(20, 3600)  # issued per project per hour (§3.4)
KINDS = ("invitation_created", "invitation_revoked", "invitation_voided", "invitation_used")
# Only the owner invites to these: the roles that themselves invite (§3.4).
OWNER_ROLES = ("owner", "admin")


def state(row: Any, now: datetime | None = None) -> str:
    """`used`, `revoked`, `voided`, `expired` or `open`."""
    if row.used_at is not None:
        return "used"
    if row.revoked_at is not None:
        return "revoked"
    if row.voided_at is not None:
        return "voided"
    if row.expires_at <= (now or clock.now()):
        return "expired"
    return "open"


def view(row: Any, project_slug: str, url: str | None = None) -> dict[str, Any]:
    """The invitation as its issuers see it; `url`, with the token, only when issued."""
    found = {
        "id": row.id,
        "project": project_slug,
        "role": row.role,
        "address": row.address,
        "note": row.note,
        "created_by": row.created_by,
        "created_at": clock.rfc3339(row.created_at),
        "expires_at": clock.rfc3339(row.expires_at),
        "used_at": _ts(row.used_at),
        "used_by": row.used_by,
        "revoked_at": _ts(row.revoked_at),
        "voided_at": _ts(row.voided_at),
    }
    if url is not None:
        found["url"] = url
    return found


def _ts(value: datetime | None) -> str | None:
    return clock.rfc3339(value) if value is not None else None


def may_issue(role: str, issuer_role: str) -> bool:
    """`owner` and `admin` need the issuer to hold `owner`; the others `members:admin`."""
    if role in OWNER_ROLES:
        return issuer_role == "owner"
    return has_scope(issuer_role, "human", "members:admin")


def issuer_holds(conn: Connection, row: Any) -> bool:
    """Whether the issuer is still an active human member with the authority it needs."""
    role = conn.execute(
        select(t.membership.c.role).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.human_id == row.created_by,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    return role is not None and may_issue(row.role, role)


def admits(conn: Connection, row: Any, project: Any, now: datetime | None = None) -> bool:
    """§3.4's predicate: open, its project not closed, its issuer with authority."""
    return (
        state(row, now) == "open" and project.state not in CLOSED_STATES and issuer_holds(conn, row)
    )


def admits_address(conn: Connection, normalized: str, *, lock: bool = False) -> bool:
    """Whether an open, address-bound invitation admits this address to register under
    `closed` or `allowlist` (§2.7.1, §3.4). An invitation without an address admits
    nobody to register. With `lock`, the invitations are read `FOR UPDATE`: completion
    decides on them as they stay until it commits, so a revocation racing it waits or
    wins, never slips between the check and the account."""
    now = clock.now()
    query = select(t.invitation).where(
        t.invitation.c.address_normalized == normalized,
        t.invitation.c.used_at.is_(None),
        t.invitation.c.revoked_at.is_(None),
        t.invitation.c.voided_at.is_(None),
        t.invitation.c.expires_at > now,
    )
    rows = conn.execute(query.with_for_update() if lock else query).all()
    for row in rows:
        state = conn.execute(
            select(t.project.c.state).where(t.project.c.id == row.project_id)
        ).scalar()
        if state not in CLOSED_STATES and issuer_holds(conn, row):
            return True
    return False


def account_address(conn: Connection, human_id: str) -> str | None:
    """The account's verified address (§18.4), normalized, or None. Fails closed: with
    None an address-bound invitation is `invitation_address_mismatch` for everyone."""
    # TODO(#280): read the verified address the notification settings store.
    del conn, human_id
    return None


def audience(conn: Connection, project_id: str, *also: str) -> list[str]:
    """`member:<id>` of every human `members:admin` holder (§3.4), and `also`."""
    humans = conn.execute(
        select(t.membership.c.human_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id.is_not(None),
            t.membership.c.role.in_(("owner", "admin")),
            t.membership.c.active.is_(True),
        )
        .order_by(t.membership.c.joined_at)
    ).scalars()
    found = [f"member:{human_id}" for human_id in humans]
    return found + [token for token in also if token not in found]


def announce(conn: Connection, kind: str, row: Any, actor: Actor, *also: str) -> None:
    """An invitation event: its id, role and whether it is address-bound, never the
    address and never the token (§3.4)."""
    emit(
        conn,
        row.project_id,
        kind,
        audience(conn, row.project_id, *also),
        {"id": row.id, "role": row.role, "address_bound": row.address is not None},
        actor=actor,
        subject=("invitation", row.id),
    )


def void(conn: Connection, row: Any, actor: Actor) -> None:
    """The issuer lost the authority the invitation needs: void it, and tell them."""
    conn.execute(
        update(t.invitation)
        .where(t.invitation.c.id == row.id)
        .values(voided_at=clock.now(), void_reason="issuer")
    )
    after = conn.execute(select(t.invitation).where(t.invitation.c.id == row.id)).one()
    announce(conn, "invitation_voided", after, actor, f"member:{row.created_by}")
