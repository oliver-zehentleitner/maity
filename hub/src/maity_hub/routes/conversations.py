"""The human's direct conversation with an agent it owns (docs/api.md §9).

A conversation is a filtered view of the event log: `message` events of
type `chat` whose `conversation_id` is the agent's member id, between the
agent and its owning human, nobody else.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import events, idempotency
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, not_found
from maity_hub.models import Strict, markdown
from maity_hub.routes.events import MessageIn, chat_parties, post_message
from maity_hub.views import ts

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200


class ChatIn(Strict):
    body: str = markdown(min_length=1)


def message_view(conn: Connection, row: Any) -> dict[str, Any]:
    delivered = conn.execute(
        select(t.message_delivery.c.delivered_at).where(t.message_delivery.c.seq == row.seq)
    ).scalar()
    payload = row.payload or {}
    return {
        "id": f"evt-{row.seq}",
        "seq": row.seq,
        "conversation_id": row.conversation_id,
        "from": _sender(conn, row),
        "to": payload.get("to"),
        "body": None if row.redacted else payload.get("body"),
        "sent_at": ts(row.at),
        "delivered_at": ts(delivered),
    }


def _sender(conn: Connection, row: Any) -> str | None:
    from maity_hub.views import principal_id

    return principal_id(conn, row.actor_membership)


def _party(conn: Connection, mine: Membership, caller: Caller, agent_id: str) -> tuple[Any, Any]:
    """The agent and its human; the caller must be one of them."""
    try:
        agent, human = chat_parties(conn, mine, agent_id)
    except ApiError:
        raise not_found() from None
    if mine.id not in (agent.id, human.id):
        raise forbidden(message="a conversation is its two parties' alone")
    return agent, human


def _messages(conn: Connection, project_id: str, agent_id: str) -> Any:
    return (
        select(t.event)
        .where(
            t.event.c.project_id == project_id,
            t.event.c.kind == "message",
            t.event.c.conversation_id == agent_id,
        )
        .order_by(t.event.c.seq)
    )


@router.get("/projects/{slug}/conversations")
def list_conversations(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        if caller.kind == "agent":
            agents = [caller.agent_id]
        else:
            agents = list(
                conn.execute(
                    select(t.membership.c.agent_id)
                    .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
                    .where(
                        t.membership.c.project_id == mine.project.id,
                        t.membership.c.active.is_(True),
                        t.agent_profile.c.owner_id == caller.human_id,
                    )
                    .order_by(t.agent_profile.c.handle)
                ).scalars()
            )
        items = [_summary(conn, mine, caller, agent_id) for agent_id in agents if agent_id]
        return JSONResponse({"items": items, "next_cursor": None})


def _summary(conn: Connection, mine: Membership, caller: Caller, agent_id: str) -> dict[str, Any]:
    last = conn.execute(
        select(func.max(t.event.c.at)).where(
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
            t.event.c.conversation_id == agent_id,
        )
    ).scalar()
    return {
        "agent_id": agent_id,
        "last_message_at": ts(last),
        "unread": _unread(conn, mine, caller, agent_id),
    }


def _unread(conn: Connection, mine: Membership, caller: Caller, agent_id: str) -> int:
    """The other party's messages after what this reader has seen (§9)."""
    if caller.kind == "human":
        seen = (
            conn.execute(
                select(t.conversation_read.c.last_seq).where(
                    t.conversation_read.c.reader == mine.id,
                    t.conversation_read.c.conversation_id == agent_id,
                )
            ).scalar()
            or 0
        )
    else:  # the agent's side is its event cursor
        seen = (
            conn.execute(
                select(t.agent_session.c.acknowledged_seq).where(
                    t.agent_session.c.id == caller.session_id
                )
            ).scalar()
            or 0
        )
    count = conn.execute(
        select(func.count()).where(
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
            t.event.c.conversation_id == agent_id,
            t.event.c.seq > seen,
            t.event.c.actor_membership != mine.id,
        )
    ).scalar_one()
    return int(count)


@router.get("/projects/{slug}/conversations/{agent_id}/messages")
def read_messages(
    slug: str,
    agent_id: str,
    request: Request,
    caller: AnyCaller,
    after: int = Query(default=0, ge=0, le=2**63 - 1),
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        _party(conn, mine, caller, agent_id)
        rows = conn.execute(
            _messages(conn, mine.project.id, agent_id).where(t.event.c.seq > after).limit(limit)
        ).all()
        events.mark_delivered(conn, list(rows), mine.principal_id)
        if rows and caller.kind == "human":
            _remember_read(conn, mine.id, agent_id, rows[-1].seq)
        cursor = rows[-1].seq if rows else after
        return JSONResponse({"items": [message_view(conn, r) for r in rows], "cursor": cursor})


def _remember_read(conn: Connection, reader: int, agent_id: str, seq: int) -> None:
    updated = conn.execute(
        update(t.conversation_read)
        .where(
            t.conversation_read.c.reader == reader,
            t.conversation_read.c.conversation_id == agent_id,
            t.conversation_read.c.last_seq < seq,
        )
        .values(last_seq=seq)
    ).rowcount
    if updated == 0:
        exists = conn.execute(
            select(t.conversation_read.c.last_seq).where(
                t.conversation_read.c.reader == reader,
                t.conversation_read.c.conversation_id == agent_id,
            )
        ).first()
        if exists is None:
            try:
                with conn.begin_nested():
                    conn.execute(
                        insert(t.conversation_read).values(
                            reader=reader, conversation_id=agent_id, last_seq=seq
                        )
                    )
            except IntegrityError:  # another tab read first; the larger seq wins next time
                pass


def load_message(conn: Connection, seq: str) -> dict[str, Any]:
    row = conn.execute(select(t.event).where(t.event.c.seq == int(seq))).one()
    return message_view(conn, row)


idempotency.LOADERS["message"] = load_message


@router.post("/projects/{slug}/conversations/{agent_id}/messages")
def send_message(
    slug: str, agent_id: str, body: ChatIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        _party(conn, mine, caller, agent_id)
        view = post_message(
            conn,
            mine,
            caller,
            MessageIn(kind="message", type="chat", body=body.body, conversation_id=agent_id),
        )
        return idempotency.Outcome(
            201, "message", str(view["seq"]), load_message(conn, str(view["seq"]))
        )

    return idempotency.run(engine_of(request), request, caller, action)
