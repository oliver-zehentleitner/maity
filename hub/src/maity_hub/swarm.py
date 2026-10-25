"""The swarm page (docs/api.md §6.22): who is at work now, and what the project got done.

Everything is derived from rows the hub keeps for its own work, on request, and never
stored: `live` is read at the moment of the call; the window part (`members`, `totals`)
may be kept for an hour per project and `days`. Where the evidence is gone, a counter is
a lower bound, never a guess.

The window part is computed once as raw facts per card and member, then folded for the
reader: in full for members, over agents only for the public page, so that a human's
contribution appears nowhere there.
"""

from __future__ import annotations

import statistics
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock
from maity_hub import tables as t

CACHE_SECONDS = 3600  # the window part, per project and `days` (§6.22)
MIN_SAMPLES = 3  # a median needs at least three durations
REVIEWED = ("done", "in_progress")  # a status entry out of `review` into these is a review


# --- the raw facts of a window --------------------------------------------------------------


@dataclass
class Window:
    """What happened in the window, before it is folded for a reader."""

    days: list[date]
    as_of: datetime
    reviews_since: date | None  # the first day the hub kept card history (§16.6)
    done: list[tuple[int | None, date]] = field(default_factory=list)  # (holder, day)
    reviews: list[int] = field(default_factory=list)  # the reviewer per review
    prs: list[set[int]] = field(default_factory=list)  # per merged PR, its members
    handovers: list[int] = field(default_factory=list)  # the member a card moved from
    claim_to_done: list[tuple[int | None, int]] = field(default_factory=list)
    review_to_done: list[tuple[int | None, int]] = field(default_factory=list)


def _day(value: datetime) -> date:
    return value.astimezone(UTC).date()


def _start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def window(conn: Connection, project_id: str, days: int) -> Window:
    now = clock.now()
    today = _day(now)
    first = today - timedelta(days=days - 1)
    since = _start(first)
    first_history = conn.execute(
        select(t.card_history.c.at).order_by(t.card_history.c.at).limit(1)
    ).scalar()
    found = Window(
        days=[first + timedelta(days=n) for n in range(days)],
        as_of=now,
        reviews_since=_day(first_history) if first_history is not None else None,
    )
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
    for actor, before, after in conn.execute(
        select(t.card_history.c.actor_membership, t.card_history.c.before, t.card_history.c.after)
        .join(t.card, t.card.c.id == t.card_history.c.card_id)
        .where(
            t.card.c.project_id == project_id,
            t.card_history.c.field == "status",
            t.card_history.c.at >= since,
            t.card_history.c.redacted.is_(False),
        )
    ):
        reviewer = member(actor)
        if before == "review" and after in REVIEWED and reviewer is not None:
            found.reviews.append(reviewer)
        elif before == "review" and after in REVIEWED:
            found.reviews.append(-1)  # in the totals, in no member's row


