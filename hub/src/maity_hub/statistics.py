"""Instance statistics (docs/api.md §16.6): counts the operator reads to see whether the
instance is used, derived from the tables the hub holds anyway.

Nothing is written and nothing names a person: every series is one grouped query over
existing rows, bucketed by UTC day, and the answer is kept in memory for an hour
(`as_of` says when it was computed). Days without activity are rows of zeros.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.instances import ONLINE_SECONDS

MAX_DAYS, DEFAULT_DAYS = 90, 30
CACHE_FOR = timedelta(hours=1)
SERIES = (
    "registrations",
    "new_instances",
    "humans_active",
    "agents_active",
    "cards_created",
    "cards_claimed",
    "cards_done",
    "reviews",
)


def _day(value: Any) -> str:
    """A `func.date(...)` result as `YYYY-MM-DD`: a string on SQLite, a date elsewhere."""
    return value.isoformat() if isinstance(value, date) else str(value)[:10]


def _start_of(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def compute(conn: Connection, days: int) -> dict[str, Any]:
    """The answer of `GET /admin/statistics?days=N`, computed now."""
    now = clock.now()
    today = now.date()
    window = [today - timedelta(days=n) for n in range(days)]  # newest first
    since = _start_of(window[-1])
    # Activity is read back far enough for `returning` (30 days) whatever the window.
    active_since = min(since, _start_of(today - timedelta(days=29)))
    rows: dict[str, dict[str, int]] = {d.isoformat(): dict.fromkeys(SERIES, 0) for d in window}

    def add(series: str, day: Any, n: int = 1) -> None:
        found = rows.get(_day(day))
        if found is not None:
            found[series] += n

    for day, n in conn.execute(
        select(func.date(t.human.c.registered_at), func.count())
        .where(t.human.c.registered_at >= since)
        .group_by(func.date(t.human.c.registered_at))
    ):
        add("registrations", day, n)

    # An instance's first exchange is its first credential (§3.3, §6.17).
    for (first,) in conn.execute(
        select(func.min(t.credential.c.created_at)).group_by(
            t.credential.c.membership_id, t.credential.c.instance
        )
    ):
        stamp = first if isinstance(first, datetime) else datetime.fromisoformat(str(first))
        if stamp.replace(tzinfo=UTC) >= since:
            add("new_instances", stamp.date())

    humans = _humans_active(conn, active_since)
    for day, members in humans.items():
        add("humans_active", day, len(members))

    for day, n in conn.execute(_agents_active(since)):
        add("agents_active", day, n)

    for day, kind, n in conn.execute(
        select(func.date(t.event.c.at), t.event.c.kind, func.count())
        .where(t.event.c.at >= since, t.event.c.kind.in_(("task_created", "task_claimed")))
        .group_by(func.date(t.event.c.at), t.event.c.kind)
    ):
        add("cards_created" if kind == "task_created" else "cards_claimed", day, n)

    # By `closed_at`, for every way a card closes (§6.6).
    for day, n in conn.execute(
        select(func.date(t.card.c.closed_at), func.count())
        .where(t.card.c.status == "done", t.card.c.closed_at >= since)
        .group_by(func.date(t.card.c.closed_at))
    ):
        add("cards_done", day, n)

    reviews_since = _reviews(conn, since, add) or today
    days_out = []
    for d in window:
        found: dict[str, Any] = {"date": d.isoformat(), **rows[d.isoformat()]}
        if d < reviews_since:  # before the hub kept history it cannot know (§16.6)
            found["reviews"] = None
        days_out.append(found)
    return {
        "as_of": clock.rfc3339(now),
        "window_days": days,
        "totals": _totals(conn, now),
        "days": days_out,
        "returning": _returning(conn, humans, today),
        "coverage": {"reviews_since": reviews_since.isoformat()},
    }


def _reviews(conn: Connection, since: datetime, add: Any) -> date | None:
    """Count the history entries (§6.15) that took a card's `status` from `review` to
    `done` or `in_progress`; a redacted entry is not counted, so the number is a lower
    bound. Returns the first day the hub kept history, or None when it has none yet."""
    first = conn.execute(select(func.min(t.card_history.c.at))).scalar()
    for at, before, after in conn.execute(
        select(t.card_history.c.at, t.card_history.c.before, t.card_history.c.after).where(
            t.card_history.c.field == "status",
            t.card_history.c.at >= since,
            t.card_history.c.redacted.is_(False),
        )
    ):
        if before == "review" and after in ("done", "in_progress"):
            add("reviews", _as_date(at))
    return _as_date(first) if first is not None else None


def _agents_active(since: datetime) -> Any:
    """Agent instances that were the actor of an event, per day: distinct (membership,
    instance) pairs; the long-poll writes no event, so listening alone does not count."""
    pairs = (
        select(
            func.date(t.event.c.at).label("day"),
            t.event.c.actor_membership.label("member"),
            t.credential.c.instance.label("instance"),
        )
        .join(t.credential, t.credential.c.id == t.event.c.actor_credential_id)
        .join(t.membership, t.membership.c.id == t.event.c.actor_membership)
        .where(t.event.c.at >= since, t.membership.c.agent_id.is_not(None))
        .distinct()
        .subquery()
    )
    return select(pairs.c.day, func.count()).group_by(pairs.c.day)


def _humans_active(conn: Connection, since: datetime) -> dict[str, set[str]]:
    """Per day the humans who were the actor of an event or opened a session (§2.1)."""
    found: dict[str, set[str]] = defaultdict(set)
    for day, human in conn.execute(
        select(func.date(t.event.c.at), t.membership.c.human_id)
        .join(t.membership, t.membership.c.id == t.event.c.actor_membership)
        .where(t.event.c.at >= since, t.membership.c.human_id.is_not(None))
        .distinct()
    ):
        found[_day(day)].add(human)
    for day, human in conn.execute(
        select(func.date(t.human_session.c.created_at), t.human_session.c.human_id)
        .where(t.human_session.c.created_at >= since)
        .distinct()
    ):
        found[_day(day)].add(human)
    return found


def _totals(conn: Connection, now: datetime) -> dict[str, int]:
    def count(query: Any) -> int:
        return int(conn.execute(query).scalar_one())

    profiles = select(func.count()).select_from(t.agent_profile)
    if "deleted_at" in t.agent_profile.c:  # a deleted profile is a tombstone (§6.3)
        profiles = profiles.where(t.agent_profile.c.deleted_at.is_(None))
    owners = select(func.count(func.distinct(t.agent_profile.c.owner_id)))
    if "deleted_at" in t.agent_profile.c:
        owners = owners.where(t.agent_profile.c.deleted_at.is_(None))
    alive = t.human.c.deleted_at.is_(None)
    return {
        "humans": count(
            select(func.count())
            .select_from(t.human)
            .where(t.human.c.account_status == "active", alive)
        ),
        "humans_pending": count(
            select(func.count()).select_from(t.human).where(t.human.c.account_status == "pending")
        ),
        "agents": count(profiles),
        "projects": count(
            select(func.count()).select_from(t.project).where(t.project.c.state != "archived")
        ),
        "instances_online": _online(conn, now),
        "humans_with_an_agent": count(owners),
        # The one thing the operator learns of a deletion (§2.9): how many there were.
        "humans_deleted": count(
            select(func.count()).select_from(t.human).where(t.human.c.deleted_at.is_not(None))
        ),
    }


def _online(conn: Connection, now: datetime) -> int:
    """Instances `online` by §6.17: listening now, or a live session used within the
    online window; a paused membership counts as paused, not online."""
    from maity_hub import listening

    found = 0
    rows = conn.execute(
        select(t.agent_session.c.id, t.credential.c.last_used_at)
        .join(t.credential, t.credential.c.id == t.agent_session.c.credential_id)
        .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
        .where(
            t.agent_session.c.live.is_(True),
            t.credential.c.revoked_at.is_(None),
            t.membership.c.active.is_(True),
            t.membership.c.paused_since.is_(None),
        )
    ).all()
    heard = listening.which((row.id for row in rows), conn)  # one read for all
    for row in rows:
        used = row.last_used_at
        recent = used is not None and (now - used).total_seconds() <= ONLINE_SECONDS
        if row.id in heard or recent:
            found += 1
    return found


def _returning(conn: Connection, active: dict[str, set[str]], today: date) -> dict[str, int]:
    """Humans first active 7 (30) or more days ago and active within the last 7 (30)."""
    first: dict[str, date] = {}
    for human, at in conn.execute(
        select(t.membership.c.human_id, func.min(t.event.c.at))
        .join(t.membership, t.membership.c.id == t.event.c.actor_membership)
        .where(t.membership.c.human_id.is_not(None))
        .group_by(t.membership.c.human_id)
    ):
        first[human] = _as_date(at)
    for human, at in conn.execute(
        select(t.human_session.c.human_id, func.min(t.human_session.c.created_at)).group_by(
            t.human_session.c.human_id
        )
    ):
        day = _as_date(at)
        first[human] = min(day, first.get(human, day))
    gone = set(
        conn.execute(select(t.human.c.id).where(t.human.c.deleted_at.is_not(None))).scalars()
    )
    for human in gone:  # a deleted account is not counted (§16.6)
        first.pop(human, None)
    answer = {}
    for span, key in ((7, "after_7_days"), (30, "after_30_days")):
        recent = {
            human
            for n in range(span)
            for human in active.get((today - timedelta(days=n)).isoformat(), set())
        }
        cutoff = today - timedelta(days=span)
        answer[key] = sum(1 for h in recent if h not in gone and first.get(h, today) <= cutoff)
    return answer


def _as_date(value: Any) -> date:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return stamp.date()


class Cache:
    """One computed answer per window size, kept for an hour (§16.6)."""

    def __init__(self) -> None:
        self._kept: dict[int, tuple[datetime, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, conn: Connection, days: int) -> dict[str, Any]:
        now = clock.now()
        with self._lock:
            kept = self._kept.get(days)
            if kept is not None and now - kept[0] < CACHE_FOR:
                return kept[1]
        answer = compute(conn, days)
        with self._lock:
            self._kept[days] = (now, answer)
        return answer

    def clear(self) -> None:
        with self._lock:
            self._kept.clear()


CACHE = Cache()
