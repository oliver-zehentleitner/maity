"""Maintenance windows (docs/api.md §16.12, hub/context/maintenance.md).

At most one window is active or upcoming. Its state comes from the clock on every read, so a
window ends at `until` by itself; the deadlines that fell into it move by its length once,
on the first read after its end (`settle`). While it runs, the middleware answers `503
maintenance` (`refusal`), and the sweeps that decide on deadlines by themselves wait
(`running_now`).
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, and_, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from maity_hub.ids import new_id

TEXT_MAX = 500
AGENTS_MAX = 200
MODES = ("accept_all", "refuse_all", "accept_only", "refuse_for")
CACHE_SECONDS = 5.0  # how long one replica trusts its last read of the window

_lock = threading.Lock()
_cached: tuple[float, dict[str, Any] | None] | None = None


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def current(conn: Connection) -> Any:
    """The window that is active or upcoming now, or None. One the clock has passed but whose
    deadlines are not moved yet is settled first, in this transaction."""
    now = clock.now()
    settle(conn, now)
    return conn.execute(
        select(t.maintenance_window).where(
            t.maintenance_window.c.cancelled_at.is_(None),
            t.maintenance_window.c.ends_at > now,
        )
    ).first()


def state(row: Any, now: datetime | None = None) -> str:
    return "running" if row.starts_at <= (now or clock.now()) else "upcoming"


def view(row: Any | None, *, admin: bool = False) -> dict[str, Any] | None:
    """`{from, until, text, state}` of a window, for `GET /maintenance`, `/me` and the packet;
    the admin's read adds who set it and when."""
    if row is None:
        return None
    found: dict[str, Any] = {
        "from": clock.rfc3339(row.starts_at),
        "until": clock.rfc3339(row.ends_at),
        "text": row.text,
        "state": state(row),
    }
    if admin:
        found |= {
            "by": row.updated_by,
            "created_at": clock.rfc3339(row.created_at),
            "updated_at": clock.rfc3339(row.updated_at),
        }
    return found


def window_now(engine: Engine) -> dict[str, Any] | None:
    """The view of the current window, read at most every few seconds per process: what the
    middleware asks on every request. `forget` drops it after a change on this replica."""
    global _cached
    with _lock:
        if _cached is not None and time.monotonic() - _cached[0] < CACHE_SECONDS:
            found = _cached[1]
            # The clock may pass `until` or `from` inside the cache's few seconds.
            return _refreshed(found)
    with engine.begin() as conn:
        found = view(current(conn))
    with _lock:
        _cached = (time.monotonic(), found)
    return found


def _refreshed(found: dict[str, Any] | None) -> dict[str, Any] | None:
    if found is None:
        return None
    now = clock.now()
    if _parse(found["until"]) <= now:
        return None
    if found["state"] == "upcoming" and _parse(found["from"]) <= now:
        return {**found, "state": "running"}
    return found


def forget() -> None:
    """Drop this replica's cached window (after a change, and in tests)."""
    global _cached
    with _lock:
        _cached = None


def running_now(engine: Engine) -> bool:
    """Whether a window runs: the sweeps that decide on deadlines wait then (§16.12)."""
    found = window_now(engine)
    return found is not None and found["state"] == "running"


def retry_after(found: dict[str, Any]) -> int:
    """Seconds until the window's `until`, at least 1."""
    left = (_parse(found["until"]) - clock.now()).total_seconds()
    return max(1, math.ceil(left))


# --- changes by the instance admin -------------------------------------------------------


def _record(conn: Connection, row: Any, action: str, by: str, now: datetime) -> None:
    conn.execute(
        t.maintenance_change.insert().values(
            id=new_id("maintenance_change"),
            window_id=row.id,
            action=action,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            text=row.text,
            by=by,
            at=now,
        )
    )


