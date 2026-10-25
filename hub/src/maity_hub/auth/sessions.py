"""A human's sessions as the session list shows them, and who may end which
(docs/api.md §2.6.5).

A session is in good standing when it was signed in by password, or when its own
`session_created` item was marked read by an allowed session (§18.3); `confirmed` below
is the set of public ids whose sign-in record was so marked.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock, ids
from maity_hub import tables as t
from maity_hub.auth.caller import (
    SESSION_ABSOLUTE,
    SESSION_IDLE,
    session_alive,
    session_expires_at,
    session_id_hash,
)
from maity_hub.errors import ApiError
from maity_hub.notifications import records
from maity_hub.views import ts

# Ended sessions stay in the list for this long (`?ended=true`).
ENDED_SHOWN = timedelta(days=30)
# A session not in good standing ends no older session while it is younger than this.
YOUNG = timedelta(hours=1)

# What a browser says about itself, matched in this order: Edge and Opera name Chrome
# too, Chrome names Safari, and every iOS browser is Safari underneath.
_BROWSERS = (
    ("Edge", re.compile(r"\bEdg(?:e|A|iOS)?/")),
    ("Opera", re.compile(r"\bOPR/|\bOpera\b")),
    ("Firefox", re.compile(r"\b(?:Firefox|FxiOS)/")),
    ("Chrome", re.compile(r"\b(?:Chrome|CriOS|Chromium)/")),
    ("Safari", re.compile(r"\bVersion/[\d.]+.*\bSafari/")),
)
_SYSTEMS = (
    ("iOS", re.compile(r"\b(?:iPhone|iPad|iPod)\b")),
    ("Android", re.compile(r"\bAndroid\b")),
    ("ChromeOS", re.compile(r"\bCrOS\b")),
    ("Windows", re.compile(r"\bWindows\b")),
    ("macOS", re.compile(r"\bMac OS X\b|\bMacintosh\b")),
    ("Linux", re.compile(r"\bLinux\b")),
)


def describe(user_agent: str | None) -> tuple[str | None, str | None]:
    """(browser, operating system) from a `User-Agent`, each None when unknown. A name
    from the list only, never text from the header: the list is shown to the human."""
    text = user_agent or ""
    browser = next((name for name, pattern in _BROWSERS if pattern.search(text)), None)
    system = next((name for name, pattern in _SYSTEMS if pattern.search(text)), None)
    return browser, system


def good_standing(row: Any, confirmed: frozenset[str] = frozenset()) -> bool:
    """§2.6.5: signed in by password, or its sign-in confirmed from another session; and
    since §2.8.2 a sign-in that included the second factor, whatever its first."""
    return bool(
        row.method == "password" or row.public_id in confirmed or row.second_factor is not None
    )


def confirmed_sessions(conn: Connection, human_id: str) -> frozenset[str]:
    """The public ids whose `session_created` record an allowed session marked read."""
    return frozenset(
        public_id
        for public_id, record in records.sign_in_records(conn, human_id).items()
        if record.read_at is not None
    )


def ended(row: Any, now: datetime) -> tuple[datetime, str] | None:
    """When and why a session ended, or None while it is alive; an expired session
    ended at its expiry."""
    if row.ended_at is not None:
        return row.ended_at, row.ended_by or "logout"
    if not session_alive(row, now):
        return session_expires_at(row), "expired"
    return None


def view(
    row: Any,
    current: str | None,
    now: datetime,
    sign_ins: dict[str, Any] | None = None,
    confirmed: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    finished = ended(row, now)
    record = (sign_ins or {}).get(row.public_id)
    return {
        "id": row.public_id,
        "current": row.id_hash == current,
        "method": row.method,
        "created_at": ts(row.created_at),
        "last_seen_at": ts(row.last_seen_at),
        "expires_at": ts(session_expires_at(row)),
        "browser": row.browser,
        "os": row.os,
        "ip": None if finished else row.ip,
        "approved_by": row.approved_by,
        "good_standing": good_standing(row, confirmed),
        "second_factor": row.second_factor is not None,
        "created": (
            {
                "record": f"acr-{record.n}",
                "ip": record.data.get("ip"),
                "browser": record.data.get("browser"),
                "os": record.data.get("os"),
            }
            if record is not None
            else None
        ),
        "ended_at": ts(finished[0]) if finished else None,
        "ended_by": finished[1] if finished else None,
    }


def listing(conn: Connection, human_id: str, current: str, *, with_ended: bool) -> list[Any]:
    """The human's sessions, newest first: the live ones, and with `with_ended` those
    ended in the last 30 days."""
    now = clock.now()
    rows = conn.execute(
        select(t.human_session)
        .where(
            t.human_session.c.human_id == human_id,
            # A session that still owes the second step is no sign-in yet (§2.8.2).
            t.human_session.c.sign_in_complete.is_(True),
        )
        .order_by(t.human_session.c.created_at.desc(), t.human_session.c.public_id.desc())
    ).all()
    forget_expired_addresses(conn)
    shown = []
    for row in rows:
        finished = ended(row, now)
        if finished is None or (with_ended and finished[0] > now - ENDED_SHOWN):
            shown.append(row)
    return shown


def refusal(
    actor: Any, target: Any, now: datetime, confirmed: frozenset[str] = frozenset()
) -> str | None:
    """Why `actor` may not end `target`, or None (§2.6.5 "Who may end which session")."""
    if actor.id_hash == target.id_hash or good_standing(actor, confirmed):
        return None
    if good_standing(target, confirmed):
        return "not_in_good_standing"
    if now - actor.created_at < YOUNG and target.created_at < actor.created_at:
        return "session_too_new"
    return None


def forbidden_to_end(reason: str) -> ApiError:
    return ApiError(403, "forbidden", "this session may not end that one", {"reason": reason})


def end(conn: Connection, rows: Iterable[Any], by: str) -> None:
    """End each live session among `rows`; an ended one keeps its end."""
    end_where(conn, t.human_session.c.id_hash.in_([row.id_hash for row in rows]), by)


def end_where(conn: Connection, which: Any, by: str) -> None:
    """End the live sessions `which` selects. The addresses go with the end: the table
    keeps no address history of an ended session (personal data), and the device codes a
    session made die with it (§2.6.2)."""
    live = which & t.human_session.c.ended_at.is_(None)
    ending = conn.execute(
        select(
            t.human_session.c.id_hash, t.human_session.c.human_id, t.human_session.c.public_id
        ).where(live)
    ).all()
    hashes = [row.id_hash for row in ending]
    if not hashes:
        return
    conn.execute(
        update(t.human_session)
        .where(t.human_session.c.id_hash.in_(hashes))
        .values(ended_at=clock.now(), ended_by=by, ip=None, source=None)
    )
    conn.execute(
        update(t.device_code)
        .where(
            t.device_code.c.session_hash.in_(hashes),
            t.device_code.c.status.in_(("waiting", "redeemed", "approved")),
        )
        .values(status="denied")
    )
    for row in ending:
        records.session_ended(conn, row.human_id, row.public_id, by)


def forget_expired_addresses(conn: Connection) -> None:
    """An expired session ended without a write; its addresses go the next time anyone
    signs in or reads a session list, for every human's sessions at once."""
    now = clock.now()
    conn.execute(
        update(t.human_session)
        .where(
            t.human_session.c.ended_at.is_(None),
            (t.human_session.c.expires_at <= now)
            | (t.human_session.c.last_seen_at <= now - SESSION_IDLE),
            (t.human_session.c.ip.is_not(None)) | (t.human_session.c.source.is_not(None)),
        )
        .values(ip=None, source=None)
    )


