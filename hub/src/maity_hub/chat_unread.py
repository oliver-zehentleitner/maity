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

What holds (the lead's boundary for #1490 and tsk-tgh0st6p2zag; hub/context/events.md):
- guaranteed: no message body is read. The database work of a pass is bounded per stay and
  call by the budget, not by the unread history: at most SCAN_BUDGET of the chat's event rows,
  of any kind and author, for the messages (agents', redacted and other events cost the same
  as human messages), at most SCAN_BUDGET of the project's `event_redacted` rows, at most
  SCAN_BUDGET of the events whose subject is the chat for the open cycle (`_cycle_open`, read
  on from where it stopped), and one-row index reads (the read mark, the chat's newest seq,
  the project's newest redaction). A pass makes one call outside the lock and, for a stay
  whose nudge is due, one under it. Every unread human message without a mention leads to
  one nudge at any rate of new messages, redactions or events about the chat: a read's bound
  grows only once a call has reached it and the redaction look has caught up, the look's
  bound only once the look has reached it, and the open-cycle check's bound only once the
  check has reached it, so none keeps the others from finishing. A redaction committed before
  a pass starts is left out of the nudge, unless the project wrote SCAN_BUDGET or more
  redactions since the read's previous call: then the look catches up over several calls,
  and those committed meanwhile are held to the concurrent case below (docs/api.md §9.2 says
  the same);
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

from sqlalchemy import Connection, Engine, select

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
    `mark`, and the counted ones' number, first and last. `upto` is the bound the read goes
    to, and grows only once a call has seen its end (`reached`). `redactions_seen` is the seq
    of the last `event_redacted` of the project the scan has looked at: a later one that names
    a message counted here starts the read over (review of #1490; tsk-tgh0st6p2zag)."""

    mark: int
    scanned_to: int
    upto: int = 0
    redactions_seen: int = 0
    # The redactions' bound: the project's newest `event_redacted` when the look began; like
    # `upto` it grows only once the look reached it, so later redactions cannot starve it.
    redactions_upto: int = 0
    redactions_reached: bool = True
    # Whether the last call outside the lock began with the redaction look behind: then the call
    # under the lock confirms without looking further, so it cannot fall behind again.
    lagging: bool = False
    count: int = 0
    oldest_seq: int | None = None
    oldest_at: datetime | None = None
    newest_seq: int | None = None
    # Whether a call has seen the end of (mark, upto]: only then may the bound grow, so new
    # messages arriving faster than the budget cannot keep the read from ever finishing.
    reached: bool = True


@dataclass
class _Cycle:
    """What one stay has seen of its chat's `chat_unread` events (subject the conversation):
    read up to `cursor`, from `start` (the read mark when it began), and the highest
    `newest_seq` of those addressed to this agent (tsk-tgh0st6p2zag)."""

    start: int
    cursor: int
    newest: int = 0
    # The read's bound: the chat's newest subject event when the read had caught up; it grows
    # only once the read reached it, so events arriving faster than the budget cannot keep the
    # read from finishing (review of #1512, delta 1). `lagging` as for `_Scan`.
    upto: int = 0
    reached: bool = True
    lagging: bool = False


_SCANS: dict[tuple[int, str], _Scan] = {}
_CYCLES: dict[tuple[int, str], _Cycle] = {}
_SCANS_LOCK = threading.Lock()


def reset() -> None:
    """Forget every stay's scan: the next pass reads each one from its read mark again."""
    with _SCANS_LOCK:
        _SCANS.clear()
        _CYCLES.clear()


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


def _rows_after(conn: Connection, stay: Any, after: int, upto: int, limit: int) -> list[Any]:
    """Up to `limit` of the chat's events in (after, upto], oldest first, of any kind and
    author: seq, time, kind, the redacted flag, the author's human id (None for an agent or the
    hub) and the mentions alone, never the body (a JSON projection). The limit counts every
    event row read, and the caller decides which count (`_counted`), so a range of agents',
    redacted or other events costs the same as one of human messages (tsk-tgh0st6p2zag). An
    index range (project_id, conversation_id, seq) and one membership lookup per row."""
    e, m = t.event.c, t.membership.c
    return list(
        conn.execute(
            select(
                e.seq,
                e.at,
                e.kind,
                e.redacted,
                m.human_id,
                e.payload["mentions"].label("mentions"),
            )
            .select_from(t.event.outerjoin(t.membership, m.id == e.actor_membership))
            .where(
                e.project_id == stay.project_id,
                e.conversation_id == stay.conversation_id,
                e.seq > after,
                e.seq <= upto,
            )
            .order_by(e.seq)
            .limit(limit)
        )
    )


def _counted(row: Any, agent_id: str) -> bool:
    """Whether an event read by `_rows_after` is a counted message (§9.2): a human's message,
    not redacted, mentioning neither the agent nor one of its instances."""
    return (
        row.kind == "message"
        and not row.redacted
        and row.human_id is not None
        and not _mentions(row, agent_id)
    )


def _newest_seq(conn: Connection, stay: Any) -> int | None:
    """The seq of the chat's newest event, of any kind and author: the read's next bound, which
    `_rows_after` narrows to human messages. An index read (project_id, conversation_id, seq),
    newest first, one row, whatever the unread history."""
    e = t.event.c
    found = conn.execute(
        select(e.seq)
        .where(e.project_id == stay.project_id, e.conversation_id == stay.conversation_id)
        .order_by(e.seq.desc())
        .limit(1)
    ).scalar()
    return None if found is None else int(found)


def _last_redaction(conn: Connection, stay: Any) -> int:
    """The seq of the project's newest `event_redacted` (0 for none): an index read
    (project_id, kind, seq), newest first, one row."""
    e = t.event.c
    found = conn.execute(
        select(e.seq)
        .where(e.project_id == stay.project_id, e.kind == "event_redacted")
        .order_by(e.seq.desc())
        .limit(1)
    ).scalar()
    return int(found or 0)


def _redactions_after(conn: Connection, stay: Any, after: int, upto: int, limit: int) -> list[Any]:
    """Up to `limit` of the project's `event_redacted` events in (after, upto], oldest first: their
    seq, conversation and the seq of the event they redacted. Every path that redacts a project
    event writes one in the same transaction (routes/events.py `tombstone`,
    jourfixe/redaction.py), and seq follows commit order in a project (events.py), so a
    redaction is seen by the first read after it commits. An index range (project_id, kind,
    seq) over redactions only, bounded by `limit`."""
    e = t.event.c
    return list(
        conn.execute(
            select(e.seq, e.conversation_id, e.payload["seq"].label("target"))
            .where(
                e.project_id == stay.project_id,
                e.kind == "event_redacted",
                e.seq > after,
                e.seq <= upto,
            )
            .order_by(e.seq)
            .limit(limit)
        )
    )


def _mentions(row: Any, agent_id: str) -> bool:
    """Whether the message mentions the agent or one of its instances (§8.6)."""
    return any(
        isinstance(mention, dict) and mention.get("member_id") == agent_id
        for mention in row.mentions or []
    )


def _scanned(conn: Connection, stay: Any, mark: int, extend: bool = True) -> _Scan | None:
    """The stay's counted messages after `mark`, read on from where the last pass stopped:
    their number, first and last, or None while the read has not reached its bound (it goes
    on next pass). Each call reads at most SCAN_BUDGET event rows of the chat, whatever they
    are, and only those after the last one read, so a backlog that never leads to a nudge (all
    of it mentions the agent, or is agents' or redacted) is not read again each minute (review
    of #1490; review of #1512). A pass calls it once outside the lock and, for a stay whose
    nudge is due, once more under it, so a redaction that restarts the read in between can make
    one pass read up to twice the budget. A moved mark, or a redaction inside the range already
    read, starts the read over.

    Redactions: a cached read first looks at the project's `event_redacted` events after its
    cursor (`redactions_seen`) up to the look's bound (`redactions_upto`), at most SCAN_BUDGET;
    one that names a message of this chat inside the range already read starts the read over.
    The look's bound is the project's newest redaction, taken when the look has caught up; the
    read's bound grows only in a call whose look began and ended caught up, and the read
    finishes only with the look caught up. So a stream of later redactions slows the read but
    cannot stop it (review of #1512 R1). Under concurrent writes, a redaction committing later
    is seen by the next call; the call under the project lock (`check`) is the last, and a
    redaction takes the same lock, so none falls between it and the write, except after a call
    that began with the look behind (`lagging`): then the call under the lock confirms what was
    read without looking further, which is the concurrent case the module docstring leaves
    open."""
    key = (stay.membership_id, stay.conversation_id)
    with _SCANS_LOCK:
        scan = _SCANS.get(key)
    # Whether the redaction look began this call caught up: only then may the messages' bound
    # grow, so the two bounds never take turns growing and the read finishes (review of #1512).
    caught_up = True
    if scan is not None and scan.mark == mark:
        # The redactions since the last look: one of a message counted here starts over. Their
        # bound grows only once the look reached it, as the messages' does; a full batch that
        # names nothing here keeps the message read going, only the nudge waits for the look.
        caught_up = scan.redactions_reached
        if extend:
            scan.lagging = not caught_up
        if scan.redactions_reached and (extend or not scan.lagging):
            scan.redactions_upto = max(scan.redactions_seen, _last_redaction(conn, stay))
            scan.redactions_reached = scan.redactions_upto == scan.redactions_seen
        seen = []
        if not scan.redactions_reached:
            seen = _redactions_after(
                conn, stay, scan.redactions_seen, scan.redactions_upto, SCAN_BUDGET
            )
            if seen:
                scan.redactions_seen = int(seen[-1].seq)
            if len(seen) < SCAN_BUDGET:
                scan.redactions_seen = scan.redactions_upto
                scan.redactions_reached = True
        if any(
            row.conversation_id == stay.conversation_id
            and row.target is not None
            and mark < int(row.target) <= scan.scanned_to
            for row in seen
        ):
            scan = None
    else:
        scan = None
    if scan is None:
        # A fresh read: the redactions it must watch for are those after this moment; one
        # committed earlier already leaves its message out of the rows read below.
        scan = _Scan(mark=mark, scanned_to=mark, upto=mark)
        scan.redactions_seen = scan.redactions_upto = _last_redaction(conn, stay)
    newest = _newest_seq(conn, stay)
    grows = scan.reached and caught_up and scan.redactions_reached
    if newest is not None and newest > scan.upto and grows and (extend or scan.upto == mark):
        # The bound grows only once the read reached the old one (review of #1490, delta 4)
        # and the redaction look is caught up, and the call under the lock (`extend=False`)
        # only confirms the range the pass found due, unless it had to start over.
        scan.upto = newest
        scan.reached = False
    budget, complete = SCAN_BUDGET, False
    while budget > 0:
        limit = min(SCAN_BATCH, budget)
        rows = _rows_after(conn, stay, scan.scanned_to, scan.upto, limit)
        for row in rows:
            if _counted(row, stay.agent_id):
                scan.count += 1
                if scan.oldest_seq is None:
                    scan.oldest_seq, scan.oldest_at = row.seq, row.at
                scan.newest_seq = row.seq
            scan.scanned_to = row.seq
        budget -= len(rows)
        if len(rows) < limit:
            # The end of (mark, upto].
            complete = scan.reached = True
            scan.scanned_to = scan.upto
            break
    with _SCANS_LOCK:
        _SCANS[key] = scan
    return scan if complete and scan.redactions_reached else None


def _cycle_open(conn: Connection, stay: Any, mark: int, extend: bool = True) -> bool:
    """Whether a `chat_unread` for this agent and chat counted a message above its read mark:
    the read cycle it opened is still open (§9.2). Its own seq is no measure: the nudge is
    written after the messages it counts, so reading exactly those leaves the mark below it.
    A nudge whose `newest_seq` is above the mark has a seq above it too, so the read starts at
    the mark. It goes on from where the last call stopped (`_Cycle`), over every event whose
    subject is the chat, at most SCAN_BUDGET per call, and the recipient and kind are checked
    here: the other agents' nudges are read once, not each minute (tsk-tgh0st6p2zag).

    The read goes up to a bound, the chat's newest subject event when the read had caught up,
    and the bound grows only once the read reached it; until then the cycle counts as open, so
    no nudge goes out on a partial read, and the read still finishes while `conversation_updated`
    or other agents' nudges keep coming (review of #1512, delta 1). After a call outside the
    lock that began behind (`lagging`), the call under the lock confirms without taking a new
    bound, or it would fall behind again. What this process wrote lies below the next bound it
    takes, but another process's nudge can lie above the bound of this cache; so the call under
    the lock also reads the project's nudges above the bound, at most SCAN_BUDGET, and counts
    the cycle open on one for this agent and chat, or on a full batch (review of #1512,
    delta 2). Index reads (project_id, subject_type, subject_id, seq): one row for the
    bound, at most SCAN_BUDGET for the read."""
    key = (stay.membership_id, stay.conversation_id)
    with _SCANS_LOCK:
        cycle = _CYCLES.get(key)
    if cycle is None or mark < cycle.start:
        cycle = _Cycle(start=mark, cursor=mark, upto=mark)
    if extend:
        cycle.lagging = not cycle.reached
    e = t.event.c
    subject = (
        e.project_id == stay.project_id,
        e.subject_type == "conversation",
        e.subject_id == stay.conversation_id,
    )
    token = f"member:{stay.agent_id}"
    if cycle.reached and (extend or not cycle.lagging):
        newest = conn.execute(
            select(e.seq).where(*subject).order_by(e.seq.desc()).limit(1)
        ).scalar()
        cycle.upto = max(cycle.cursor, int(newest or 0))
        cycle.reached = cycle.upto == cycle.cursor
    if not cycle.reached:
        rows = list(
            conn.execute(
                select(e.seq, e.kind, e.audience, e.payload["newest_seq"].label("newest_seq"))
                .where(*subject, e.seq > cycle.cursor, e.seq <= cycle.upto)
                .order_by(e.seq)
                .limit(SCAN_BUDGET)
            )
        )
        for row in rows:
            if row.kind == KIND and token in (row.audience or []):
                cycle.newest = max(cycle.newest, int(row.newest_seq or 0))
            cycle.cursor = int(row.seq)
        if len(rows) < SCAN_BUDGET:
            cycle.cursor = cycle.upto
            cycle.reached = True
    with _SCANS_LOCK:
        _CYCLES[key] = cycle
    if not cycle.reached or cycle.newest > mark:
        return True
    if extend:
        return False
    # Under the lock, before a nudge is written: another process (a second worker, its own
    # caches) may have written one above what this cache has read (review of #1512, delta 2).
    # The project's nudges above the bound, at most SCAN_BUDGET, by the index (project_id,
    # kind, seq); more than that, and nothing is written now.
    above = list(
        conn.execute(
            select(
                e.subject_type,
                e.subject_id,
                e.audience,
                e.payload["newest_seq"].label("newest_seq"),
            )
            .where(e.project_id == stay.project_id, e.kind == KIND, e.seq > cycle.upto)
            .order_by(e.seq)
            .limit(SCAN_BUDGET)
        )
    )
    return len(above) == SCAN_BUDGET or any(
        row.subject_type == "conversation"
        and row.subject_id == stay.conversation_id
        and token in (row.audience or [])
        and int(row.newest_seq or 0) > mark
        for row in above
    )


def due(
    conn: Connection, stay: Any, listens: dict[int, bool] | None = None, extend: bool = True
) -> dict[str, Any] | None:
    """The nudge's payload when one is due for this stay now, else None. The cheap checks
    come first, so that what needs no nudge reads no message: whether the agent listens
    (`listens` keeps the answer per membership for one pass) and the open cycle. Only a stay
    that passes both reads its messages' mentions, and then only those it has not read before
    (`_scanned`): a row is read again only when the mark moves, a redaction falls inside the
    range read, or the process restarts (review of #1490). The delay is checked on the oldest
    counted message the read found; with `extend` False (the call under the lock) the read
    only confirms the range the pass found due (tsk-tgh0st6p2zag)."""
    listening_now = None if listens is None else listens.get(stay.membership_id)
    if listening_now is None:
        listening_now = _listening(conn, stay.membership_id)
        if listens is not None:
            listens[stay.membership_id] = listening_now
    if not listening_now:
        return None
    mark = _mark(conn, stay)
    if _cycle_open(conn, stay, mark, extend):
        return None
    scan = _scanned(conn, stay, mark, extend)
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
        payload = due(conn, stay, extend=False)
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
            for kept in (_SCANS, _CYCLES):
                for key in [key for key in kept if key not in keep]:
                    del kept[key]
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
