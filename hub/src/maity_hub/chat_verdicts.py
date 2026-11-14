"""Agree and disagree on a chat message (docs/api.md §9.7).

A human's current verdict on a message is a `chat_verdict` row; every change writes one
`chat_verdict` event, whose `seq` the row keeps as `set_seq`. The row is what a message shows
(`verdicts`), never derived from the events: a redaction replaces an event's payload, and the
verdict it set stays (hub/context/events.md). The caller decides who may give one; this module
writes and reads them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import events
from maity_hub import tables as t
from maity_hub.views import ts

KIND = "chat_verdict"
VALUES = ("agree", "disagree")


def current(conn: Connection, message_seq: int, human_id: str) -> Any:
    """The human's verdict on the message, or None."""
    return conn.execute(
        select(t.chat_verdict).where(
            t.chat_verdict.c.message_seq == message_seq, t.chat_verdict.c.human_id == human_id
        )
    ).first()


def change(
    conn: Connection,
    message: Any,
    human_id: str,
    value: str | None,
    sentence: str | None,
    *,
    conversation: dict[str, Any],
    author: str | None,
    audience: list[str],
    actor: events.Actor,
) -> int | None:
    """Give, replace or (`value` None) take back the human's verdict on `message`, under the
    project's lock the caller holds. Writes one `chat_verdict` and returns its seq; None when
    nothing changes, which writes no event (§9.7)."""
    before = current(conn, message.seq, human_id)
    if value is None and before is None:
        return None
    if before is not None and before.value == value and before.sentence == sentence:
        return None
    payload = {
        "conversation": conversation,
        "message_seq": message.seq,
        "author": author,
        "value": value,
        "previous": before.value if before is not None else None,
        "sentence": sentence if value is not None else None,
    }
    seq = events.emit(
        conn,
        message.project_id,
        KIND,
        audience,
        payload,
        actor=actor,
        subject=("conversation", message.conversation_id),
        conversation_id=message.conversation_id,
    )
    at = conn.execute(select(t.event.c.at).where(t.event.c.seq == seq)).scalar_one()
    key = (t.chat_verdict.c.message_seq == message.seq, t.chat_verdict.c.human_id == human_id)
    if value is None:
        conn.execute(delete(t.chat_verdict).where(*key))
    elif before is not None:
        conn.execute(
            update(t.chat_verdict)
            .where(*key)
            .values(value=value, sentence=sentence, set_seq=seq, at=at)
        )
    else:
        conn.execute(
            insert(t.chat_verdict).values(
                message_seq=message.seq,
                human_id=human_id,
                project_id=message.project_id,
                conversation_id=message.conversation_id,
                value=value,
                sentence=sentence,
                set_seq=seq,
                at=at,
            )
        )
    return seq


def of_messages(conn: Connection, rows: Sequence[Any]) -> dict[int, list[dict[str, Any]]]:
    """`verdicts` of each message (§9.7): the current verdict of each human, oldest first. A
    redacted message reads none; a verdict whose event was redacted shows its `value` with
    `sentence: null`."""
    seqs = [r.seq for r in rows if not r.redacted]
    found: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not seqs:
        return found
    verdict, setter = t.chat_verdict, t.event.alias("setter")
    for row in conn.execute(
        select(verdict, setter.c.redacted)
        .join(setter, setter.c.seq == verdict.c.set_seq)
        .where(verdict.c.message_seq.in_(seqs))
        .order_by(verdict.c.set_seq)
    ):
        found[row.message_seq].append(
            {
                "by": row.human_id,
                "value": row.value,
                "sentence": None if row.redacted else row.sentence,
                "at": ts(row.at),
                "seq": row.set_seq,
            }
        )
    return found
