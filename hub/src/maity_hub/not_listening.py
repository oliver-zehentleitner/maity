"""An agent session that is not listening (docs/api.md §5.3).

A session is not listening when an event waits for its instance (wake-relevant for its
member and pointed at the instance by the team's wake rule), created 10 minutes ago or
longer and above the session's acknowledged cursor, and the session has made no call
for events and no resume in those 10 minutes. The worker checks every minute.

An episode lives on the session row: `not_listening_since` (when the 10 minutes ran
out) and `not_listening_seq` (the oldest event that was waiting). It starts with
`member_not_listening` (`ended: false`); it ends when the acknowledged cursor reaches that
event, when the session ends, or when an exclusion begins, with `member_not_listening`
(`ended: true`). It files no request of its own: the owner hears of it through the hourly
digest (`not_listening_digest`). A session never not listening: one with
an open long-poll, a paused instance or membership, an agent that is not `available`,
and a session a runner supervises (§15.11).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, or_, select, update

from maity_hub import clock, events, listening
from maity_hub import tables as t
from maity_hub.events import emit, lock_project, transaction
from maity_hub.views import principal_id

log = logging.getLogger(__name__)

WAIT = timedelta(minutes=10)
INTERVAL = 60.0  # seconds between the worker's checks


def called(conn: Connection, session_id: str | None) -> None:
    """A call for events: the session listens, whatever it acknowledges (§5.3)."""
    if session_id is None:
        return
    conn.execute(
        update(t.agent_session)
        .where(t.agent_session.c.id == session_id)
        .values(events_at=clock.now())
    )


class _Unnarrowed:
    """An event row as if no team had narrowed it, for the instances the hub chose none
    of: then the event waits for the lead instance, or for every instance (§5.3)."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def __getattr__(self, name: str) -> Any:
        return None if name == "wakes" else getattr(self._row, name)


def waits_for(row: Any, member: Any, principal: str, credential: Any) -> bool:
    """Whether the event waits for this instance (§5.3)."""
    if events.wakes(row, member, principal, credential.instance, credential.id):
        return True
    chosen = (row.wakes or {}).get(principal)
    if chosen != [] or not events.wakes(
        _Unnarrowed(row), member, principal, credential.instance, credential.id
    ):
        return False
    return member.lead_instance is None or credential.instance == member.lead_instance


def oldest_waiting(conn: Connection, session: Any, member: Any, credential: Any) -> Any | None:
    """The oldest event above the session's cursor that waits for its instance."""
    principal = member.agent_id
    after = session.acknowledged_seq
    while True:
        rows, examined, truncated = events.read(
            conn, member.project_id, member, principal, after, 500
        )
        for row in rows:
            if waits_for(row, member, principal, credential):
                return row
        if not truncated and len(rows) < 500:
            return None
        if examined <= after:
            return None
        after = examined


def _excluded(session: Any, member: Any, credential: Any) -> str | None:
    """Why this session is never not listening now, or None."""
    if session.live is None or session.ended_at is not None:
        return "the session ended"
    if session.supervisor is not None:
        return "a runner supervises the session"
    if credential.revoked_at is not None:
        return "the credential was revoked"
    if credential.paused_since is not None or member.paused_since is not None:
        return "the agent is paused"
    if member.active is None or member.removed_at is not None:
        return "the agent left the project"
    if (member.availability_state or "available") != "available":
        return "the agent is not available"
    return None


def _audience(conn: Connection, member: Any) -> list[str]:
    """The member the agent reports to, the admins, and the profile's owner when a
    member (§8.2)."""
    audience = ["trust:admin"]
    boss = principal_id(conn, member.reports_to)
    if boss is not None:
        audience.insert(0, f"member:{boss}")
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == member.agent_id)
    ).scalar()
    owner_member = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == member.project_id,
            t.membership.c.human_id == owner,
            t.membership.c.active.is_(True),
        )
    ).first()
    if owner_member is not None and f"member:{owner}" not in audience:
        audience.append(f"member:{owner}")
    return audience


def _announce(
    conn: Connection, member: Any, credential: Any, session: Any, since: datetime, ended: bool
) -> None:
    emit(
        conn,
        member.project_id,
        "member_not_listening",
        _audience(conn, member),
        {
            "member_id": member.agent_id,
            "instance": credential.instance,
            "session_id": session.id,
            "since": clock.rfc3339(since),
            "ended": ended,
        },
        subject=("member", member.agent_id),
    )


def _end(conn: Connection, member: Any, credential: Any, session: Any, reason: str) -> None:
    from maity_hub.routes.requests import withdraw_hub_notice

    # A request filed per episode before the owner's digest replaced it (§5.3); the digest's
    # first hour withdraws the others.
    withdraw_hub_notice(conn, session.not_listening_request_id, reason)
    _announce(conn, member, credential, session, session.not_listening_since, ended=True)
    conn.execute(
        update(t.agent_session)
        .where(t.agent_session.c.id == session.id)
        .values(not_listening_since=None, not_listening_seq=None, not_listening_request_id=None)
    )


def check(engine: Engine, session_id: str) -> None:
    """One session: start, end or keep its episode, under its project's lock."""
    with transaction(engine) as conn:
        session = conn.execute(
            select(t.agent_session).where(t.agent_session.c.id == session_id)
        ).one()
        member = conn.execute(
            select(t.membership).where(t.membership.c.id == session.membership_id)
        ).one()
        lock_project(conn, member.project_id)
        # Read again under the lock: whoever held it may have paused the agent, changed
        # its availability, its team's wake rule or its reports-to meanwhile.
        member = conn.execute(
            select(t.membership).where(t.membership.c.id == session.membership_id)
        ).one()
        session = conn.execute(
            select(t.agent_session).where(t.agent_session.c.id == session_id)
        ).one()
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == session.credential_id)
        ).one()
        why = _excluded(session, member, credential)
        if session.not_listening_since is not None:
            if why is not None:
                _end(conn, member, credential, session, why)
            elif session.acknowledged_seq >= session.not_listening_seq:
                _end(conn, member, credential, session, "the agent read its events again")
            return
        if why is not None or listening.is_listening(session.id):
            return
        now = clock.now()
        called_at = session.events_at or session.started_at
        if called_at > now - WAIT:
            return
        oldest = oldest_waiting(conn, session, member, credential)
        if oldest is None or oldest.at > now - WAIT:
            return
        since = max(oldest.at, called_at) + WAIT
        # No request of its own: the owner hears of it through the digest (§5.3).
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.id == session.id)
            .values(not_listening_since=since, not_listening_seq=oldest.seq)
        )
        refreshed = conn.execute(
            select(t.agent_session).where(t.agent_session.c.id == session_id)
        ).one()
        _announce(conn, member, credential, refreshed, since, ended=False)


def sweep(engine: Engine) -> None:
    """Every live agent session, and every session with an episode still open."""
    with engine.connect() as conn:
        ids = (
            conn.execute(
                select(t.agent_session.c.id).where(
                    or_(
                        t.agent_session.c.live.is_(True),
                        t.agent_session.c.not_listening_since.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    for session_id in ids:
        try:
            check(engine, session_id)
        except Exception:  # one session's failure must not stop the others
            log.exception("the not-listening check of %s failed", session_id)


class Worker:
    """Runs `sweep` every minute (§5.3)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-not-listening", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                sweep(self.engine)
            except Exception:
                log.exception("the not-listening sweep failed")