def put(conn: Connection, starts_at: datetime, ends_at: datetime, text: str, by: str) -> Any:
    """Create the window, or change the active or upcoming one; returns the row. The caller
    has checked the fields (`check`)."""
    now = clock.now()
    row = current(conn)
    if row is None:
        window_id = new_id("maintenance_window")
        conn.execute(
            t.maintenance_window.insert().values(
                id=window_id,
                starts_at=starts_at,
                ends_at=ends_at,
                text=text,
                created_by=by,
                created_at=now,
                updated_by=by,
                updated_at=now,
            )
        )
        action = "created"
    else:
        window_id = row.id
        conn.execute(
            update(t.maintenance_window)
            .where(t.maintenance_window.c.id == window_id)
            .values(starts_at=starts_at, ends_at=ends_at, text=text, updated_by=by, updated_at=now)
        )
        action = "changed"
    saved = conn.execute(
        select(t.maintenance_window).where(t.maintenance_window.c.id == window_id)
    ).one()
    _record(conn, saved, action, by, now)
    broadcast(conn, "maintenance_scheduled", saved, by)
    forget()
    return saved


def cancel(conn: Connection, row: Any, by: str) -> None:
    """Withdraw an upcoming window."""
    now = clock.now()
    conn.execute(
        update(t.maintenance_window)
        .where(t.maintenance_window.c.id == row.id)
        .values(cancelled_at=now, updated_by=by, updated_at=now)
    )
    _record(conn, row, "cancelled", by, now)
    broadcast(conn, "maintenance_cancelled", row, by)
    forget()


def end(conn: Connection, row: Any, by: str) -> None:
    """End a running window now: its `until` becomes now, and the deadlines move at once."""
    now = clock.now()
    conn.execute(
        update(t.maintenance_window)
        .where(t.maintenance_window.c.id == row.id)
        .values(ends_at=now, updated_by=by, updated_at=now)
    )
    ended = conn.execute(
        select(t.maintenance_window).where(t.maintenance_window.c.id == row.id)
    ).one()
    _record(conn, ended, "ended", by, now)
    settle(conn, now)
    forget()


def check(fields: dict[str, Any], running: Any | None) -> dict[str, str]:
    """The field errors of a `PUT` (§16.12): `from` before `until`, `until` in the future,
    the text 1–500 characters; a running window keeps its `from`."""
    errors: dict[str, str] = {}
    starts_at, ends_at, text = fields["from"], fields["until"], fields["text"]
    if not text:
        errors["text"] = "too_short"
    elif len(text) > TEXT_MAX:
        errors["text"] = "too_long"
    if ends_at <= clock.now():
        errors["until"] = "until_past"
    if starts_at >= ends_at:
        errors["from"] = "from_after_until"
    if running is not None and state(running) == "running" and starts_at != running.starts_at:
        errors["from"] = "running"
    return errors


# --- the deadlines that fell into a window --------------------------------------------------


def settle(conn: Connection, now: datetime) -> None:
    """Move the deadlines that fell into each window that is over and not yet settled, by the
    window's length, once (a conditional update claims the window, so two replicas do not
    both move them)."""
    over = conn.execute(
        select(t.maintenance_window).where(
            t.maintenance_window.c.cancelled_at.is_(None),
            t.maintenance_window.c.settled_at.is_(None),
            t.maintenance_window.c.ends_at <= now,
        )
    ).all()
    for row in over:
        claimed = conn.execute(
            update(t.maintenance_window)
            .where(
                t.maintenance_window.c.id == row.id,
                t.maintenance_window.c.settled_at.is_(None),
            )
            .values(settled_at=now)
        ).rowcount
        if claimed:
            shift(conn, row.starts_at, row.ends_at)


def _inside(column: Any, starts_at: datetime, ends_at: datetime) -> Any:
    return and_(column.is_not(None), column > starts_at, column <= ends_at)


