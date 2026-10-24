"""Writing events (docs/api.md §8, docs/architecture.md §7).

Writers serialise per project on the project row, so that a lower `seq`
never becomes visible after a higher one and a cursor never skips an
event. Every write that emits runs in `transaction()`, which signals the
waiters after the transaction committed, never before: a woken reader
must find the row.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Connection, Engine, insert, select
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, ticker_read
from maity_hub import tables as t

_PENDING = "maity_pending_events"
_UNDO = "maity_undo_on_rollback"


@dataclass(frozen=True)
class Actor:
    membership_id: int | None  # null for a runner, which is no member (§15.10)
    session_id: str | None = None
    credential_id: str | None = None
    via: str | None = None  # signed, bearer, cookie
    harness: str | None = None
    model: str | None = None
    runner_id: str | None = None


class Notifier:
    """Post-commit fan-out of new events to whoever waits on a project.

    Listeners are called from the committing thread; the long-poll
    (slice 5) registers one that wakes its asyncio waiters thread-safely.
    """

    def __init__(self) -> None:
        self._listeners: list[Callable[[str, int], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, listener: Callable[[str, int], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.remove(listener)

        return unsubscribe

    def notify(self, project_id: str, seq: int) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            listener(project_id, seq)


notifier = Notifier()


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """`engine.begin()` that announces the events it wrote once they are committed.

    SQLAlchemy's `commit` event fires before the database has committed, so
    a waiter woken there could read before the row is visible; the
    announcement waits until `begin()` has returned cleanly.
    """
    pending: list[tuple[str, int]] = []
    undo: list[Callable[[], None]] = []
    try:
        with engine.begin() as conn:
            conn.info[_PENDING] = pending
            conn.info[_UNDO] = undo
            try:
                yield conn
            finally:
                conn.info.pop(_PENDING, None)
                conn.info.pop(_UNDO, None)
    except BaseException:
        for step in reversed(undo):
            step()
        raise
    for project_id, seq in pending:
        notifier.notify(project_id, seq)


def on_rollback(conn: Connection, step: Callable[[], None]) -> None:
    """Run `step` when the caller's `transaction` does not commit: in-process state
    (a rate charged) must not outlive a write that never happened."""
    undo = conn.info.get(_UNDO)
    if undo is None:
        raise RuntimeError("events.on_rollback outside events.transaction()")
    undo.append(step)


def lock_project(conn: Connection, project_id: str) -> Any:
    """`SELECT … FOR UPDATE` on the project row, returned as it is now.

    Decisions that depend on the project (its state, its policy) are taken
    from this row, read under the lock; SQLite took its write lock at BEGIN.
    """
    return conn.execute(
        select(t.project).where(t.project.c.id == project_id).with_for_update()
    ).one()


def emit(
    conn: Connection,
    project_id: str,
    kind: str,
    audience: list[str],
    payload: dict[str, Any],
    *,
    actor: Actor | None = None,
    subject: tuple[str, str] | None = None,
    conversation_id: str | None = None,
) -> int:
    """Append one event inside the caller's transaction; returns its `seq`."""
    project = lock_project(conn, project_id)
    # Under the project's lock `seq` follows commit order; `at` must not run backwards
    # against it (a clock step back, replicas whose clocks differ): never before the
    # project's last event (§18.2, "at is monotonic per project").
    last = conn.execute(
        select(t.event.c.at)
        .where(t.event.c.project_id == project_id)
        .order_by(t.event.c.seq.desc())
        .limit(1)
    ).scalar()
    now = clock.now()
    result = conn.execute(
        insert(t.event).values(
            project_id=project_id,
            kind=kind,
            at=now if last is None or now >= last else last,
            actor_membership=actor.membership_id if actor else None,
            actor_session_id=actor.session_id if actor else None,
            actor_credential_id=actor.credential_id if actor else None,
            actor_via=actor.via if actor else None,
            actor_harness=actor.harness if actor else None,
            actor_model=actor.model if actor else None,
            actor_runner_id=actor.runner_id if actor else None,
            subject_type=subject[0] if subject else None,
            subject_id=subject[1] if subject else None,
            audience=audience,
            conversation_id=conversation_id,
            payload=payload,
            redacted=False,
        )
    )
    key = result.inserted_primary_key
    if key is None:
        raise RuntimeError("the event insert returned no seq")
    seq = int(key[0])
    if kind in {"message", "task_claimed"}:
        from maity_hub import onboarding

        onboarding.observe(
            conn,
            project,
            kind,
            payload,
            actor.membership_id if actor else None,
            now if last is None or now >= last else last,
        )
    pending = conn.info.get(_PENDING)
    if pending is None:
        raise RuntimeError("events.emit outside events.transaction(): nobody would be woken")
    pending.append((project_id, seq))
    return seq


