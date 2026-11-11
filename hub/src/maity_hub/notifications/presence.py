"""Whether a human is present in the web app, for the notification mail's hold (§18.4, §18.5).

A dashboard tab calls `POST /me/presence` every minute while it is visible and had input
within ten minutes. `mark` moves the session's `present_until` to `PRESENT_FOR` after the
call, but only when that moves it by at least `MOVE`: the write is conditional on the
stored value, so the calls of every tab of one session write at most once a minute between
them, and two calls at once write once. `held` is the mailer's one question. Nothing else
reads `present_until`: it is no presence anyone sees (hub/context/notifications.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, exists, or_, select, update

from maity_hub import tables as t
from maity_hub.auth.caller import SESSION_IDLE
from maity_hub.ratelimit import Limiter

PRESENT_FOR = timedelta(minutes=2)
MOVE = timedelta(minutes=1)
# Counted in the process only (§1.7): a shared count would write a row for every call, the
# write the throttle above keeps off this route.
CALLS = Limiter(10, 60, name="presence.CALLS", local=True)


def mark(conn: Connection, session_hash: str, now: datetime) -> bool:
    """The session is present until `now + PRESENT_FOR`; whether this call wrote it."""
    until = now + PRESENT_FOR
    column = t.human_session.c.present_until
    written = conn.execute(
        update(t.human_session)
        .where(
            t.human_session.c.id_hash == session_hash,
            or_(column.is_(None), column <= until - MOVE),
        )
        .values(present_until=until)
    )
    return written.rowcount == 1


def held(conn: Connection, human_id: str, now: datetime, grace: timedelta) -> bool:
    """Whether one of the human's live sessions is present, or was within `grace` (§18.5).
    A session that is signed out, ended or expired stops counting at once."""
    session = t.human_session.c
    return bool(
        conn.execute(
            select(
                exists().where(
                    session.human_id == human_id,
                    session.ended_at.is_(None),
                    session.expires_at > now,
                    session.last_seen_at > now - SESSION_IDLE,
                    session.present_until > now - grace,
                )
            )
        ).scalar()
    )
