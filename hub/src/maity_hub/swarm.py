"""The swarm page (docs/api.md §6.22): who is at work now, and what the project got done.

Everything is derived from rows the hub keeps for its own work, on request, and never
stored: `live` is read at the moment of the call; the window part (`members`, `totals`)
is gathered once per project for the longest window, 90 days, kept for up to an hour, and
cut to each reader's `days`. Where the evidence is gone, a counter is
a lower bound, never a guess.

The window part is computed once as raw facts per card and member, then folded for the
reader: in full for members, over agents only for the public page, so that a human's
contribution appears nowhere there.
"""

from __future__ import annotations

import re
import statistics
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import bounded, clock
from maity_hub import tables as t

CACHE_SECONDS = 3600  # the window part, per project (§6.22)
MAX_DAYS = 90  # every page is cut from this one window
MIN_SAMPLES = 3  # a median needs at least three durations
REVIEWED = ("done", "in_progress")  # a status entry out of `review` into these is a review
PULL = re.compile(r"https?://([^/]+)/([^/]+)/([^/]+)/pulls?/(\d+)", re.IGNORECASE)


# --- the raw facts of a window --------------------------------------------------------------


@dataclass
class Window:
    """What happened in the last `MAX_DAYS` days, each fact with its UTC day, before it is
    cut to a reader's `days` and folded for the reader."""

    as_of: datetime
    reviews_since: date | None  # the first day the hub kept card history (§16.6)
    done: list[tuple[int | None, date]] = field(default_factory=list)  # (holder, day)
    reviews: list[tuple[int, date]] = field(default_factory=list)  # (reviewer or -1, day)
    prs: list[tuple[set[int], date]] = field(default_factory=list)  # (its members, day)
    handovers: list[tuple[int, date]] = field(default_factory=list)  # (moved from, day)
    claim_to_done: list[tuple[int | None, int, date]] = field(default_factory=list)
    review_to_done: list[tuple[int | None, int, date]] = field(default_factory=list)


def _day(value: datetime) -> date:
    return value.astimezone(UTC).date()


def _start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


_first_history: list[date] = []  # once the hub keeps history, its first day never moves


def _reviews_since(conn: Connection) -> date | None:
    if not _first_history:
        first = conn.execute(select(func.min(t.card_history.c.at))).scalar()
        if first is None:
            return None
        _first_history.append(_day(first))
    return _first_history[0]


def window(conn: Connection, project_id: str) -> Window:
    now = clock.now()
    since = _start(_day(now) - timedelta(days=MAX_DAYS - 1))
    found = Window(as_of=now, reviews_since=_reviews_since(conn))
    active = set(
        conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id, t.membership.c.active.is_(True)
            )
        ).scalars()
    )

    def member(membership_id: int | None) -> int | None:
        return membership_id if membership_id in active else None

    closed = list(
        conn.execute(
            select(t.card.c.id, t.card.c.claim_holder, t.card.c.closed_at).where(
                t.card.c.project_id == project_id,
                t.card.c.status == "done",
                t.card.c.closed_at >= since,
            )
        )
    )
    holder_of = {c.id: member(c.claim_holder) for c in closed}
    for card in closed:
        found.done.append((holder_of[card.id], _day(card.closed_at)))
    _reviews(conn, project_id, since, member, found)
    _prs(conn, project_id, since, member, found)
    _durations(conn, project_id, closed, holder_of, found)
    return found


def _reviews(
    conn: Connection, project_id: str, since: datetime, member: Any, found: Window
) -> None:
    """History entries only (§6.15): a report, a refresh or a self-done close is none; a
    redacted entry is not counted."""
    for actor, at, before, after in conn.execute(
        select(
            t.card_history.c.actor_membership,
            t.card_history.c.at,
            t.card_history.c.before,
            t.card_history.c.after,
        )
        .join(t.card, t.card.c.id == t.card_history.c.card_id)
        .where(
            t.card.c.project_id == project_id,
            t.card_history.c.field == "status",
            t.card_history.c.at >= since,
            t.card_history.c.redacted.is_(False),
        )
    ):
        if before == "review" and after in REVIEWED:
            reviewer = member(actor)
            # Without a member it counts in the totals and in no member's row.
            found.reviews.append((reviewer if reviewer is not None else -1, _day(at)))