def shift(conn: Connection, starts_at: datetime, ends_at: datetime) -> None:
    """Every deadline the hub acts on by itself that fell into `(starts_at, ends_at]` moves by
    the window's length (§16.12): a claim's lease, a jour fixe round's answers and report and
    each of its steps' `closes_at`, and an outage's start, which the grace of a substitution
    counts from."""
    length = ends_at - starts_at
    card = t.card.c
    conn.execute(
        update(t.card)
        .where(_inside(card.lease_until, starts_at, ends_at))
        .values(lease_until=card.lease_until + length)
    )
    member = t.membership.c
    conn.execute(
        update(t.membership)
        .where(_inside(member.outage_since, starts_at, ends_at))
        .values(outage_since=member.outage_since + length)
    )
    rounds = t.jour_fixe_round.c
    for column in (rounds.answers_close_at, rounds.report_due_at):
        conn.execute(
            update(t.jour_fixe_round)
            .where(_inside(column, starts_at, ends_at))
            .values({column.name: column + length})
        )
    open_rounds = conn.execute(
        select(rounds.id, rounds.steps).where(
            rounds.reported_at.is_(None), rounds.steps.is_not(None)
        )
    ).all()
    for found in open_rounds:
        steps = _shifted_steps(found.steps, starts_at, ends_at, length)
        if steps is not None:
            conn.execute(update(t.jour_fixe_round).where(rounds.id == found.id).values(steps=steps))


def _shifted_steps(
    steps: Any, starts_at: datetime, ends_at: datetime, length: timedelta
) -> list[Any] | None:
    """The round's steps with each `closes_at` inside the window moved, or None when none is."""
    if not isinstance(steps, list):
        return None
    moved = False
    out: list[Any] = []
    for step in steps:
        closes = step.get("closes_at") if isinstance(step, dict) else None
        if isinstance(closes, str):
            at = _parse(closes)
            if starts_at < at <= ends_at:
                step = {**step, "closes_at": clock.rfc3339(at + length)}
                moved = True
        out.append(step)
    return out if moved else None


# --- the broadcast and each owner's choice --------------------------------------------------


def accepts(choice: Any, agent_id: str) -> bool:
    """Whether an owner's `broadcasts` choice lets the hub's broadcast reach `agent_id`."""
    if not isinstance(choice, dict):
        return True  # never set: accept_all
    mode, listed = choice.get("mode", "accept_all"), set(choice.get("agents") or [])
    if mode == "refuse_all":
        return False
    if mode == "accept_only":
        return agent_id in listed
    if mode == "refuse_for":
        return agent_id not in listed
    return True


def broadcast(conn: Connection, kind: str, row: Any, by: str) -> None:
    """One event per project with at least one agent member whose owner accepts, addressed to
    those agents alone (§16.12, §8.2). No hub-wide stream exists."""
    members = conn.execute(
        select(t.membership.c.id, t.membership.c.project_id, t.membership.c.agent_id)
        .where(t.membership.c.active.is_(True), t.membership.c.agent_id.is_not(None))
        .order_by(t.membership.c.project_id, t.membership.c.id)
    ).all()
    owners = dict(
        conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.owner_id).where(
                t.agent_profile.c.id.in_({m.agent_id for m in members})
            )
        ).all()
    )
    choices = dict(
        conn.execute(
            select(t.human.c.id, t.human.c.broadcasts).where(t.human.c.id.in_(set(owners.values())))
        ).all()
    )
    audience: dict[str, list[str]] = {}
    for m in members:
        if accepts(choices.get(owners.get(m.agent_id)), m.agent_id):
            audience.setdefault(m.project_id, []).append(f"member:{m.agent_id}")
    payload = {
        "window": {
            "from": clock.rfc3339(row.starts_at),
            "until": clock.rfc3339(row.ends_at),
            "text": row.text,
        },
        "by": by,
    }
    for project_id, tokens in audience.items():
        events.emit(conn, project_id, kind, tokens, payload, actor=events.Actor(None, human_id=by))


def check_choice(body: dict[str, Any], own_agents: Iterable[str]) -> dict[str, str]:
    """The field errors of `PATCH /me/broadcasts`."""
    errors: dict[str, str] = {}
    mode, agents = body.get("mode"), body.get("agents") or []
    if mode not in MODES:
        errors["mode"] = "invalid"
    if not isinstance(agents, list) or not all(isinstance(a, str) for a in agents):
        errors["agents"] = "invalid"
        return errors
    if len(agents) > AGENTS_MAX:
        errors["agents"] = "too_many"
    elif mode in ("accept_all", "refuse_all") and agents:
        errors["agents"] = "not_allowed"
    elif set(agents) - set(own_agents):
        errors["agents"] = "not_your_agent"
    return errors
