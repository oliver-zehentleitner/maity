"""A card's edit history (docs/api.md §6.15): one entry per field a member changed.

`record` is the one call a write path makes: it compares the card as it was with what
the write changed and stores an entry per recorded field, whole values on both sides
and a unified diff for `title` and `body`. `stamp` then ties the entries to the event
the write emitted, so that redacting an entry redacts the same values there. Changes
the hub makes on its own (rank, a request's block, a claim, a report, an observation)
are events only.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.events import Actor
from maity_hub.ids import new_id

# The card columns a member's write changes that the history records.
RECORDED = ("title", "body", "label", "area", "status", "assigned_to", "ktw_ref")
DIFFED = ("title", "body")


def diff(before: str | None, after: str | None) -> str:
    """A unified diff without file headers."""
    lines = list(
        difflib.unified_diff(
            (before or "").splitlines(), (after or "").splitlines(), lineterm="", n=1
        )
    )
    # The two file headers come first, by position; a content line may start with
    # "--" or "++" itself and stays.
    return "\n".join(lines[2:])


def _entry(
    conn: Connection, card_id: str, field: str, before: Any, after: Any, actor: Actor, at: Any
) -> str:
    entry_id = new_id("history")
    link = (after or before) if field == "links" else None
    change = ("added" if after else "removed") if link else None
    conn.execute(
        insert(t.card_history).values(
            id=entry_id,
            card_id=card_id,
            at=at,
            actor_membership=actor.membership_id,
            actor_session_id=actor.session_id,
            field=field,
            link_id=link["id"] if link else None,
            link_change=change,
            before=before,
            after=after,
            diff=diff(before, after) if field in DIFFED else None,
            redacted=False,
        )
    )
    return entry_id


def record(
    conn: Connection,
    before: Any,
    changed: dict[str, Any],
    actor: Actor,
    *,
    shown: dict[str, tuple[Any, Any]] | None = None,
    extra: Iterable[tuple[str, Any, Any]] = (),
) -> list[str]:
    """An entry per recorded column in `changed` (the card row as it was in `before`)
    and per `(field, before, after)` in `extra` (edges, `contract.state`, links), all
    with the same `at`. `shown` gives `(before, after)` as the history shows a column
    whose stored value is not the shown one (a member id for `assigned_to`)."""
    at = clock.now()
    shown = shown or {}
    ids = [
        _entry(
            conn,
            before.id,
            field,
            *shown.get(field, (getattr(before, field), changed[field])),
            actor,
            at,
        )
        for field in RECORDED
        if field in changed
    ]
    ids += [_entry(conn, before.id, field, old, new, actor, at) for field, old, new in extra]
    return ids


def created(conn: Connection, card_id: str, fields: dict[str, Any], actor: Actor) -> str:
    """The one entry for a card's creation: `before: null`, `after` its fields."""
    return _entry(conn, card_id, "created", None, fields, actor, clock.now())


def stamp(conn: Connection, entry_ids: Sequence[str], seq: int) -> None:
    """The event that carried these entries' values (`history` in its payload)."""
    if entry_ids:
        conn.execute(
            update(t.card_history)
            .where(t.card_history.c.id.in_(list(entry_ids)))
            .values(event_seq=seq)
        )


# --- reading ---------------------------------------------------------------------------------


def members(conn: Connection, membership_ids: Iterable[int | None]) -> dict[int, dict[str, Any]]:
    """`{member_id, handle, kind}` per membership row: an entry's actor without its
    session, a note's author."""
    ids = {i for i in membership_ids if i is not None}
    if not ids:
        return {}
    found = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.agent_id,
            t.membership.c.human_id,
            t.agent_profile.c.handle.label("agent_handle"),
            t.human.c.handle.label("human_handle"),
        )
        .select_from(t.membership)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .outerjoin(t.human, t.human.c.id == t.membership.c.human_id)
        .where(t.membership.c.id.in_(ids))
    ).all()
    return {
        row.id: {
            "member_id": row.agent_id or row.human_id,
            "handle": row.agent_handle or row.human_handle,
            "kind": "agent" if row.agent_id else "human",
        }
        for row in found
    }


def view(row: Any, actors: dict[int, dict[str, Any]]) -> dict[str, Any]:
    actor = actors.get(row.actor_membership) if row.actor_membership is not None else None
    shown: dict[str, Any] = {
        "id": row.id,
        "at": clock.rfc3339(row.at),
        "actor": {**actor, "session_id": row.actor_session_id} if actor else None,
        "field": row.field,
    }
    if row.redacted:
        shown.update(before=row.redaction, after=row.redaction, diff=row.redaction)
        shown["redacted"] = True
    else:
        shown.update(before=row.before, after=row.after, diff=row.diff)
    return shown


# --- redaction -------------------------------------------------------------------------------

# What a task event keeps whatever is redacted: which card, fields, entries, the state.
_EVENT_KEEPS = frozenset({"id", "fields", "history", "project_state", "reason"})
# A history field whose value travels in the event under another key.
_EVENT_KEY = {"contract.state": "contract"}


def tombstone(reason: str, by: str) -> dict[str, Any]:
    """§8.5's tombstone."""
    return {"redacted": True, "reason": reason, "by": by, "at": clock.rfc3339(clock.now())}


def redact(conn: Connection, row: Any, mark: dict[str, Any]) -> bool:
    """Tombstone one entry, and the same field values in the event of its write. One
    conditional UPDATE decides between two redactions at once: only the winner writes
    the event's values, and only it announces (it returns True)."""
    won = conn.execute(
        update(t.card_history)
        .where(t.card_history.c.id == row.id, t.card_history.c.redacted.is_(False))
        .values(before=None, after=None, diff=None, redacted=True, redaction=mark)
    ).rowcount
    if won != 1:
        return False
    if row.event_seq is None:
        return True
    event = conn.execute(select(t.event).where(t.event.c.seq == row.event_seq)).first()
    if event is None or event.redacted:
        return True
    payload = dict(event.payload)
    if row.field == "created":
        names = [k for k in payload if k not in _EVENT_KEEPS]
    else:
        names = [_EVENT_KEY.get(row.field, row.field)]
    for name in names:
        if name in payload:
            payload[name] = mark
    conn.execute(update(t.event).where(t.event.c.seq == event.seq).values(payload=payload))
    return True


def link_entry(conn: Connection, card_id: str, link_id: str, removed: bool) -> Any | None:
    """The entry that added a link of the card through `POST …/links`, or with `removed`
    the one that removed it; a link the card was created with has no add entry of its
    own (it is in the `created` entry). Found by the stored change, redacted or not."""
    c = t.card_history.c
    return conn.execute(
        select(t.card_history)
        .where(
            c.card_id == card_id,
            c.field == "links",
            c.link_id == link_id,
            c.link_change == ("removed" if removed else "added"),
        )
        .order_by(c.at.desc(), c.id.desc())
    ).first()


def link_shown(row: Any) -> dict[str, Any]:
    """The link as its entry holds it, or the tombstone once the entry is redacted."""
    shown: dict[str, Any] = row.redaction if row.redacted else (row.after or row.before)
    return shown
