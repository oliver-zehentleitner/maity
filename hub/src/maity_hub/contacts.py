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

from maity_hub import clock, handles, write_guard
from maity_hub import tables as t
from maity_hub.errors import ApiError, not_found
from maity_hub.ratelimit import Limiter
from maity_hub.views import ts

PER_DAY = 100
DAY = 24 * 3600
ADDED = Limiter(PER_DAY, DAY, name="contacts.ADDED")  # new contacts per human

CONTACTS = "contacts"  # whom the human has added: who may contact them
CONTACT_OF = "contact_of"  # who has the human as a contact: whom they may contact


def target(conn: Connection, me: str, handle: str, *, active: bool) -> str:
    """The human `handle` names (a live alias too, §6.24), for a change of `me`'s contacts in
    this transaction. An approved, active account, as `GET /people` answers (§6.27); with
    `active` false (a removal) also a suspended or pending one, but only when it is one of
    `me`'s contacts, so that the one person who added it can always remove it and nobody
    else learns that the account is not active (#1532 review). Every other case is
    `not_found`, except an organisation's live handle (`not_a_person`) and the caller (`self`).

    The person's `account_lock` is taken shared before their row is read, in the order every
    human transaction takes it (`write_guard`): a deletion of that account either waits for
    this transaction, and its cleanup then removes the contact, or has committed, and the
    row read here says deleted. A check without the lock would let an insert land after the
    deletion's cleanup (#1532 review)."""
    human_id = handles.human_id_of(conn, handle)
    if human_id is None:
        org_id = handles.org_id_of(conn, handle)
        org = (
            None
            if org_id is None
            else conn.execute(select(t.org.c.deleted_at).where(t.org.c.id == org_id)).first()
        )
        if org is not None and org.deleted_at is None:  # a deleted one is `not_found`, as GET
            raise ApiError(
                400, "invalid", "only a person can be a contact", {"reason": "not_a_person"}
            )
        raise not_found()
    if human_id == me:
        raise ApiError(400, "invalid", "you cannot be your own contact", {"reason": "self"})
    write_guard.share(conn, human_id)
    human = conn.execute(
        select(t.human.c.deleted_at, t.human.c.suspended_at, t.human.c.account_status).where(
            t.human.c.id == human_id
        )
    ).first()
    if human is None or human.deleted_at is not None:
        raise not_found()
    shown = human.suspended_at is None and human.account_status == "active"
    if not shown and (active or not has(conn, me, human_id)):
        raise not_found()
    return human_id


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
