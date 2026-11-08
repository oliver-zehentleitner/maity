"""The unread nudge in a group chat (docs/api.md §9.2, "The unread nudge"; §8.2).

What human participants write in a group chat without mentioning an agent participant wakes
it once, later: the worker's minute pass emits `chat_unread` for the agent when the chat holds
*counted* messages (a human's, after the agent's read mark and inside its window, not
redacted, mentioning neither the agent nor one of its instances), the oldest of them is
`DELAY` old, an instance of the agent that is neither dormant nor paused listens, and no
`chat_unread` for that chat lies above the read mark. Reading the chat moves the mark and so
re-arms it once the mark reaches the nudge's `newest_seq`; a `wait` or a resume delivering the
nudge moves nothing.

Nothing is stored for it: the read mark (`conversation_read`, else the stay's `window_after`)
and the event table (an earlier `chat_unread`, found by its subject, and its `newest_seq`) say
all the cycle needs. The only thing kept between passes is in this process's memory: per stay,
how far its unread messages have been read and their running counts (`_Scan`), so a pass reads
only what came since, in bounded batches. Restarted, moved to another replica or reset, it reads
the stay once more from its read mark.
Agents' messages never count, so two agents cannot wake each other through it; humans are
never addressed, every message of the others wakes them already. Not for a jour fixe round's
thread (`hub_thread`), a closed chat, a direct conversation or a cross-project chat (§9.5),
which are not rows of `conversation` here, or a paused or isolated membership.

What holds (the lead's boundary for #1490; hub/context/events.md):
- guaranteed: no message body is read; the message rows read are bounded (SCAN_BUDGET per
  stay and call; a pass makes one call outside the lock and, for a stay whose nudge is due,
  one under it), while the one-row
  aggregates (`_counts`, `_oldest_human`) go over the stay's unread range in the database each
  minute, a cost that grows with unread history; every unread human message without a
  mention leads to one nudge once the read has caught up. Each call moves the read's bound up
  to the newest message and reads at most SCAN_BUDGET rows, and a read finishes only on a batch
  that comes back short: while SCAN_BUDGET or more new human messages arrive in the chat
  between passes it may never finish; with fewer, each pass gains on the backlog until a call
  reaches the end. And a redaction committed before a pass starts is left out of the nudge;
- beyond that, a redaction that commits while a pass runs is caught by the call under the
  project lock on both routes known from the review (a first read, and an earlier read whose
  bound grows; each tested on PostgreSQL). Exactness against a concurrent redaction is not
  promised: the nudge is a wake-up hint, and the agent then reads the chat, which shows a
  redacted message only as its tombstone (§8.5), never its body. Another route, should one
  turn up, is a P3 for the hub roll-up.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, and_, case, func, select

from maity_hub import clock, listening
from maity_hub import tables as t
from maity_hub.events import emit, lock_project, transaction

log = logging.getLogger(__name__)

KIND = "chat_unread"
# `chat_unread.delay` (§9.2): a hub constant today; should it become a setting, the name and
# its meaning stay. Long enough that a burst of messages is one nudge and a human who wants
# an answer at once has time to mention; short against the hours a chat lay unseen.
DELAY = timedelta(minutes=10)
# Rows read per query, and per stay and pass: a long unread range is read over several passes
# rather than at once; the nudge waits until the read reached its end, so its counts cover every
# message up to it (concurrent redactions: the module docstring).
SCAN_BATCH = 500
SCAN_BUDGET = 2000


@dataclass
class _Scan:
    """What one stay's unread messages have shown so far: read up to `scanned_to`, from
    `mark`, and the counted ones' number, first and last. `upto` is the high-water mark the
    read is bounded by, and `redacted` how many human messages in (mark, upto] were redacted.
    That count is always taken in one statement with the check of the range already read
    (`_counts`), never after it: a redaction committed later moves it and starts the read
    over, one committed earlier is left out of the rows read (review of #1490, deltas 2, 3)."""

    mark: int
    scanned_to: int
    upto: int = 0
    redacted: int = 0
    count: int = 0
    oldest_seq: int | None = None
    oldest_at: datetime | None = None
    newest_seq: int | None = None


_SCANS: dict[tuple[int, str], _Scan] = {}
_SCANS_LOCK = threading.Lock()


def reset() -> None:
    """Forget every stay's scan: the next pass reads each one from its read mark again."""
    with _SCANS_LOCK:
        _SCANS.clear()


def _candidates(conn: Connection, conversation_id: str | None = None) -> list[Any]:
    """Every open stay of an agent in an open group chat that is not a round's thread, with
    the membership's state the conditions read; with `conversation_id`, that chat's."""
    p, c, m = t.conversation_participant.c, t.conversation.c, t.membership.c
    query = (
        select(
            p.conversation_id,
            p.window_after,
            p.membership_id,
            c.project_id,
            c.title,
            m.agent_id,
        )
        .join(t.conversation, c.id == p.conversation_id)
        .join(t.membership, m.id == p.membership_id)
        .where(
            p.here.is_(True),
            c.closed_at.is_(None),
            c.hub_thread.is_(False),
            m.agent_id.is_not(None),
            m.active.is_(True),
            m.removed_at.is_(None),
            m.paused_since.is_(None),
            m.isolated_since.is_(None),
        )
        .order_by(c.project_id, p.conversation_id, p.membership_id)
    )
    if conversation_id is not None:
        query = query.where(p.conversation_id == conversation_id)
    return list(conn.execute(query))


def _listening(conn: Connection, membership_id: int) -> bool:
    """Whether an instance of the agent that is neither dormant nor paused has a live
    session with an open long-poll (§5.3)."""
    s, cr = t.agent_session.c, t.credential.c
    sessions = (
        conn.execute(
            select(s.id)
            .join(t.credential, cr.id == s.credential_id)
            .where(
                s.membership_id == membership_id,
                s.live.is_(True),
                s.ended_at.is_(None),
                cr.revoked_at.is_(None),
                cr.dormant_since.is_(None),
                cr.paused_since.is_(None),
            )
        )
        .scalars()
        .all()
    )
    return bool(sessions) and bool(listening.which(sessions, conn))


def _mark(conn: Connection, stay: Any) -> int:
    """The seq the agent counts from in this chat: its read mark, or its window if later."""
    read = conn.execute(
        select(t.conversation_read.c.last_seq).where(
            t.conversation_read.c.reader == stay.membership_id,
            t.conversation_read.c.conversation_id == stay.conversation_id,
        )
    ).scalar()
    return max(int(stay.window_after), int(read or 0))


def _humans_after(stay: Any, after: int, *, redacted: bool = False) -> Any:
    """The human participants' messages of the chat after `after` (a WHERE): the unredacted
    ones, or with `redacted` the redacted ones."""
    e, m = t.event.c, t.membership.c
    return and_(
        m.id == e.actor_membership,
        e.project_id == stay.project_id,
        e.conversation_id == stay.conversation_id,
        e.kind == "message",
        e.seq > after,
        e.redacted.is_(redacted),
        m.human_id.is_not(None),
    )


def _humans_from() -> Any:
    return t.event.join(t.membership, t.membership.c.id == t.event.c.actor_membership)


def _oldest_human(conn: Connection, stay: Any, after: int) -> Any:
    """The oldest human message's time after `after`, or None: an aggregate, no row read.
    Mentions only take messages out, so the delay cannot be due when this is younger."""
    return conn.execute(
        select(func.min(t.event.c.at)).select_from(_humans_from()).where(_humans_after(stay, after))
    ).scalar()


def _rows_after(conn: Connection, stay: Any, after: int, upto: int, limit: int) -> list[Any]:
    """Up to `limit` human messages in (after, upto], oldest first: seq, time and the
    mentions alone, never the body (a JSON projection)."""
    e = t.event.c
    return list(
        conn.execute(
            select(e.seq, e.at, e.payload["mentions"].label("mentions"))
            .select_from(_humans_from())
            .where(_humans_after(stay, after), e.seq <= upto)
            .order_by(e.seq)
            .limit(limit)
        )
    )


def _counts(conn: Connection, stay: Any, mark: int, upto: int) -> tuple[int | None, int, int]:
    """In one statement, so one snapshot even under READ COMMITTED: the newest human message's
    seq after `mark` (redacted or not), and how many human messages are redacted in
    (mark, upto] and above `upto`. The check of a range already read and the count for its
    extension then cannot fall apart around a redaction committed between two statements."""
    e, m = t.event.c, t.membership.c
    redacted = e.redacted.is_(True)
    row = conn.execute(
        select(
            func.max(e.seq),
            func.coalesce(func.sum(case((and_(redacted, e.seq <= upto), 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(redacted, e.seq > upto), 1), else_=0)), 0),
        )
        .select_from(_humans_from())
        .where(
            e.project_id == stay.project_id,
            e.conversation_id == stay.conversation_id,
            e.kind == "message",
            e.seq > mark,
            m.human_id.is_not(None),
        )
    ).one()
    newest = None if row[0] is None else int(row[0])
    return newest, int(row[1]), int(row[2])


def _mentions(row: Any, agent_id: str) -> bool:
    """Whether the message mentions the agent or one of its instances (§8.6)."""
    return any(
        isinstance(mention, dict) and mention.get("member_id") == agent_id
        for mention in row.mentions or []
    )


def _scanned(conn: Connection, stay: Any, mark: int) -> _Scan | None:
    """The stay's counted messages after `mark`, read on from where the last pass stopped:
    their number, first and last, or None while the read has not reached its bound (it goes
    on next pass). Each call reads at most SCAN_BUDGET rows of this stay, and only those after
    the last one read, so a backlog that never leads to a nudge (all of it mentions the agent)
    is not read again each minute (review of #1490). A pass calls it once outside the lock and,
    for a stay whose nudge is due, once more under it, so a redaction that restarts the read
    in between can make one pass read up to twice the budget. A moved mark, or a redaction
    inside the bounded range, starts the read over.

    Redactions under concurrent writes: the check of the range already read and the bound and
    redaction count for its extension come from one statement (`_counts`), and only then are
    rows under the bound read. A redaction committed after that statement moves the count
    and restarts the read at the next call; the call under the project lock (`check`) is the
    last, and a redaction takes the same lock, so none falls between it and the write."""
    key = (stay.membership_id, stay.conversation_id)
    with _SCANS_LOCK:
        scan = _SCANS.get(key)
    if scan is None or scan.mark != mark:
        scan = _Scan(mark=mark, scanned_to=mark, upto=mark)
    newest, in_range, above = _counts(conn, stay, mark, scan.upto)
    if scan.upto > mark and in_range != scan.redacted:
        # A message already counted may have been redacted: start over. A fresh scan has no
        # counted row, so the count taken for it now can hide nothing.
        scan = _Scan(mark=mark, scanned_to=mark, upto=mark)
        newest, in_range, above = _counts(conn, stay, mark, mark)
    if newest is not None and newest > scan.upto:
        # The extension's count from the same statement as the check above.
        scan.redacted = in_range + above
        scan.upto = newest
    budget, complete = SCAN_BUDGET, False
    while budget > 0:
        limit = min(SCAN_BATCH, budget)
        rows = _rows_after(conn, stay, scan.scanned_to, scan.upto, limit)
        for row in rows:
            if not _mentions(row, stay.agent_id):
                scan.count += 1
                if scan.oldest_seq is None:
                    scan.oldest_seq, scan.oldest_at = row.seq, row.at
                scan.newest_seq = row.seq
            scan.scanned_to = row.seq
        budget -= len(rows)
        if len(rows) < limit:
            complete = True
            break
    with _SCANS_LOCK:
        _SCANS[key] = scan
    return scan if complete else None


def _cycle_open(conn: Connection, stay: Any, mark: int) -> bool:
    """Whether a `chat_unread` for this agent and chat counted a message above its read mark:
    the read cycle it opened is still open (§9.2). Its own seq is no measure: the nudge is
    written after the messages it counts, so reading exactly those leaves the mark below it.
    A nudge whose `newest_seq` is above the mark has a seq above it too, which narrows the
    read."""
    e = t.event.c
    rows = conn.execute(
        select(e.audience, e.payload["newest_seq"].label("newest_seq")).where(
            e.project_id == stay.project_id,
            e.subject_type == "conversation",
            e.subject_id == stay.conversation_id,
            e.kind == KIND,
            e.seq > mark,
        )
    )
    token = f"member:{stay.agent_id}"
    return any(token in (row.audience or []) and int(row.newest_seq or 0) > mark for row in rows)


def due(
    conn: Connection, stay: Any, listens: dict[int, bool] | None = None
) -> dict[str, Any] | None:
    """The nudge's payload when one is due for this stay now, else None. The cheap checks
    come first, so that what needs no nudge reads no message: whether the agent listens
    (`listens` keeps the answer per membership for one pass), the open cycle, and the oldest
    human message's age by an aggregate. Only a stay that passes all three reads its
    messages' mentions, and then only those it has not read before (`_scanned`): a row is read
    again only when the mark moves, a redaction falls inside the range read, or the process
    restarts (review of #1490)."""
    listening_now = None if listens is None else listens.get(stay.membership_id)
    if listening_now is None:
        listening_now = _listening(conn, stay.membership_id)
        if listens is not None:
            listens[stay.membership_id] = listening_now
    if not listening_now:
        return None
    mark = _mark(conn, stay)
    if _cycle_open(conn, stay, mark):
        return None
    oldest = _oldest_human(conn, stay, mark)
    if oldest is None or oldest > clock.now() - DELAY:
        return None
    scan = _scanned(conn, stay, mark)
    if scan is None or not scan.count or scan.oldest_at is None:
        return None
    if scan.oldest_at > clock.now() - DELAY:
        return None
    return {
        "conversation": {"id": stay.conversation_id, "kind": "group", "title": stay.title},
        "unread": scan.count,
        "oldest_seq": scan.oldest_seq,
        "newest_seq": scan.newest_seq,
    }


def check(engine: Engine, conversation_id: str, membership_id: int) -> int | None:
    """One stay: emit the nudge when it is due, under the project's lock. The seq or None."""
    with transaction(engine) as conn:
        project_id = conn.execute(
            select(t.conversation.c.project_id).where(t.conversation.c.id == conversation_id)
        ).scalar_one()
        lock_project(conn, project_id)
        # Read again under the lock: a pause, a leave or a read may have come meanwhile.
        stay = next(
            (
                row
                for row in _candidates(conn, conversation_id)
                if row.membership_id == membership_id
            ),
            None,
        )
        if stay is None:
            return None
        payload = due(conn, stay)
        if payload is None:
            return None
        return emit(
            conn,
            project_id,
            KIND,
            [f"member:{stay.agent_id}"],
            payload,
            subject=("conversation", conversation_id),
        )


def sweep(engine: Engine) -> list[int]:
    """Every agent's open stay in an open group chat: read first, outside the lock, and only
    a stay whose nudge is due is checked again and written under it. The seqs written."""
    pending = []
    with engine.connect() as conn:
        listens: dict[int, bool] = {}
        stays = _candidates(conn)
        keep = {(stay.membership_id, stay.conversation_id) for stay in stays}
        with _SCANS_LOCK:  # a stay that ended, or a chat that closed, needs no scan kept
            for key in [key for key in _SCANS if key not in keep]:
                del _SCANS[key]
        for stay in stays:
            try:
                if due(conn, stay, listens) is not None:
                    pending.append((stay.conversation_id, stay.membership_id))
            except Exception:  # one stay's failure must not stop the others' reads either
                log.exception(
                    "the unread nudge of %s in %s failed", stay.membership_id, stay.conversation_id
                )
                conn.rollback()  # a failed statement aborts the transaction on PostgreSQL
    written = []
    for conversation_id, membership_id in pending:
        try:
            seq = check(engine, conversation_id, membership_id)
        except Exception:  # one stay's failure must not stop the others
            log.exception("the unread nudge of %s in %s failed", membership_id, conversation_id)
            continue
        if seq is not None:
            written.append(seq)
    return written
