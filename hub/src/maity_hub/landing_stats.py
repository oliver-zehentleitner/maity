"""The counters of the landing page (docs/api.md §16.7, "The stats").

Computed by the hub at most every five minutes and shared by every visitor, never per request:
people (active human accounts), agents (agent profiles with an active membership), and the two
online counts by the presence rule of §5.3 (a call in the last 120 seconds). An online count
below the floor is `null`, so a small number never points at a person. `public_projects` and
`cards_done_week` need public pages (§16.9), which this hub does not have yet: `null`.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import clock
from maity_hub import tables as t

TTL = timedelta(minutes=5)
ONLINE = timedelta(seconds=120)
FLOOR = 5

_lock = threading.Lock()
_cached: tuple[datetime, dict[str, Any]] | None = None


def compute(conn: Connection) -> dict[str, Any]:
    now = clock.now()
    people = conn.execute(
        select(func.count()).where(
            t.human.c.account_status == "active", t.human.c.deleted_at.is_(None)
        )
    ).scalar_one()
    agents = conn.execute(
        select(func.count(func.distinct(t.membership.c.agent_id))).where(
            t.membership.c.agent_id.is_not(None), t.membership.c.active.is_(True)
        )
    ).scalar_one()
    people_online = conn.execute(
        select(func.count()).where(
            t.human.c.account_status == "active",
            t.human.c.deleted_at.is_(None),
            t.human.c.last_seen_at >= now - ONLINE,
        )
    ).scalar_one()
    agents_online = conn.execute(
        select(func.count(func.distinct(t.membership.c.agent_id)))
        .select_from(
            t.credential.join(t.membership, t.membership.c.id == t.credential.c.membership_id)
        )
        .where(
            t.membership.c.agent_id.is_not(None),
            t.credential.c.revoked_at.is_(None),
            t.credential.c.last_used_at >= now - ONLINE,
        )
    ).scalar_one()
    return {
        "people": int(people),
        "agents": int(agents),
        "public_projects": None,
        "cards_done_week": None,
        "people_online": int(people_online) if people_online >= FLOOR else None,
        "agents_online": int(agents_online) if agents_online >= FLOOR else None,
        "online_floor": FLOOR,
        "computed_at": clock.rfc3339(now),
    }


def current(conn: Connection) -> dict[str, Any]:
    """The counters, recomputed when the last computation is five minutes old."""
    global _cached
    now = clock.now()
    with _lock:
        if _cached is None or now - _cached[0] >= TTL:
            _cached = (now, compute(conn))
        return dict(_cached[1])


def reset() -> None:
    """Forget the cached counters (tests)."""
    global _cached
    with _lock:
        _cached = None


def named(setting: dict[str, Any]) -> set[str]:
    """The counters an enabled `stats` section of some language names."""
    found: set[str] = set()
    for page in setting["pages"].values():
        for section in page["sections"]:
            if section["type"] == "stats" and section["enabled"]:
                found.update(section["items"])
    return found


def published(conn: Connection, setting: dict[str, Any]) -> dict[str, Any] | None:
    """`stats` of `GET /landing`: only the counters that are named, `None` when none is."""
    names = named(setting)
    if not names:
        return None
    values = current(conn)
    return {
        **{k: v for k, v in values.items() if k in names},
        "online_floor": values["online_floor"],
        "computed_at": values["computed_at"],
    }
