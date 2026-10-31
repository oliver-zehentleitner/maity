"""No write of a deleted account commits (docs/api.md §2.9, "ends access at once").

A call authenticates in a transaction of its own (`deps._resolve`) and works in later
ones, so an account deleted in between would otherwise still get its write: a profile,
a runner, a project created after the deletion committed. Every transaction of a human
caller therefore passes one check, wherever it is opened: before its first locking
statement (a write, or a `SELECT … FOR UPDATE`/`FOR SHARE`), it takes the human's
`account_lock` row with a shared lock and refuses (`unauthenticated`, as an ended
session) when the account is deleted. The lock is held to the end of the transaction.

One lock order: the deletion takes the same row exclusively before anything else
(`account_deletion.lock_account`), every human caller's transaction takes it shared
before any other lock. A write either holds the shared lock first, commits, and is then
removed with the rest by the deletion, or waits for the deletion's commit and is refused.
Neither waits for the other while holding a lock the other wants, so the two cannot
form a cycle. `account_lock` is a row of its own, not the human row: the human row is
locked `FOR UPDATE` by ordinary work (account records, a slug claim, the preferences, the
avatar), often after project locks, and a shared lock on it held from a transaction's
start would deadlock against those. Nothing but this module and the deletion locks
`account_lock`.

Read-only transactions take no lock: under READ COMMITTED (and SQLite's serialised
writer) a plain read holds nothing the deletion waits for, and what it reads of a
deleted account is shaped by the views (§2.9). SQLite ignores the lock clause; its
`BEGIN IMMEDIATE` already makes one transaction wait for the other.

Only `deleted_at` is checked, not the calling session's end: a logout ends its own
session inside the transaction that is checked; the deletion ends every session and
sets `deleted_at` in one transaction, so the account is what tells.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Connection, Engine, event, insert, select
from sqlalchemy.exc import IntegrityError

from maity_hub import tables as t
from maity_hub.errors import unauthenticated

_HUMAN: ContextVar[str | None] = ContextVar("maity_write_guard_human", default=None)
_HELD = "maity_write_guard_held"  # conn.info: this transaction passed the check
_LOCKING = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE)\b|\bFOR\s+(NO\s+KEY\s+)?UPDATE\b|\bFOR\s+(KEY\s+)?SHARE\b"
    r"|\bLOCK\s+IN\s+SHARE\s+MODE\b",
    re.IGNORECASE,
)


def bind(human_id: str) -> None:
    """The calling human of this request (its context, copied into the thread the route
    runs in); set once the caller is authenticated."""
    _HUMAN.set(human_id)


def install(engine: Engine) -> None:
    """Hook the engine once."""
    if event.contains(engine, "before_cursor_execute", _before):
        return
    event.listen(engine, "before_cursor_execute", _before)
    # Cleared when a transaction begins, not only when it ends: `info` belongs to the
    # pooled connection, and a pool's reset ends a transaction without either event.
    event.listen(engine, "begin", _forget)
    event.listen(engine, "commit", _forget)
    event.listen(engine, "rollback", _forget)


def locking(statement: str) -> bool:
    """Whether a statement takes a row lock: a write, or a locking read."""
    return _LOCKING.search(statement) is not None


def _before(
    conn: Any, cursor: Any, statement: str, params: Any, context: Any, executemany: bool
) -> None:
    human_id = _HUMAN.get()
    if human_id is None or conn.info.get(_HELD):
        return
    # Taken before the first savepoint too: a lock taken inside a savepoint is given up
    # when that savepoint rolls back (PostgreSQL), and the flag would not know it.
    if not (locking(statement) or statement.lstrip()[:9].upper() == "SAVEPOINT"):
        return
    conn.info[_HELD] = True  # set first: the check's own statements pass through here
    hold(conn, human_id)


def _forget(conn: Any) -> None:
    conn.info.pop(_HELD, None)


def exempt(conn: Connection) -> None:
    """Let this transaction write without the check: one that changes nothing of an account,
    opened beside the caller's own transaction (`shared_counts`). Taking the shared lock there
    would wait for the caller's transaction, which may have just made the `account_lock` row and
    not committed it yet: a request waiting on itself."""
    conn.info[_HELD] = True


def ensure_row(conn: Connection, human_id: str) -> None:
    """The human's `account_lock` row, made when missing (a human made after 0076)."""
    found = conn.execute(
        select(t.account_lock.c.human_id).where(t.account_lock.c.human_id == human_id)
    ).first()
    if found is not None:
        return
    exists = conn.execute(select(t.human.c.id).where(t.human.c.id == human_id)).first()
    if exists is None:
        return
    try:
        with conn.begin_nested():
            conn.execute(insert(t.account_lock).values(human_id=human_id))
    except IntegrityError:
        pass  # made at the same moment by another transaction


def share(conn: Connection, human_id: str) -> None:
    """Take the human's `account_lock` shared, refusing nothing: for a change of the
    account that no caller of it makes (the address's confirmation link), so it takes
    its place in the same order against a deletion."""
    ensure_row(conn, human_id)
    conn.execute(
        select(t.account_lock.c.human_id)
        .where(t.account_lock.c.human_id == human_id)
        .with_for_update(read=True)
    ).first()


def hold(conn: Connection, human_id: str) -> None:
    """Take the human's `account_lock` shared and refuse a deleted or suspended account.
    Called before the transaction's first locking statement (`_before`), and by tests."""
    share(conn, human_id)
    row = conn.execute(
        select(t.human.c.deleted_at, t.human.c.suspended_at).where(t.human.c.id == human_id)
    ).first()
    # A suspension ends the sessions (§16.8): a request that got past them before it
    # committed waits here for it, and then finds the account suspended.
    if row is None or row.deleted_at is not None or row.suspended_at is not None:
        raise unauthenticated("the session has ended or expired")
