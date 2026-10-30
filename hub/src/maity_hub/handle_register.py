"""The one namespace of current handles (docs/api.md §6.24, §6.26): a human's and an
organisation's. Agent profiles are not in it, their handles are unique only per owner.

The primary key of `handle_register` is what keeps two principals from one handle, under
any race and on every engine; the callers below only turn the violation into an answer.
A row is never deleted: the handle of a deleted account or organisation stays taken, so an
old link and an old project name never come to mean someone else (§2.9, §6.26).
"""

from __future__ import annotations

from sqlalchemy import Connection, insert, select
from sqlalchemy.exc import IntegrityError

from maity_hub import tables as t

HUMAN, ORG = "human", "org"


def taken(conn: Connection, handle: str) -> bool:
    return (
        conn.execute(
            select(t.handle_register.c.handle).where(t.handle_register.c.handle == handle)
        ).first()
        is not None
    )


def claim(conn: Connection, handle: str, kind: str, owner_id: str) -> bool:
    """Enter `handle` for `owner_id`; False when another principal holds it. The insert
    runs in a savepoint, so a loser leaves the caller's transaction usable."""
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.handle_register).values(handle=handle, kind=kind, owner_id=owner_id)
            )
    except IntegrityError:
        if taken(conn, handle):
            return False
        raise  # not the handle: the owner has an entry already, which is a bug of the caller
    return True