def _prs(conn: Connection, project_id: str, since: datetime, member: Any, found: Window) -> None:
    """Pull requests by their first retained `link_observed` to `merged` (§6.13), deduplicated
    by repository and number across links and cards; a merge seen before the hub kept those
    events is not counted. Each member holding a card that links it gets it once."""
    links = {
        row.id: row
        for row in conn.execute(
            select(t.card_link.c.id, t.card_link.c.repository, t.card_link.c.number)
            .join(t.card, t.card.c.id == t.card_link.c.card_id)
            .where(t.card.c.project_id == project_id)
        )
    }
    first: dict[str, datetime] = {}
    cards: dict[str, set[str]] = {}
    for at, payload in conn.execute(
        select(t.event.c.at, t.event.c.payload)
        .where(t.event.c.project_id == project_id, t.event.c.kind == "link_observed")
        .order_by(t.event.c.seq)
    ):
        payload = payload or {}
        if (payload.get("new") or {}).get("state") != "merged":
            continue
        link = links.get(payload.get("link_id"))
        key = (
            f"{link.repository}#{link.number}"
            if link is not None and link.repository and link.number is not None
            else str(payload.get("forge_url"))
        )
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
        if at < since:
            continue
        found.prs.append({m for m in (member(holders.get(c)) for c in cards[key]) if m})


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
    for card_id, at in conn.execute(
        select(t.card_history.c.card_id, t.card_history.c.at).where(
            t.card_history.c.card_id.in_(ids),
            t.card_history.c.field == "status",
            t.card_history.c.after == "review",
            t.card_history.c.redacted.is_(False),
        )
    ):
        entered[card_id] = max(at, entered.get(card_id, at))
    for card in closed:
        holder = holder_of[card.id]
        if card.id in claimed and claimed[card.id] <= card.closed_at:
            found.claim_to_done.append(
                (holder, int((card.closed_at - claimed[card.id]).total_seconds()))
            )
        if card.id in entered and entered[card.id] < card.closed_at:
            found.review_to_done.append(
                (holder, int((card.closed_at - entered[card.id]).total_seconds()))
            )


# --- folding for a reader --------------------------------------------------------------------


def _median(values: list[int]) -> int | None:
    return int(statistics.median(values)) if len(values) >= MIN_SAMPLES else None


def fold(found: Window, members: dict[int, dict[str, Any]], *, include: Any) -> dict[str, Any]:
    """`members` and `totals` over the memberships `include` admits; a contribution
    without a member (no holder, a holder gone) counts in the totals only when `include`
    admits `None`."""
    reviews_known = found.reviews_since is not None

    def counts(of: int | None) -> dict[str, Any]:
        def mine(value: int | None) -> bool:
            return value == of if of is not None else include(value)

        review_samples = [s for m, s in found.review_to_done if mine(m)]
        return {
            "cards_done": sum(1 for m, _ in found.done if mine(m)),
            "reviews_given": (
                sum(1 for m in found.reviews if mine(None if m == -1 else m))
                if reviews_known
                else None
            ),
            "prs_merged": sum(
                1 for ms in found.prs if (of in ms if of is not None else _any(ms, include))
            ),
            "handovers": sum(1 for m in found.handovers if mine(m)),
            "claim_to_done_median_seconds": _median([s for m, s in found.claim_to_done if mine(m)]),
            "review_to_done_median_seconds": _median(review_samples) if reviews_known else None,
        }

    rows = [
        {**person, **counts(membership_id)}
        for membership_id, person in members.items()
        if include(membership_id)
    ]
    per_day = {d: 0 for d in found.days}
    for m, day in found.done:
        if include(m) and day in per_day:
            per_day[day] += 1
    totals = counts(None)
    totals["cards_done_per_day"] = [{"date": d.isoformat(), "count": n} for d, n in per_day.items()]
    return {
        "as_of": clock.rfc3339(found.as_of),
        "window_days": len(found.days),
        "members": rows,
        "totals": totals,
        "coverage": {
            "reviews_since": found.reviews_since.isoformat() if found.reviews_since else None
        },
    }


def _any(members: set[int], include: Any) -> bool:
    return any(include(m) for m in members) or (not members and include(None))


# --- the cache -------------------------------------------------------------------------------


class _Cache:
    """The window part, per project and `days`, for at most `CACHE_SECONDS`."""

    def __init__(self) -> None:
        self._kept: dict[tuple[str, int], Window] = {}
        self._lock = threading.Lock()

    def get(self, conn: Connection, project_id: str, days: int) -> Window:
        key = (project_id, days)
        with self._lock:
            kept = self._kept.get(key)
        if kept is not None and (clock.now() - kept.as_of).total_seconds() < CACHE_SECONDS:
            return kept
        fresh = window(conn, project_id, days)
        with self._lock:
            self._kept[key] = fresh
        return fresh

    def clear(self) -> None:
        with self._lock:
            self._kept.clear()


CACHE = _Cache()