SEE_ALL_ROLES = ("owner", "admin")
# Kinds no agent reads, whatever its role or audience (§8.2): one names who shares an
# environment, which only the humans responsible may know.
HUMANS_ONLY_KINDS = frozenset({"shared_environment_detected"})


def hidden_redactions(
    conn: Connection, rows: Sequence[Any], membership: Any = None
) -> frozenset[str]:
    """What a batch needs read once to judge its rows (§8.5, §17.5):
    - the `subject_id`s of `event_redacted` that name an event of a humans-only kind,
      as unreadable to agents as the event they redact;
    - `notice:<seq>` for each `event_redacted` whose subject is a ticker item: it is
      shaped like the item and never wakes;
    - with `membership`, `ticker:<seq>` for each decision item, and for the notice of
      one, whose request it may not read now: no item, no placeholder, no notice."""
    hidden = {f"ticker:{seq}" for seq in ticker_read.withheld(conn, rows, membership)}
    seqs = {int(r.subject_id) for r in rows if r.kind == "event_redacted" and r.subject_id}
    if not seqs:
        return frozenset(hidden)
    subjects = conn.execute(select(t.event).where(t.event.c.seq.in_(seqs))).all()
    for subject in subjects:
        if subject.kind in HUMANS_ONLY_KINDS:
            hidden.add(str(subject.seq))
        if subject.kind == "ticker":
            hidden.add(f"notice:{subject.seq}")
    hidden |= {f"ticker:{seq}" for seq in ticker_read.withheld(conn, subjects, membership)}
    return frozenset(hidden)


def readable_by(
    row: Any, membership: Any, principal: str, hidden: frozenset[str] = frozenset()
) -> bool:
    """§8.2: audience `all`, `member:<id>`, `role:<role>`, or one's own; owners and
    admins read every event of the project."""
    audience = row.audience or []
    humans_only = row.kind in HUMANS_ONLY_KINDS or (
        row.kind == "event_redacted" and row.subject_id in hidden
    )
    if humans_only and membership.agent_id is not None:
        return False
    if row.kind == "ticker" and f"ticker:{row.seq}" in hidden:
        return False  # a decision whose request it may not read: no item at all (§17.5)
    if row.kind == "event_redacted" and f"ticker:{row.subject_id}" in hidden:
        return False  # nor the notice of its removal
    if row.kind == "ticker_subscription_changed":
        # The member's own business, and the human owners' and admins' (§17.12).
        return (row.payload or {}).get("member_id") == principal or (
            membership.agent_id is None and membership.role in SEE_ALL_ROLES
        )
    if row.actor_membership == membership.id:
        return True
    if row.conversation_id is not None:
        # A conversation is its two parties' alone, admins included (§9).
        return f"member:{principal}" in audience
    if membership.role in SEE_ALL_ROLES:
        return True
    return (
        "all" in audience
        or f"member:{principal}" in audience
        or f"role:{membership.role}" in audience
    )


def read(
    conn: Connection, project_id: str, membership: Any, principal: str, after: int, limit: int
) -> tuple[list[Any], int, bool]:
    """Readable events after `after`, oldest first: (rows, highest seq examined, truncated)."""
    return _scan(
        conn,
        t.event.c.project_id == project_id,
        lambda row, hidden: readable_by(row, membership, principal, hidden),
        after,
        limit,
        membership,
    )


def _scan(
    conn: Connection,
    scope: ColumnElement[bool],
    readable: Callable[[Any, frozenset[str]], bool],
    after: int,
    limit: int,
    membership: Any = None,
) -> tuple[list[Any], int, bool]:
    found: list[Any] = []
    examined = after
    while True:
        batch = conn.execute(
            select(t.event)
            .where(scope, t.event.c.seq > examined)
            .order_by(t.event.c.seq)
            .limit(500)
        ).all()
        hidden = hidden_redactions(conn, batch, membership)
        for row in batch:
            if readable(row, hidden):
                if len(found) == limit:
                    return found, found[-1].seq, True
                found.append(row)
            examined = row.seq
        if len(batch) < 500:
            return found, examined, False


# Readable by everyone they name, but never a reason to wake (§8.2): what a project
# shows changed, nothing anybody has to act on. Memory is read on the next resume (§19.3).
NON_WAKING = frozenset(
    {
        "project_updated",
        "avatar_changed",
        "memory_added",
        "memory_deleted",
        "soul_changed",
        "request_claimed",  # a claim wakes nobody (§7)
    }
)


