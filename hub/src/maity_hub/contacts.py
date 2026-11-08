"""A human's contacts (docs/api.md §6.29).

Adding someone to one's contacts is consent that they may contact one, one way; the sections
that use it say what it allows. It is private to the two: no event, no notification, no count.
A row lives until its human removes it or either account is deleted; a suspension leaves it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, delete, insert, or_, select
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.ratelimit import Limiter
from maity_hub.views import ts

PER_DAY = 100
DAY = 24 * 3600
ADDED = Limiter(PER_DAY, DAY, name="contacts.ADDED")  # new contacts per human

CONTACTS = "contacts"  # whom the human has added: who may contact them
CONTACT_OF = "contact_of"  # who has the human as a contact: whom they may contact


def has(conn: Connection, human_id: str, contact_id: str) -> bool:
    """Whether `contact_id` is one of `human_id`'s contacts."""
    c = t.contact.c
    found = conn.execute(
        select(c.since).where(c.human_id == human_id, c.contact_id == contact_id)
    ).first()
    return found is not None


def add(conn: Connection, human_id: str, contact_id: str) -> bool:
    """Add the contact inside the caller's transaction; False when it was there already."""
    if has(conn, human_id, contact_id):
        return False
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.contact).values(
                    human_id=human_id, contact_id=contact_id, since=clock.now()
                )
            )
    except IntegrityError:
        return False  # a concurrent call added it
    return True


def remove(conn: Connection, human_id: str, contact_id: str) -> None:
    c = t.contact.c
    conn.execute(delete(t.contact).where(c.human_id == human_id, c.contact_id == contact_id))


def forget(conn: Connection, human_id: str) -> None:
    """Every contact of a deleted account, both ways (§2.9)."""
    c = t.contact.c
    conn.execute(delete(t.contact).where(or_(c.human_id == human_id, c.contact_id == human_id)))


def _sides(side: str) -> tuple[Any, Any]:
    """(the caller's column, the other person's column) for `side`."""
    c = t.contact.c
    return (c.human_id, c.contact_id) if side == CONTACTS else (c.contact_id, c.human_id)


def page(
    conn: Connection, human_id: str, side: str, limit: int, after: tuple[datetime, str] | None
) -> list[Any]:
    """One page of `side`, newest first by (since, the other's id): up to `limit + 1` rows with
    `since`, `other_id`, `handle` and `display_name`. Accounts that are suspended or waiting for
    approval are left out while they are (§6.29); a deleted one has no rows left."""
    mine, other = _sides(side)
    since = t.contact.c.since
    h = t.human.c
    query = (
        select(since, other.label("other_id"), h.handle, h.display_name)
        .join(t.human, h.id == other)
        .where(
            mine == human_id,
            h.deleted_at.is_(None),
            h.suspended_at.is_(None),
            h.account_status == "active",
        )
    )
    if after is not None:
        at, after_id = after
        query = query.where((since < at) | ((since == at) & (other < after_id)))
    return list(conn.execute(query.order_by(since.desc(), other.desc()).limit(limit + 1)).all())


def exported(conn: Connection, human_id: str) -> dict[str, list[dict[str, Any]]]:
    """The caller's side of each contact for the export (§2.9): handle and `since`, oldest
    first, whatever the other account's state."""
    h = t.human.c
    out: dict[str, list[dict[str, Any]]] = {}
    for side in (CONTACTS, CONTACT_OF):
        mine, other = _sides(side)
        since = t.contact.c.since
        rows = conn.execute(
            select(h.handle, since)
            .join(t.human, h.id == other)
            .where(mine == human_id)
            .order_by(since, h.handle)
        ).all()
        out[side] = [{"handle": r.handle, "since": ts(r.since)} for r in rows]
    return out