def pull_key(url: Any) -> str:
    """A pull request as repository and number, read from its forge URL, so that one PR is
    one key whichever link or card names it."""
    match = PULL.match(str(url or ""))
    if match is None:
        return str(url)
    host, owner, name, number = match.groups()
    return f"{host.lower()}/{owner.lower()}/{name.lower()}#{int(number)}"


def _prs(conn: Connection, project_id: str, since: datetime, member: Any, found: Window) -> None:
    """Pull requests by their first retained `link_observed` to `merged` (§6.13), deduplicated
    by repository and number across links and cards; a merge seen before the hub kept those
    events is not counted. Each member holding a card that links it gets it once."""
    first: dict[str, datetime] = {}
    cards: dict[str, set[str]] = {}
    for at, payload in conn.execute(
        select(t.event.c.at, t.event.c.payload)
        .where(t.event.c.project_id == project_id, t.event.c.kind == "link_observed")
        .order_by(t.event.c.seq)
    ):
        payload = payload or {}
        # Only what a read found public reaches this page without sign-in (§11.4); an
        # event from before the field was written counts as not public.
        if payload.get("public") is not True:
            continue
        if (payload.get("new") or {}).get("state") != "merged":
            continue
        key = pull_key(payload.get("forge_url"))
        first.setdefault(key, at)
        cards.setdefault(key, set()).add(str(payload.get("task_id")))
    holders = (
        dict(
            conn.execute(
                select(t.card.c.id, t.card.c.claim_holder).where(
                    t.card.c.id.in_({c for ids in cards.values() for c in ids if c})
                )
            ).all()
        )
        if cards
        else {}
    )
    for key, at in first.items():
        if at >= since:
            members = {m for m in (member(holders.get(c)) for c in cards[key]) if m}
            found.prs.append((members, _day(at)))


def _durations(
    conn: Connection,
    project_id: str,
    closed: list[Any],
    holder_of: dict[str, int | None],
    found: Window,
) -> None:
    """Pooled samples per card closed `done` in the window: its last claim to `closed_at`,
    and its last entry into `review` to `closed_at`. The entry is a `task_reported` with
    `status_after: review` from a status other than `review`, or a history entry into
    `review`; an older report without the status fields proves nothing and gives none."""
    if not closed:
        return
    ids = [c.id for c in closed]
    claimed: dict[str, datetime] = {}
    entered: dict[str, datetime] = {}
    for kind, subject, at, payload in conn.execute(
        select(t.event.c.kind, t.event.c.subject_id, t.event.c.at, t.event.c.payload).where(
            t.event.c.project_id == project_id,
            t.event.c.subject_type == "task",
            t.event.c.subject_id.in_(ids),
            t.event.c.kind.in_(("task_claimed", "task_reported")),
            t.event.c.redacted.is_(False),
        )
    ):
        if kind == "task_claimed":
            claimed[subject] = max(at, claimed.get(subject, at))
            continue
        payload = payload or {}
        before, after = payload.get("status_before"), payload.get("status_after")
        if after == "review" and before is not None and before != "review":
            entered[subject] = max(at, entered.get(subject, at))
    # `after` is a JSON value: compared here, as `_reviews` does, not in SQL.
    for card_id, at, after in conn.execute(
        select(t.card_history.c.card_id, t.card_history.c.at, t.card_history.c.after).where(
            t.card_history.c.card_id.in_(ids),
            t.card_history.c.field == "status",
            t.card_history.c.redacted.is_(False),
        )
    ):
        if after == "review":
            entered[card_id] = max(at, entered.get(card_id, at))
    for card in closed:
        holder, day = holder_of[card.id], _day(card.closed_at)
        if card.id in claimed and claimed[card.id] <= card.closed_at:
            seconds = int((card.closed_at - claimed[card.id]).total_seconds())
            found.claim_to_done.append((holder, seconds, day))
        if card.id in entered and entered[card.id] < card.closed_at:
            seconds = int((card.closed_at - entered[card.id]).total_seconds())
            found.review_to_done.append((holder, seconds, day))


