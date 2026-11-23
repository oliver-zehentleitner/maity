"""The history of a human's allow and deny entries (docs/api.md §9.6, "History").

Every write of the lists records here what it did to each entry it touched: `created`,
`changed` (with the entry before it and the fields that differ), `deleted` or `expired`, with
the entry as it was and how it came about (`cause`). The owner's answer to the request to chat
with their agents records one `answer` item besides. Only the owner reads the history, newest
first, in the order written; it is kept as long as the account, at most `KEPT` items per human,
deleted with the account and in its export.

The cause of a write is set around it with `caused`; without one it is the owner's own write
under `/me/chat-access` (`list`). The writes take the entries' snapshots themselves:
`created` after an insert, `watching` around a write that may change or delete entries, so a
write gives one item per entry it changed and none where it changed nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, delete, insert, select

from maity_hub import clock, namespace, paging
from maity_hub import tables as t
from maity_hub.ids import new_id
from maity_hub.views import ts

KEPT = 10_000  # items per human; a write beyond deletes the oldest
ENTRY, ANSWER = "entry", "answer"
CREATED, CHANGED, DELETED, EXPIRED = "created", "changed", "deleted", "expired"
LIST, REQUEST, CHAT_ADD, EXPIRY, GONE = "list", "request", "chat_add", "expiry", "gone"
BY_THE_HUB = (EXPIRY, GONE)  # changes the hub makes itself: `by` is null


@dataclass(frozen=True)
class Cause:
    cause: str
    request_id: str | None = None
    conversation: dict[str, Any] | None = None


_CURRENT: ContextVar[Cause | None] = ContextVar("chat_access_history_cause", default=None)


@dataclass
class _Batch:
    """One logical write made of several (an account's deletion): the entries it touched, each
    as it was when first touched, and the account whose own history goes with it."""

    leaving: str | None
    before: dict[str, tuple[str, str, Any]]
    deny_ids: dict[str, str]
    causes: dict[str, Cause]


_BATCH: ContextVar[_Batch | None] = ContextVar("chat_access_history_batch", default=None)


@contextmanager
def caused(cause: Cause) -> Iterator[None]:
    """The cause of every entry write within: a request's answer, an add to a chat, a
    deletion of what an entry names."""
    token = _CURRENT.set(cause)
    try:
        yield
    finally:
        _CURRENT.reset(token)


@contextmanager
def one_write(conn: Connection, *, leaving: str | None = None) -> Iterator[None]:
    """Count the writes within as one (§9.6, "History": an account's deletion): each entry they
    narrow or delete gets one item once they are done, against the entry as it was before the
    first of them; none for `leaving`'s own entries. An exception within writes none."""
    batch = _Batch(leaving, {}, {}, {})
    token = _BATCH.set(batch)
    try:
        yield
    finally:
        _BATCH.reset(token)
    _compare(conn, batch.before, batch.deny_ids, batch.causes, skip=leaving)


def _cause() -> Cause:
    return _CURRENT.get() or Cause(LIST)


def chat_of(conn: Connection, conversation: Any) -> dict[str, Any]:
    """A group chat as an item names it: `{id, project: {owner, slug}}`."""
    full = namespace.full_names(conn, [conversation.project_id])[conversation.project_id]
    owner, slug = full.split("/", 1)
    return {"id": conversation.id, "project": {"owner": owner, "slug": slug}}


# Snapshots and the items of an entry ---------------------------------------------------------


def _snapshot(conn: Connection, entry_ids: Iterable[str]) -> dict[str, tuple[str, str, Any]]:
    """Each entry that is there, as the lists show it: id → (owner, kind, view)."""
    from maity_hub import chat_access

    ids = sorted(set(entry_ids))
    if not ids:
        return {}
    rows = conn.execute(
        select(t.chat_access).where(t.chat_access.c.id.in_(ids)).order_by(t.chat_access.c.id)
    ).all()
    views = chat_access.render(conn, rows)
    # The handle is not kept: a read shows the one the account has then (§9.6, "History").
    stored = [{**view, "handle": None} if "handle" in view else view for view in views]
    return {r.id: (r.human_id, r.kind, v) for r, v in zip(rows, stored, strict=True)}


def created(conn: Connection, entry_id: str, cause: Cause | None = None) -> None:
    """An entry just written."""
    for _, (owner, kind, view) in _snapshot(conn, [entry_id]).items():
        _entry_item(conn, owner, CREATED, kind, entry_id, view, None, [], cause)


@contextmanager
def watching(
    conn: Connection, entry_ids: Iterable[str], *, deny_id: str | None = None
) -> Iterator[None]:
    """Around a write that may change or delete `entry_ids`, whose rows the caller has locked:
    an item for each entry that it deleted or whose view it changed, none for the others. An
    exception within writes none."""
    was = before(conn, entry_ids)
    yield
    after(conn, was, deny_id=deny_id)


def before(conn: Connection, entry_ids: Iterable[str]) -> dict[str, tuple[str, str, Any]]:
    """The entries as they are before a write, for `after`."""
    return _snapshot(conn, entry_ids)


def after(
    conn: Connection, before: dict[str, tuple[str, str, Any]], *, deny_id: str | None = None
) -> None:
    """An item for each entry of `before` that the write since deleted or changed; within
    `one_write`, only once that is done."""
    batch = _BATCH.get()
    if batch is not None:
        for entry_id, was in before.items():
            batch.before.setdefault(entry_id, was)
            batch.causes.setdefault(entry_id, _cause())
            if deny_id is not None:
                batch.deny_ids.setdefault(entry_id, deny_id)
        return
    _compare(conn, before, {k: deny_id for k in before} if deny_id else {}, {})


def _compare(
    conn: Connection,
    before: dict[str, tuple[str, str, Any]],
    deny_ids: dict[str, str],
    causes: dict[str, Cause],
    *,
    skip: str | None = None,
) -> None:
    after = _snapshot(conn, before)
    for entry_id, (owner, kind, was) in sorted(before.items()):
        if owner == skip:
            continue
        deny_id, cause = deny_ids.get(entry_id), causes.get(entry_id)
        now = after.get(entry_id)
        if now is None:
            _entry_item(conn, owner, DELETED, kind, entry_id, was, None, [], cause, deny_id)
            continue
        fields = sorted(k for k in set(was) | set(now[2]) if was.get(k) != now[2].get(k))
        if fields:
            _entry_item(conn, owner, CHANGED, kind, entry_id, now[2], was, fields, cause, deny_id)


def expired(conn: Connection, entry_ids: Iterable[str]) -> None:
    """Allow entries whose `until` the hub just saw pass (§9.6, "Waiting")."""
    for entry_id, (owner, kind, view) in sorted(_snapshot(conn, entry_ids).items()):
        _entry_item(conn, owner, EXPIRED, kind, entry_id, view, None, [], Cause(EXPIRY))


def _entry_item(
    conn: Connection,
    owner: str,
    change: str,
    kind: str,
    entry_id: str,
    entry: Any,
    before: Any,
    fields: list[str],
    cause: Cause | None,
    deny_id: str | None = None,
) -> None:
    why = cause or _cause()
    data = {
        "change": change,
        "list": kind,
        "entry_id": entry_id,
        "by": None if why.cause in BY_THE_HUB else owner,
        "cause": why.cause,
        "request_id": why.request_id if why.cause == REQUEST else None,
        "deny_id": deny_id,
        "conversation": why.conversation if why.cause == CHAT_ADD else None,
        "entry": entry,
        "before": before,
        "fields": fields,
    }
    _write(conn, owner, ENTRY, entry_id, data)


# The answer to the request ---------------------------------------------------------------------


def answered(
    conn: Connection,
    owner: str,
    *,
    request_id: str,
    side: str,
    reply_id: str,
    withdrawn: bool,
    agents: list[str],
    body: dict[str, Any],
    entries: list[str],
) -> None:
    """The owner's answer to the request to chat with their agents (§9.6, "The request")."""
    allow = reply_id.startswith("allow_")
    data = {
        "by": owner,
        "request_id": request_id,
        "side": side,
        "reply_id": reply_id,
        "withdrawn": withdrawn,
        "agents": list(dict.fromkeys(agents)),
        "their_human": bool(body.get("their_human", False)) if allow else False,
        "their_agents": body.get("their_agents") if allow else None,
        "allowed": body.get("allowed") if allow else None,
        "denied": body.get("denied") if allow else None,
        "entries": entries,
    }
    _write(conn, owner, ANSWER, None, data)


def _write(conn: Connection, owner: str, kind: str, entry_id: str | None, data: Any) -> None:
    conn.execute(
        insert(t.chat_access_history).values(
            id=new_id("chat_access_history"),
            human_id=owner,
            kind=kind,
            entry_id=entry_id,
            data=data,
            at=clock.now(),
        )
    )
    _trim(conn, owner)


def _trim(conn: Connection, owner: str) -> None:
    """At most `KEPT` items per human: the oldest beyond go."""
    h = t.chat_access_history.c
    oldest_kept = conn.execute(
        select(h.n).where(h.human_id == owner).order_by(h.n.desc()).offset(KEPT - 1).limit(1)
    ).scalar()
    if oldest_kept is not None:
        conn.execute(delete(t.chat_access_history).where(h.human_id == owner, h.n < oldest_kept))


# Reads ---------------------------------------------------------------------------------------


def _scope(me: str) -> str:
    return paging.scope(list="chat_access_history", human=me)


def listing(conn: Connection, me: str, limit: int, cursor: str | None) -> dict[str, Any]:
    """`GET /me/chat-access/history`: newest first, in the order written, paged (§1.4)."""
    h = t.chat_access_history.c
    query = select(t.chat_access_history).where(h.human_id == me)
    if cursor is not None:
        query = query.where(h.n < paging.unseq(cursor, _scope(me)))
    rows = conn.execute(query.order_by(h.n.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    more = len(rows) > limit
    return {
        "items": render(conn, page),
        "next_cursor": paging.seq_cursor(page[-1].n, _scope(me)) if more else None,
    }


def exported(conn: Connection, me: str) -> list[dict[str, Any]]:
    """The whole history for the export (§2.9), oldest first."""
    h = t.chat_access_history.c
    rows = conn.execute(select(t.chat_access_history).where(h.human_id == me).order_by(h.n)).all()
    return render(conn, rows)


def render(conn: Connection, rows: Sequence[Any]) -> list[dict[str, Any]]:
    """The items as §9.6 shows them: the stored item with `entry_exists` and `names` as of now."""
    entry_ids = {r.entry_id for r in rows if r.entry_id is not None}
    existing: set[str] = set()
    if entry_ids:
        existing = set(
            conn.execute(
                select(t.chat_access.c.id).where(t.chat_access.c.id.in_(sorted(entry_ids)))
            ).scalars()
        )
    named = [_named(r.data) for r in rows]
    handles = _handles(conn, set().union(*named) if named else set())
    out = []
    for r, ids in zip(rows, named, strict=True):
        item: dict[str, Any] = {"id": r.id, "seq": r.n, "at": ts(r.at), "kind": r.kind}
        shown = {i: dict(handles.get(i, _GONE)) for i in sorted(ids)}
        if r.kind == ENTRY:
            data = dict(r.data)
            for side in ("entry", "before"):
                if data.get(side) is not None:
                    data[side] = _with_handle(data[side], shown)
            change = data.pop("change")
            listed = data.pop("list")
            entry_id = data.pop("entry_id")
            item.update(
                change=change,
                list=listed,
                entry_id=entry_id,
                entry_exists=entry_id in existing,
                **data,
            )
        else:
            item.update(r.data)
        item["names"] = shown
        out.append(item)
    return out


def _with_handle(entry: dict[str, Any], shown: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The entry with the `handle` the lists show beside a side or a human, as of the read."""
    if "handle" not in entry:
        return entry
    person = entry.get("owner_id") or entry.get("human_id")
    named = shown.get(person, _GONE) if isinstance(person, str) else _GONE
    return {**entry, "handle": named["handle"]}


def _named(data: dict[str, Any]) -> set[str]:
    """The ids of the agents and humans an item names: in its entry and the entry before, its
    side and its agents."""
    ids: set[str] = set()
    for entry in (data.get("entry"), data.get("before")):
        if not entry:
            continue
        for field in ("agents", "their_agents"):
            if isinstance(entry.get(field), list):
                ids.update(entry[field])
        for field in ("owner_id", "human_id", "agent_id"):
            if isinstance(entry.get(field), str):
                ids.add(entry[field])
    if isinstance(data.get("side"), str):
        ids.add(data["side"])
    for field in ("agents", "their_agents"):
        if isinstance(data.get(field), list):
            ids.update(data[field])
    return ids


_GONE: dict[str, Any] = {"handle": None, "deleted": True}


def _handles(conn: Connection, ids: set[str]) -> dict[str, dict[str, Any]]:
    """`{handle, deleted}` as the profile or the account is now: a deleted account as §2.9
    shows one, `{handle: None, deleted: True}`, and a deleted agent profile the same way,
    since its owner may give its handle to a new agent."""
    found: dict[str, dict[str, Any]] = {}
    humans = sorted(i for i in ids if i.startswith("hum-"))
    agents = sorted(i for i in ids if not i.startswith("hum-"))
    if humans:
        h = t.human.c
        found.update(
            {
                r.id: _GONE if r.deleted_at is not None else {"handle": r.handle, "deleted": False}
                for r in conn.execute(select(h.id, h.handle, h.deleted_at).where(h.id.in_(humans)))
            }
        )
    if agents:
        a = t.agent_profile.c
        found.update(
            {
                r.id: _GONE if r.deleted_at is not None else {"handle": r.handle, "deleted": False}
                for r in conn.execute(select(a.id, a.handle, a.deleted_at).where(a.id.in_(agents)))
            }
        )
    return found