def runner_reads(row: Any, runner_id: str) -> bool:
    """§15.8: addressed to the runner by audience, and not caused by the runner itself;
    `all` never reaches a runner."""
    return f"runner:{runner_id}" in (row.audience or []) and row.actor_runner_id != runner_id


def read_for_runner(
    conn: Connection, project_ids: Sequence[str], runner_id: str, after: int, limit: int
) -> tuple[list[Any], int]:
    """The runner's events after `after` over its projects: (rows, highest seq examined)."""
    if not project_ids:
        return [], after
    rows, examined, _ = _scan(
        conn,
        t.event.c.project_id.in_(project_ids),
        lambda row, _hidden: runner_reads(row, runner_id),
        after,
        limit,
    )
    return rows, examined


def wakes(row: Any, membership: Any, principal: str) -> bool:
    """§8.2 wake-relevant: addressed to the reader by audience (or a conversation naming
    it), and not caused by the reader's own membership. Seeing everything as an owner or
    admin never wakes, and neither does a kind in NON_WAKING."""
    if row.actor_membership == membership.id or row.kind in NON_WAKING:
        return False
    if row.kind == "ticker":
        return ticker_read.wakes(row, principal)
    if row.kind == "request_forwarded":
        # Only a forward to a member wakes, and only that member; an opening to the
        # admins wakes no agent, it would wake every admin agent at once (§7).
        payload = row.payload or {}
        return (
            payload.get("holder") == principal
            and payload.get("step", {}).get("action") == "forwarded"
        )
    audience = row.audience or []
    return (
        "all" in audience
        or f"member:{principal}" in audience
        or f"role:{membership.role}" in audience
        or row.conversation_id == principal
    )


def read_waking(
    conn: Connection, project_id: str, membership: Any, principal: str, after: int, limit: int
) -> tuple[list[Any], int]:
    """Wake-relevant events after `after`: (rows, highest seq examined)."""
    rows, examined, truncated = read(conn, project_id, membership, principal, after, 10_000)
    # The notice of a removed ticker item is read like the item, and woken by never (§17.5).
    notices = hidden_redactions(conn, [r for r in rows if r.kind == "event_redacted"])
    found = [
        r
        for r in rows
        if wakes(r, membership, principal)
        and not (r.kind == "event_redacted" and f"notice:{r.subject_id}" in notices)
    ][:limit]
    if found and (len(found) == limit or truncated):
        return found, found[-1].seq
    return found, examined


def highest_readable(conn: Connection, project_id: str, membership: Any, principal: str) -> int:
    """`after=latest`: the highest seq this reader may read, or 0."""
    return _highest(
        conn,
        t.event.c.project_id == project_id,
        lambda row, hidden: readable_by(row, membership, principal, hidden),
        membership,
    )


def highest_for_runner(conn: Connection, project_ids: Sequence[str], runner_id: str) -> int:
    """The runner's `after=latest` and the cursor of its hello packet (§15.8)."""
    if not project_ids:
        return 0
    return _highest(
        conn,
        t.event.c.project_id.in_(project_ids),
        lambda row, _hidden: runner_reads(row, runner_id),
    )


def _highest(
    conn: Connection,
    scope: ColumnElement[bool],
    readable: Callable[[Any, frozenset[str]], bool],
    membership: Any = None,
) -> int:
    query = select(t.event).where(scope).order_by(t.event.c.seq.desc()).limit(500)
    before = None
    while True:
        batch = conn.execute(
            query.where(t.event.c.seq < before) if before is not None else query
        ).all()
        hidden = hidden_redactions(conn, batch, membership)
        for row in batch:
            if readable(row, hidden):
                seq: int = row.seq
                return seq
        if len(batch) < 500:
            return 0
        before = batch[-1].seq


def mark_delivered(conn: Connection, rows: list[Any], reader: str) -> None:
    """The first time a chat message reaches its recipient (docs/api.md §9)."""
    seqs = [
        r.seq
        for r in rows
        if r.kind == "message"
        and not r.redacted
        and (r.payload or {}).get("type") == "chat"
        and (r.payload or {}).get("to") == reader
    ]
    if not seqs:
        return
    known = set(
        conn.execute(
            select(t.message_delivery.c.seq).where(t.message_delivery.c.seq.in_(seqs))
        ).scalars()
    )
    now = clock.now()
    for seq in seqs:
        if seq not in known:
            try:
                with conn.begin_nested():
                    conn.execute(insert(t.message_delivery).values(seq=seq, delivered_at=now))
            except IntegrityError:
                pass  # another read delivered it a moment earlier: the first time stands