# --- folding for a reader --------------------------------------------------------------------


def _median(values: list[int]) -> int | None:
    return int(statistics.median(values)) if len(values) >= MIN_SAMPLES else None


def fold(
    found: Window, members: dict[int, dict[str, Any]], *, days: int, include: Any
) -> dict[str, Any]:
    """`members` and `totals` over the last `days` days of the window and the memberships
    `include` admits; a contribution without a member (no holder, a holder gone) counts in
    the totals only when `include` admits `None`."""
    today = _day(found.as_of)
    shown = [today - timedelta(days=n) for n in range(days - 1, -1, -1)]
    cut = shown[0]
    reviews_known = found.reviews_since is not None
    done = [(m, d) for m, d in found.done if d >= cut]
    reviews = [(None if m == -1 else m) for m, d in found.reviews if d >= cut]
    prs = [ms for ms, d in found.prs if d >= cut]
    handovers = [m for m, d in found.handovers if d >= cut]
    claim = [(m, s) for m, s, d in found.claim_to_done if d >= cut]
    review = [(m, s) for m, s, d in found.review_to_done if d >= cut]

    def counts(of: int | None) -> dict[str, Any]:
        def mine(value: int | None) -> bool:
            return value == of if of is not None else include(value)

        return {
            "cards_done": sum(1 for m, _ in done if mine(m)),
            "reviews_given": sum(1 for m in reviews if mine(m)) if reviews_known else None,
            "prs_merged": sum(
                1 for ms in prs if (of in ms if of is not None else _any(ms, include))
            ),
            "handovers": sum(1 for m in handovers if mine(m)),
            "claim_to_done_median_seconds": _median([s for m, s in claim if mine(m)]),
            "review_to_done_median_seconds": (
                _median([s for m, s in review if mine(m)]) if reviews_known else None
            ),
        }

    rows = [
        {**person, **counts(membership_id)}
        for membership_id, person in members.items()
        if include(membership_id)
    ]
    per_day = {d: 0 for d in shown}
    for m, day in done:
        if include(m):
            per_day[day] += 1
    totals = counts(None)
    totals["cards_done_per_day"] = [{"date": d.isoformat(), "count": n} for d, n in per_day.items()]
    return {
        "as_of": clock.rfc3339(found.as_of),
        "window_days": days,
        "members": rows,
        "totals": totals,
        "coverage": {
            "reviews_since": found.reviews_since.isoformat() if found.reviews_since else None
        },
    }


def _any(members: set[int], include: Any) -> bool:
    return any(include(m) for m in members) or (not members and include(None))


# --- the cache -------------------------------------------------------------------------------


PROJECTS_KEPT = 1024  # the windows kept; an older one is gathered anew on its next view


class _Cache:
    """The window part, one per project, for at most `CACHE_SECONDS` and never past the
    end of its UTC day, so that a new day has its row from its first minute."""

    def __init__(self) -> None:
        self._kept: OrderedDict[str, Window] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, conn: Connection, project_id: str) -> Window:
        now = clock.now()
        with self._lock:
            kept = self._kept.get(project_id)
        if (
            kept is not None
            and (now - kept.as_of).total_seconds() < CACHE_SECONDS
            and _day(kept.as_of) == _day(now)
        ):
            return kept
        fresh = window(conn, project_id)
        with self._lock:
            bounded.put(self._kept, project_id, fresh, PROJECTS_KEPT)
        return fresh

    def clear(self) -> None:
        with self._lock:
            self._kept.clear()
        _first_history.clear()


CACHE = _Cache()
