"""Notes on a card (docs/api.md §6.16): remarks that never change the card.

A note is posted, then resolved (`incorporated`, `dismissed`) or redacted; never edited
or deleted. A card holds at most 50 open notes and 200 in all, of which agents may post
150, so that the last places stay for humans (`context/cards.md`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, func, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.ratelimit import Limiter

STATES = ("open", "incorporated", "dismissed")
RESOLVED = ("incorporated", "dismissed")
BODY_MAX = 4096  # bytes of UTF-8
OPEN_MAX = 50
TOTAL_MAX = 200
AGENTS_MAX = 150
# 20 notes per membership in 10 minutes; in process, like the other limits of one replica.
POSTED = Limiter(20, 600, name="board.notes.POSTED")


def over_cap(*, open_count: int, total: int, by_agents: int, author_is_agent: bool) -> bool:
    """Whether one more note breaks a cap: the open cap, the total, or the agents' share."""
    if open_count >= OPEN_MAX or total >= TOTAL_MAX:
        return True
    return author_is_agent and by_agents >= AGENTS_MAX


def counts(conn: Connection, card_id: str) -> tuple[int, int, int]:
    """(open, total, posted by agents) of one card."""
    c = t.card_note.c
    open_count = total = by_agents = 0
    for state, kind, n in conn.execute(
        select(c.state, c.author_kind, func.count())
        .where(c.card_id == card_id)
        .group_by(c.state, c.author_kind)
    ):
        total += int(n)
        open_count += int(n) if state == "open" else 0
        by_agents += int(n) if kind == "agent" else 0
    return open_count, total, by_agents


def counts_of(conn: Connection, card_ids: Iterable[str]) -> dict[str, dict[str, int]]:
    """`notes: {open, total}` of several cards in one grouped query."""
    wanted = list(dict.fromkeys(card_ids))
    found = {card_id: {"open": 0, "total": 0} for card_id in wanted}
    if not wanted:
        return found
    c = t.card_note.c
    for card_id, state, n in conn.execute(
        select(c.card_id, c.state, func.count())
        .where(c.card_id.in_(wanted))
        .group_by(c.card_id, c.state)
    ):
        found[card_id]["total"] += int(n)
        if state == "open":
            found[card_id]["open"] += int(n)
    return found


def view(row: Any, authors: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """A note as §6.16 shows it; `authors` from `history.members`."""
    return {
        "id": row.id,
        "task_id": row.card_id,
        "author": authors[row.author],
        "body": row.redaction if row.redacted else row.body,
        "mentions": [] if row.redacted else (row.mentions or []),
        "state": row.state,
        "resolution": row.resolution,
        "created_at": clock.rfc3339(row.created_at),
        **({"redacted": True} if row.redacted else {}),
    }


def redact(conn: Connection, row: Any, mark: dict[str, Any]) -> bool:
    """Tombstone the body, empty the mentions, and redact the note's `note_added` the
    same way. Only the one redaction that wins the conditional UPDATE announces."""
    won = conn.execute(
        update(t.card_note)
        .where(t.card_note.c.id == row.id, t.card_note.c.redacted.is_(False))
        .values(body=None, mentions=[], redacted=True, redaction=mark)
    ).rowcount
    if won != 1:
        return False
    if row.event_seq is not None:
        event = conn.execute(select(t.event).where(t.event.c.seq == row.event_seq)).first()
        if event is not None and not event.redacted:
            payload = dict(event.payload)
            note = dict(payload.get("note") or {})
            note.update(body=mark, mentions=[])
            payload["note"] = note
            conn.execute(update(t.event).where(t.event.c.seq == event.seq).values(payload=payload))
    return True