def approved_by_chain(conn: Connection, human_id: str, public_id: str) -> list[Any]:
    """The sessions `public_id` approved by device code, and those they approved in turn
    (§2.6.5, "End this session")."""
    rows = conn.execute(select(t.human_session).where(t.human_session.c.human_id == human_id)).all()
    children: dict[str, list[Any]] = {}
    for row in rows:
        if row.approved_by is not None:
            children.setdefault(row.approved_by, []).append(row)
    found: list[Any] = []
    queue = [public_id]
    while queue:
        for row in children.get(queue.pop(), []):
            if row not in found:
                found.append(row)
                queue.append(row.public_id)
    return found


NEXT_MAX = 512
_NEXT_BAD = re.compile(r"[\\\s\x00-\x1f\x7f]|//")


def safe_next(value: str | None) -> str:
    """A login's `next` (§2.6.5): `/` or a dashboard route `/#/…` on the public host,
    at most 512 characters, without a backslash, whitespace, a control or format
    character, a second `#` or `//`. Anything else becomes `/`, silently."""
    if (
        not value
        or len(value) > NEXT_MAX
        or not (value == "/" or value.startswith("/#/"))
        or value.count("#") > 1
        or _NEXT_BAD.search(value)
        # C1 controls, bidi overrides, zero-width and other format characters.
        or any(unicodedata.category(c) in ("Cc", "Cf") for c in value)
    ):
        return "/"
    return value


