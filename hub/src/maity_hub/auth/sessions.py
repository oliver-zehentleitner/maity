"""A human's sessions as the session list shows them, and who may end which
(docs/api.md §2.6.5).

A session is in good standing when it was signed in by password, or when its own
`session_created` item was marked read by an allowed session. Only the password exists
as a method so far, so every session is in good standing until the device code and the
mail link add the others; the rules below are written for both already.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth.caller import session_alive, session_expires_at
from maity_hub.errors import ApiError
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


def good_standing(row: Any) -> bool:
    """§2.6.5. Without account records yet, only the password grants it."""
    return bool(row.method == "password")


def ended(row: Any, now: datetime) -> tuple[datetime, str] | None:
    """When and why a session ended, or None while it is alive; an expired session
    ended at its expiry."""
    if row.ended_at is not None:
        return row.ended_at, row.ended_by or "logout"
    if not session_alive(row, now):
        return session_expires_at(row), "expired"
    return None


def view(row: Any, current: str | None, now: datetime) -> dict[str, Any]:
    finished = ended(row, now)
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
        "good_standing": good_standing(row),
        # The account record of the sign-in (§2.6.5) arrives with account records.
        "created": None,
        "ended_at": ts(finished[0]) if finished else None,
        "ended_by": finished[1] if finished else None,
    }


def listing(conn: Connection, human_id: str, current: str, *, with_ended: bool) -> list[Any]:
    """The human's sessions, newest first: the live ones, and with `with_ended` those
    ended in the last 30 days."""
    now = clock.now()
    rows = conn.execute(
        select(t.human_session)
        .where(t.human_session.c.human_id == human_id)
        .order_by(t.human_session.c.created_at.desc(), t.human_session.c.public_id.desc())
    ).all()
    forget_expired_addresses(conn, rows, now)
    shown = []
    for row in rows:
        finished = ended(row, now)
        if finished is None or (with_ended and finished[0] > now - ENDED_SHOWN):
            shown.append(row)
    return shown


def refusal(actor: Any, target: Any, now: datetime) -> str | None:
    """Why `actor` may not end `target`, or None (§2.6.5 "Who may end which session")."""
    if actor.id_hash == target.id_hash or good_standing(actor):
        return None
    if good_standing(target):
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
    keeps no address history of an ended session (personal data)."""
    conn.execute(
        update(t.human_session)
        .where(which, t.human_session.c.ended_at.is_(None))
        .values(ended_at=clock.now(), ended_by=by, ip=None, source=None)
    )


def forget_expired_addresses(conn: Connection, rows: Iterable[Any], now: datetime) -> None:
    """An expired session ended without a write; its addresses go when it is next seen."""
    stale = [
        row.id_hash
        for row in rows
        if row.ended_at is None and not session_alive(row, now) and (row.ip or row.source)
    ]
    if stale:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.id_hash.in_(stale))
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
    at most 512 characters, without a backslash, whitespace, a control character, a
    second `#` or `//`. Anything else becomes `/`, silently."""
    if (
        not value
        or len(value) > NEXT_MAX
        or not (value == "/" or value.startswith("/#/"))
        or value.count("#") > 1
        or _NEXT_BAD.search(value)
    ):
        return "/"
    return value
