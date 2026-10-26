"""Device codes: signing in a new device from one that is signed in (docs/api.md §2.6.2).

A code is made by one session of a human (A), redeemed by one new browser (B), which the
pending cookie binds to it, approved on A by picking the number B shows, and completed
into one new session of that human on B. The code alone grants nothing, and B learns
the account only after the approval. The code and the pending cookie are stored as
`sha256` only.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import avatars, clock, ids
from maity_hub import tables as t
from maity_hub.auth import sessions
from maity_hub.errors import ApiError
from maity_hub.views import ts

LIFETIME = timedelta(minutes=5)
COMPLETE_WITHIN = timedelta(seconds=60)  # after the approval
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford's base32
LENGTH = 8
USER_AGENT_MAX = 300
OPEN = ("waiting", "redeemed", "approved")


def code_invalid() -> ApiError:
    """Wrong, unknown, expired, used or denied: never which (§2.6)."""
    return ApiError(403, "code_invalid", "the code is not valid")


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def normalise(text: str) -> str | None:
    """Case-insensitive, hyphens and spaces dropped, I and L read as 1, O as 0."""
    code = text.upper().replace("-", "").replace(" ", "")
    code = code.replace("I", "1").replace("L", "1").replace("O", "0")
    if len(code) != LENGTH or any(c not in ALPHABET for c in code):
        return None
    return code


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def status(row: Any, now: datetime) -> str:
    """The state as it is now: an open code past its time is `expired`."""
    if row.status in OPEN and now >= row.expires_at:
        return "expired"
    return str(row.status)


def create(conn: Connection, human_id: str, session_hash: str) -> tuple[Any, str]:
    """A new code of this session, voiding an earlier open one: (row, code)."""
    now = clock.now()
    conn.execute(
        update(t.device_code)
        .where(t.device_code.c.session_hash == session_hash, t.device_code.c.status.in_(OPEN))
        .values(status="denied")
    )
    code = new_code()
    code_id = ids.new_id("device_code")
    conn.execute(
        insert(t.device_code).values(
            id=code_id,
            human_id=human_id,
            session_hash=session_hash,
            code_hash=digest(code),
            status="waiting",
            created_at=now,
            expires_at=now + LIFETIME,
        )
    )
    return conn.execute(select(t.device_code).where(t.device_code.c.id == code_id)).one(), code


def creator_view(row: Any, now: datetime) -> dict[str, Any]:
    """What the session that made the code sees: the device once it was redeemed, and
    the three numbers while it waits for the pick."""
    state = status(row, now)
    view: dict[str, Any] = {"id": row.id, "status": state, "expires_at": ts(row.expires_at)}
    if row.redeemed_at is not None:
        view["device"] = {
            "ip": row.ip,
            "redeemed_at": ts(row.redeemed_at),
            "user_agent": row.user_agent,
            "browser": row.browser,
            "os": row.os,
            "new_device": bool(row.new_device),
        }
    if state == "redeemed":
        view["choices"] = row.choices
    return view


def redeem(
    conn: Connection,
    text: str,
    *,
    address: str,
    user_agent: str | None,
    device_cookie: str | None,
    next_route: str,
) -> tuple[Any, str] | None:
    """Bind a waiting code to this browser: (row, pending cookie value), or None for a
    code that is not valid now. The first redemption wins; every later one fails."""
    code = normalise(text)
    if code is None:
        return None
    row = conn.execute(
        select(t.device_code).where(t.device_code.c.code_hash == digest(code)).with_for_update()
    ).first()
    now = clock.now()
    if row is None or status(row, now) != "waiting":
        return None
    match = 10 + secrets.randbelow(90)
    others: set[int] = set()
    while len(others) < 2:
        drawn = 10 + secrets.randbelow(90)
        if drawn != match:
            others.add(drawn)
    browser, system = sessions.describe(user_agent)
    pending = secrets.token_urlsafe(32)
    conn.execute(
        update(t.device_code)
        .where(t.device_code.c.id == row.id)
        .values(
            status="redeemed",
            pending_hash=digest(pending),
            redeemed_at=now,
            ip=address[:64],
            user_agent=(user_agent or "")[:USER_AGENT_MAX] or None,
            browser=browser,
            os=system,
            new_device=not sessions.knows_device(conn, row.human_id, device_cookie),
            match_number=match,
            choices=sorted({match, *others}),
            next=next_route,
        )
    )
    return conn.execute(select(t.device_code).where(t.device_code.c.id == row.id)).one(), pending


def of_creator(conn: Connection, code_id: str, session_hash: str, *, lock: bool = False) -> Any:
    """The code, for the session that made it only; None for every other caller."""
    query = select(t.device_code).where(
        t.device_code.c.id == code_id, t.device_code.c.session_hash == session_hash
    )
    return conn.execute(query.with_for_update() if lock else query).first()


def of_pending(conn: Connection, pending: str | None, *, lock: bool = False) -> Any:
    """The code the pending cookie is bound to, or None."""
    if not pending:
        return None
    query = select(t.device_code).where(t.device_code.c.pending_hash == digest(pending))
    return conn.execute(query.with_for_update() if lock else query).first()


def approve(conn: Connection, row: Any, number: int) -> bool:
    """The human's pick: the right number approves, a wrong one denies the code."""
    right = bool(number == row.match_number)
    now = clock.now()
    conn.execute(
        update(t.device_code)
        .where(t.device_code.c.id == row.id)
        .values(
            status="approved" if right else "denied",
            approved_at=now if right else None,
            expires_at=now + COMPLETE_WITHIN if right else row.expires_at,
        )
    )
    return right


def deny(conn: Connection, row: Any) -> None:
    conn.execute(update(t.device_code).where(t.device_code.c.id == row.id).values(status="denied"))


def pending_view(conn: Connection, row: Any, now: datetime) -> dict[str, Any]:
    """What the new browser sees: no account before the approval."""
    state = status(row, now)
    view: dict[str, Any] = {
        "status": state,
        "expires_at": ts(row.expires_at),
        "match_number": row.match_number,
    }
    if state == "approved":
        human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).one()
        view["account"] = {
            "handle": human.handle,
            "display_name": human.display_name,
            "avatar_url": avatars.urls(conn, [human.id])[human.id],
        }
    return view


def complete(
    conn: Connection, row: Any, *, address: str, user_agent: str | None
) -> tuple[str, str, str]:
    """The approved code becomes the new browser's session: (cookie value, CSRF token,
    public id). One code yields at most one session."""
    approver = conn.execute(
        select(t.human_session.c.public_id).where(t.human_session.c.id_hash == row.session_hash)
    ).scalar()
    created = sessions.create(
        conn,
        row.human_id,
        method="device_code",
        address=address,
        user_agent=user_agent,
        approved_by=approver,
    )
    conn.execute(
        update(t.device_code)
        .where(t.device_code.c.id == row.id)
        .values(status="used", pending_hash=None, session_public_id=created[2])
    )
    return created


def void_open(conn: Connection, which: Any = None) -> None:
    """Deny the open codes `which` selects (all when None): a method switched off, or
    the sessions that made them ended (§2.6.5)."""
    query = update(t.device_code).where(t.device_code.c.status.in_(OPEN))
    if which is not None:
        query = query.where(which)
    conn.execute(query.values(status="denied"))
