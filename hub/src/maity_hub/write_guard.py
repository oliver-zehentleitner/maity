"""No write of a deleted account commits (docs/api.md §2.9, "ends access at once").

A call authenticates in a transaction of its own (`deps._resolve`) and writes in later
ones, so an account deleted in between would otherwise still get its write: a profile,
a runner, a project created after the deletion committed. The check therefore sits
where every write passes, the commit: for a human caller, a transaction that wrote
re-reads the caller's row under a shared lock right before it commits and refuses
(`unauthenticated`, as an ended session) when the account is deleted.

The deletion takes the same row `FOR UPDATE` first (`account_deletion.confirm`), so the
two are ordered: a write whose check runs first commits before the deletion reads what
the account owns and is removed with the rest; a write that comes second waits for the
deletion's commit and then sees `deleted_at`. SQLite serialises writers anyway.

Only `deleted_at` is checked, not the calling session's end: a logout, or ending one's
own session, ends it in the very transaction that would be checked; the deletion ends
every session and sets `deleted_at` in one transaction, so the account is what tells.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import Engine, event, select

from maity_hub import tables as t
from maity_hub.errors import unauthenticated

_HUMAN: ContextVar[str | None] = ContextVar("maity_write_guard_human", default=None)
_WROTE = "maity_write_guard_wrote"
_WRITES = ("INSERT", "UPDATE", "DELETE")


def bind(human_id: str) -> None:
    """The calling human of this request (its context, copied into the thread the route
    runs in); set once the caller is authenticated."""
    _HUMAN.set(human_id)


def install(engine: Engine) -> None:
    """Hook the engine once: mark a transaction that wrote, check it at its commit."""
    if event.contains(engine, "commit", _check):
        return
    event.listen(engine, "before_cursor_execute", _mark)
    event.listen(engine, "commit", _check)
    event.listen(engine, "rollback", _forget)


def _mark(
    conn: Any, cursor: Any, statement: str, params: Any, context: Any, executemany: bool
) -> None:
    if _HUMAN.get() is not None and statement.lstrip()[:6].upper() in _WRITES:
        conn.info[_WROTE] = True


def _forget(conn: Any) -> None:
    conn.info.pop(_WROTE, None)


def _check(conn: Any) -> None:
    human_id = _HUMAN.get()
    if not conn.info.pop(_WROTE, False) or human_id is None:
        return
    deleted = conn.execute(
        select(t.human.c.deleted_at).where(t.human.c.id == human_id).with_for_update(read=True)
    ).first()
    if deleted is None or deleted.deleted_at is not None:
        raise unauthenticated("the session has ended or expired")
