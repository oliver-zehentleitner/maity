"""The owner's digest of agent instances that are not listening (docs/api.md §5.3).

An instance is *away* when its session's episode (`not_listening_since`, `not_listening`)
has lasted the owner's threshold for that project: their own override there (§6.2) or
else their personal `not_listening.minutes` (§18.4). Once an hour, on the hour (UTC),
the worker looks at every owner's away instances.

This module does the `bell` mode: the account record `agents_not_listening`. The table
is append-only, so the worker writes only when the state flips: `{instances: n}` when an
owner's first instance becomes away, `{instances: 0}` when none is away any more or the
mode leaves `bell`. Whether the bell's item is open, and the count in its title, are
derived when it is read (`away_of`), so it is listed exactly while an instance is away.
The `inbox` mode (one personal request per owner) comes with the digest request; until
then an owner under `inbox` hears of an episode as before, one request per episode. A mode
other than `inbox` withdraws those per-episode requests still open at the next hour, so
the modes never add up for longer than that.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.events import lock_project, transaction
from maity_hub.notifications import preferences, records

log = logging.getLogger(__name__)

RECORD = "agents_not_listening"
CHECK_EVERY = 60.0  # seconds between the worker's looks at the clock


@dataclass(frozen=True)
class Away:
    agent_id: str
    handle: str
    instance: str
    project_id: str
    since: datetime


def _episodes(conn: Connection, owner_id: str | None = None) -> list[Any]:
    """Every session in an episode, with its agent's owner, handle, instance and project."""
    query = (
        select(
            t.agent_session.c.not_listening_since.label("since"),
            t.membership.c.agent_id,
            t.membership.c.project_id,
            t.agent_profile.c.owner_id,
            t.agent_profile.c.handle,
            t.credential.c.instance,
        )
        .join(t.membership, t.membership.c.id == t.agent_session.c.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .join(t.credential, t.credential.c.id == t.agent_session.c.credential_id)
        .where(t.agent_session.c.not_listening_since.isnot(None))
    )
    if owner_id is not None:
        query = query.where(t.agent_profile.c.owner_id == owner_id)
    return list(conn.execute(query).all())


def _thresholds(conn: Connection, owner_id: str, project_ids: set[str]) -> dict[str, int]:
    """Minutes per project for this owner: their override there, else their personal
    default (§6.2), whether or not they are a member of the project."""
    personal = int(preferences.preferences(conn, owner_id)["not_listening"]["minutes"])
    found = dict.fromkeys(project_ids, personal)
    if not project_ids:
        return found
    for project_id, own in conn.execute(
        select(t.membership.c.project_id, t.membership.c.own_settings).where(
            t.membership.c.human_id == owner_id,
            t.membership.c.active.is_(True),
            t.membership.c.project_id.in_(project_ids),
        )
    ):
        minutes = ((own or {}).get("not_listening") or {}).get("minutes")
        if minutes is not None:
            found[project_id] = int(minutes)
    return found


def _away(conn: Connection, rows: list[Any], owner_id: str, now: datetime) -> list[Away]:
    minutes = _thresholds(conn, owner_id, {r.project_id for r in rows})
    return sorted(
        (
            Away(r.agent_id, r.handle, r.instance, r.project_id, r.since)
            for r in rows
            if now - r.since >= timedelta(minutes=minutes[r.project_id])
        ),
        key=lambda a: (a.since, a.handle, a.instance),
    )


def away_of(conn: Connection, owner_id: str, now: datetime | None = None) -> list[Away]:
    """The owner's instances that are away now, oldest episode first."""
    return _away(conn, _episodes(conn, owner_id), owner_id, now or clock.now())


def latest(conn: Connection, owner_id: str, now: datetime | None = None) -> Any | None:
    """The owner's newest `agents_not_listening` record within the window the bell reads
    (`records.KEPT`), open when its count is not 0. An open record that left the window is
    not seen, so `reconcile` writes a new one and the bell keeps listing it."""
    since = (now or clock.now()) - records.KEPT
    return conn.execute(
        select(t.account_record)
        .where(
            t.account_record.c.human_id == owner_id,
            t.account_record.c.type == RECORD,
            t.account_record.c.at >= since,
        )
        .order_by(t.account_record.c.n.desc())
        .limit(1)
    ).first()


def _is_open(row: Any | None) -> bool:
    return row is not None and int((row.data or {}).get("instances", 0)) > 0


def withdraw_episode_requests(conn: Connection, owner_id: str) -> None:
    """Withdraw the per-episode requests still open for the owner's sessions (§5.3): they
    belong to `inbox` only. The session forgets the request only if it still holds this
    one, so a request the episode's own check filed meanwhile is never lost."""
    from maity_hub.routes.requests import withdraw_hub_notice

    s = t.agent_session.c
    held = conn.execute(
        select(s.id, s.not_listening_request_id, t.membership.c.project_id)
        .join(t.membership, t.membership.c.id == s.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.agent_profile.c.owner_id == owner_id, s.not_listening_request_id.isnot(None))
        .order_by(t.membership.c.project_id, s.id)
    ).all()
    # The projects' locks first, as the episode's own check takes them (not_listening.check):
    # the request's withdrawal emits under that lock, so the other order could deadlock.
    for project_id in sorted({row.project_id for row in held}):
        lock_project(conn, project_id)
    for session_id, request_id, _ in held:
        withdraw_hub_notice(conn, request_id, "the owner's digest replaces it")
        conn.execute(
            update(t.agent_session)
            .where(s.id == session_id, s.not_listening_request_id == request_id)
            .values(not_listening_request_id=None)
        )


def reconcile(conn: Connection, owner_id: str, now: datetime | None = None) -> None:
    """Bring one owner's record and requests in line with their mode and their away
    instances."""
    mode = preferences.preferences(conn, owner_id)["not_listening"]["mode"]
    if mode != "inbox":
        withdraw_episode_requests(conn, owner_id)
    count = len(away_of(conn, owner_id, now)) if mode == "bell" else 0
    open_ = _is_open(latest(conn, owner_id, now))
    if count and not open_:
        records.write(conn, owner_id, RECORD, {"instances": count})
    elif not count and open_:
        records.write(conn, owner_id, RECORD, {"instances": 0})


def mode_changed(conn: Connection, owner_id: str, old: str, new: str) -> None:
    """A change of `not_listening.mode` takes effect at the `PATCH` (§5.3): leaving
    `bell` closes an open record at once. Leaving `inbox` withdraws its per-episode
    requests at the next hour (`reconcile`): a withdrawal wakes the asker, and the `PATCH`
    is no events transaction."""
    if old == "bell" and new != "bell" and _is_open(latest(conn, owner_id)):
        records.write(conn, owner_id, RECORD, {"instances": 0})


def run(engine: Engine, now: datetime | None = None) -> None:
    """One hour's pass over every owner with an episode or with an open record."""
    now = now or clock.now()
    with engine.connect() as conn:
        owners = {r.owner_id for r in _episodes(conn) if r.owner_id}
        owners |= {
            h
            for h in conn.execute(
                select(t.account_record.c.human_id)
                .where(t.account_record.c.type == RECORD)
                .distinct()
            ).scalars()
        }
    for owner_id in sorted(owners):
        with transaction(engine) as conn:
            reconcile(conn, owner_id, now)


def next_hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


class Worker:
    """Runs `run` on the hour (UTC), looking at the clock once a minute (§5.3)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = CHECK_EVERY if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._due = next_hour(clock.now())

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="maity-not-listening-digest", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            now = clock.now()
            if now < self._due:
                continue
            self._due = next_hour(now)
            try:
                run(self.engine, now)
            except Exception:
                log.exception("the not-listening digest failed")
