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
all the cycle needs.
Agents' messages never count, so two agents cannot wake each other through it; humans are
never addressed, every message of the others wakes them already. Not for a jour fixe round's
thread (`hub_thread`), a closed chat, a direct conversation or a cross-project chat (§9.5),
which are not rows of `conversation` here, or a paused or isolated membership.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, and_, func, select

from maity_hub import clock, listening
from maity_hub import tables as t
from maity_hub.events import emit, lock_project, transaction

log = logging.getLogger(__name__)

KIND = "chat_unread"
# `chat_unread.delay` (§9.2): a hub constant today; should it become a setting, the name and
# its meaning stay. Long enough that a burst of messages is one nudge and a human who wants
# an answer at once has time to mention; short against the hours a chat lay unseen.
DELAY = timedelta(minutes=10)


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


def _listening(conn: Connection, membership_id: str) -> bool:
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


def _humans_after(stay: Any, after: int) -> Any:
    """The human participants' unredacted messages of the chat after `after` (a WHERE)."""
    e, m = t.event.c, t.membership.c
    return and_(
        m.id == e.actor_membership,
        e.project_id == stay.project_id,
        e.conversation_id == stay.conversation_id,
        e.kind == "message",
        e.seq > after,
        e.redacted.is_(False),
        m.human_id.is_not(None),
    )


def _oldest_human(conn: Connection, stay: Any, after: int) -> Any:
    """The oldest human message's time after `after`, or None: an aggregate, no row read.
    Mentions only take messages out, so the delay cannot be due when this is younger."""
    return conn.execute(
        select(func.min(t.event.c.at))
        .select_from(t.event.join(t.membership, t.membership.c.id == t.event.c.actor_membership))
        .where(_humans_after(stay, after))
    ).scalar()


def _counted(conn: Connection, stay: Any, after: int) -> list[Any]:
    """The human participants' messages after `after` that mention neither the agent nor
    one of its instances, oldest first: seq, time and the mentions alone, never the body
    (a JSON projection), so the read stays small however long the messages are."""
    e = t.event.c
    rows = conn.execute(
        select(e.seq, e.at, e.payload["mentions"].label("mentions"))
        .select_from(t.event.join(t.membership, t.membership.c.id == e.actor_membership))
        .where(_humans_after(stay, after))
        .order_by(e.seq)
    )
    return [
        row
        for row in rows
        if not any(
            isinstance(mention, dict) and mention.get("member_id") == stay.agent_id
            for mention in row.mentions or []
        )
    ]


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
    conn: Connection, stay: Any, listens: dict[str, bool] | None = None
) -> dict[str, Any] | None:
    """The nudge's payload when one is due for this stay now, else None. The cheap checks
    come first, so that what needs no nudge reads no message: whether the agent listens
    (`listens` keeps the answer per membership for one pass), the open cycle, and the oldest
    human message's age by an aggregate. Only a stay that passes all three reads its
    messages' mentions, and an emitted nudge opens a cycle, so that read happens at most once
    per cycle (review of #1490: an offline agent's growing unread range was read each minute)."""
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
    counted = _counted(conn, stay, mark)
    if not counted or counted[0].at > clock.now() - DELAY:
        return None
    return {
        "conversation": {"id": stay.conversation_id, "kind": "group", "title": stay.title},
        "unread": len(counted),
        "oldest_seq": counted[0].seq,
        "newest_seq": counted[-1].seq,
    }


def check(engine: Engine, conversation_id: str, membership_id: str) -> int | None:
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
    with engine.connect() as conn:
        listens: dict[str, bool] = {}
        pending = [
            (stay.conversation_id, stay.membership_id)
            for stay in _candidates(conn)
            if due(conn, stay, listens) is not None
        ]
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