def create(
    conn: Connection,
    human_id: str,
    *,
    method: str,
    address: str,
    user_agent: str | None,
    approved_by: str | None = None,
    state: str = "full",
    next_route: str | None = None,
) -> tuple[str, str, str]:
    """A new session of `human_id`: (cookie value, CSRF token, public id). Only the
    cookie value's hash is stored. A session that still owes the second step of a
    two-factor sign-in (`state` other than `full`, §2.8.2) is not a sign-in yet: no
    record, no `last_login_at`; `complete_sign_in` makes it one."""
    now = clock.now()
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
    browser, system = describe(user_agent)
    public_id = ids.new_id("human_session")
    complete = state == "full"
    conn.execute(
        insert(t.human_session).values(
            id_hash=session_id_hash(session_id),
            human_id=human_id,
            csrf_token=csrf,
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_ABSOLUTE,
            source=address[:64],
            public_id=public_id,
            method=method,
            browser=browser,
            os=system,
            ip=address[:64],
            approved_by=approved_by,
            state=state,
            sign_in_complete=complete,
            password_at=now if method == "password" else None,
            next=next_route,
        )
    )
    if complete:
        _signed_in(conn, human_id, public_id, now)
    else:
        conn.execute(update(t.human).where(t.human.c.id == human_id).values(last_seen_at=now))
    return session_id, csrf, public_id


def _signed_in(conn: Connection, human_id: str, public_id: str, now: datetime) -> None:
    """A sign-in counts: `last_login_at` moves and the human is told (§2.6.5)."""
    row = conn.execute(
        select(t.human_session).where(t.human_session.c.public_id == public_id)
    ).one()
    conn.execute(update(t.human).where(t.human.c.id == human_id).values(last_login_at=now))
    # Every new session tells its human, whichever the method (§2.6.5).
    data: dict[str, Any] = {
        "session_id": public_id,
        "method": row.method,
        "browser": row.browser,
        "os": row.os,
        "ip": row.ip,
        "approved_by": row.approved_by,
    }
    if row.second_factor is not None:
        data["second_factor"] = row.second_factor
    records.session_created(conn, human_id, data)


def complete_in_place(conn: Connection, row: Any) -> None:
    """A session held at enrolment whose reason went away completes its sign-in as it
    is, without a new cookie: it never gave a second factor to rotate for."""
    done = conn.execute(
        update(t.human_session)
        .where(
            t.human_session.c.id_hash == row.id_hash, t.human_session.c.sign_in_complete.is_(False)
        )
        .values(state="full", sign_in_complete=True)
    )
    if done.rowcount == 1:
        _signed_in(conn, row.human_id, row.public_id, clock.now())


def complete_sign_in(conn: Connection, row: Any, second_factor: str | None) -> tuple[str, str]:
    """The second step of a two-factor sign-in is done (§2.8.2): the session gets a fresh
    cookie value and CSRF token (the fixation rule applies now, not at the first
    factor), becomes `full`, and only now counts as a sign-in. Conditional on the row
    still owing that step, so of two concurrent completions one wins; the other raises
    `LookupError`."""
    now = clock.now()
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
    values: dict[str, Any] = {
        "id_hash": session_id_hash(session_id),
        "csrf_token": csrf,
        "state": "full",
        "sign_in_complete": True,
        "last_seen_at": now,
    }
    if second_factor is not None:
        values.update(second_factor=second_factor, second_factor_at=now)
    done = conn.execute(
        update(t.human_session)
        .where(
            t.human_session.c.id_hash == row.id_hash,
            t.human_session.c.sign_in_complete.is_(False),
            t.human_session.c.ended_at.is_(None),
        )
        .values(**values)
    )
    if done.rowcount != 1:
        raise LookupError("the sign-in was completed or ended meanwhile")
    _signed_in(conn, row.human_id, row.public_id, now)
    return session_id, csrf


# --- the device cookie (§2.6.5) ------------------------------------------------------

DEVICE_COOKIE = "maity_device"
DEVICE_LIFETIME = timedelta(days=400)
# One value per human who signed in on this browser; the oldest drop out past this.
DEVICE_VALUES = 4


def _device_values(cookie: str | None) -> list[str]:
    return [v for v in (cookie or "").split(".") if 0 < len(v) <= 64][-DEVICE_VALUES:]


def knows_device(conn: Connection, human_id: str, cookie: str | None) -> bool:
    """Whether this browser's device cookie holds a value of this human."""
    hashes = [hashlib.sha256(v.encode()).hexdigest() for v in _device_values(cookie)]
    if not hashes:
        return False
    found = conn.execute(
        select(t.human_device.c.value_hash).where(
            t.human_device.c.human_id == human_id, t.human_device.c.value_hash.in_(hashes)
        )
    ).first()
    return found is not None


def remember_device(conn: Connection, human_id: str, cookie: str | None) -> str | None:
    """At a completed sign-in: the cookie's new value when this browser held no value of
    this human, else None (the cookie stays as it is)."""
    if knows_device(conn, human_id, cookie):
        return None
    value = secrets.token_urlsafe(32)
    conn.execute(
        insert(t.human_device).values(
            value_hash=hashlib.sha256(value.encode()).hexdigest(),
            human_id=human_id,
            created_at=clock.now(),
        )
    )
    return ".".join([*_device_values(cookie), value][-DEVICE_VALUES:])
