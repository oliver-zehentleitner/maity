"""Reading events, the long-poll, posting messages, redaction (docs/api.md §8)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import clock, events, idempotency, longpoll
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, EventsCaller, engine_of, wait_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.models import Strict, markdown
from maity_hub.views import event_view

router = APIRouter()

FALLBACK_SECONDS = 2.0
PAGE_DEFAULT, PAGE_MAX = 50, 200
MESSAGE_TYPES = (
    "interface_change",
    "blocker",
    "go_request",
    "review_result",
    "handover",
    "notice",
    "chat",
)


class MessageIn(Strict):
    kind: Literal["message"]
    type: str
    to: str | None = None
    body: str = markdown(min_length=1)
    task_id: str | None = None
    conversation_id: str | None = None


class RedactIn(Strict):
    reason: str = markdown(min_length=1)


def load_event(conn: Connection, seq: str) -> dict[str, Any]:
    row = conn.execute(select(t.event).where(t.event.c.seq == int(seq))).one()
    return event_view(conn, row)


idempotency.LOADERS["event"] = load_event


# --- reading and waiting -------------------------------------------------------------------


def _parse_after(raw: str | None) -> int | Literal["latest"]:
    if raw is None:
        return 0
    if raw == "latest":
        return "latest"
    if not raw.isdigit():
        raise invalid({"after": "not_a_seq"})
    return int(raw)


@router.get("/projects/{slug}/events")
async def read_events(slug: str, request: Request, caller: EventsCaller) -> JSONResponse:
    wait = wait_of(request)
    after_param = _parse_after(request.query_params.get("after"))
    raw_limit = request.query_params.get("limit", str(PAGE_DEFAULT))
    if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= PAGE_MAX:
        raise invalid({"limit": "out_of_range"})
    limit = int(raw_limit)
    engine = engine_of(request)

    def start() -> tuple[Membership, int]:
        with engine.begin() as conn:
            mine = membership(conn, caller, slug)
            mine.require("project:read")
            if after_param == "latest":
                after = events.highest_readable(conn, mine.project.id, mine.row, mine.principal_id)
            else:
                after = after_param
                _acknowledge(conn, caller, after)
            return mine, after

    mine, after = await run_in_threadpool(start)
    if after_param == "latest" and wait == 0:
        # From now on, without the history; acknowledges nothing (§8.3).
        return _answer([], after, superseded=False)

    def read(waking: bool) -> tuple[list[dict[str, Any]], int]:
        with engine.begin() as conn:
            if waking:
                rows, examined = events.read_waking(
                    conn, mine.project.id, mine.row, mine.principal_id, after, limit
                )
            else:
                rows, examined, _ = events.read(
                    conn, mine.project.id, mine.row, mine.principal_id, after, limit
                )
            events.mark_delivered(conn, rows, mine.principal_id)
            cursor = rows[-1].seq if rows else max(examined, after)
            return [event_view(conn, r) for r in rows], cursor

    if wait == 0:
        items, cursor = await run_in_threadpool(read, False)
        return _answer(items, cursor, superseded=False)

    waiter = longpoll.Waiter(
        key=caller.credential_id or f"session:{caller.human_session}",
        project_id=mine.project.id,
        session_id=caller.session_id,
        loop=asyncio.get_running_loop(),
    )
    longpoll.registry.enter(waiter)
    try:
        deadline = time.monotonic() + wait
        while True:
            waiter.event.clear()  # an event after this read wakes the next wait
            items, cursor = await run_in_threadpool(read, True)
            if items or waiter.superseded:
                return _answer([] if waiter.superseded else items, cursor, waiter.superseded)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or await request.is_disconnected():
                return _answer([], cursor, superseded=False)
            with contextlib.suppress(TimeoutError):  # the fallback re-read
                await asyncio.wait_for(waiter.event.wait(), min(remaining, FALLBACK_SECONDS))
    finally:
        longpoll.registry.leave(waiter)


def _answer(items: list[dict[str, Any]], cursor: int, superseded: bool) -> JSONResponse:
    return JSONResponse(
        {
            "items": items,
            "cursor": cursor,
            "server_time": clock.rfc3339(clock.now()),
            "superseded": superseded,
        }
    )


def _acknowledge(conn: Connection, caller: Caller, after: int) -> None:
    """`after=N` acknowledges everything up to N for this session (§8.3)."""
    if caller.session_id is None or after <= 0:
        return
    conn.execute(
        update(t.agent_session)
        .where(
            t.agent_session.c.id == caller.session_id,
            t.agent_session.c.acknowledged_seq < after,
        )
        .values(acknowledged_seq=after)
    )


# --- posting messages ------------------------------------------------------------------


def chat_parties(conn: Connection, mine: Membership, agent_id: str) -> tuple[Any, Any]:
    """The agent's membership and its owning human's; both must be members (§9)."""
    agent = member_row(conn, mine.project.id, agent_id)
    if agent.agent_id is None:
        raise not_found()
    owner_id = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent.agent_id)
    ).scalar_one()
    try:
        human = member_row(conn, mine.project.id, owner_id)
    except ApiError:
        raise not_found() from None
    return agent, human


def post_message(
    conn: Connection, mine: Membership, caller: Caller, body: MessageIn
) -> dict[str, Any]:
    """Validate and emit one `message` event; returns its view."""
    if body.type not in MESSAGE_TYPES:
        raise invalid({"type": "unknown"})
    me = mine.principal_id
    if body.type == "chat":
        if body.conversation_id is None:
            raise invalid({"conversation_id": "required_for_chat"})
        try:
            agent, human = chat_parties(conn, mine, body.conversation_id)
        except ApiError:
            raise invalid({"conversation_id": "not_a_conversation"}) from None
        parties = [agent.agent_id, human.human_id]
        if me not in parties:
            raise forbidden(message="only the two parties write in a conversation")
        to = parties[1] if me == parties[0] else parties[0]
        audience = [f"member:{p}" for p in parties]
    else:
        if body.conversation_id is not None:
            raise invalid({"conversation_id": "chat_only"})
        if body.to is None:
            raise invalid({"to": "required"})
        to = body.to
        if to == "all":
            target = "all"
        elif to.startswith("role:"):
            from maity_hub.scopes import ROLES

            if to.removeprefix("role:") not in ROLES:
                raise invalid({"to": "unknown_role"})
            target = to
        else:
            try:
                member_row(conn, mine.project.id, to)
            except ApiError:
                raise invalid({"to": "not_a_member"}) from None
            target = f"member:{to}"
        audience = list(dict.fromkeys([target, f"member:{me}"]))
    if body.task_id is not None:
        found = conn.execute(
            select(t.card.c.id).where(
                t.card.c.id == body.task_id, t.card.c.project_id == mine.project.id
            )
        ).first()
        if found is None:
            raise invalid({"task_id": "unknown_task"})
    payload = {
        "type": body.type,
        "to": to,
        "body": body.body,
        "conversation_id": body.conversation_id,
        "task_id": body.task_id,
    }
    seq = events.emit(
        conn,
        mine.project.id,
        "message",
        audience,
        payload,
        actor=caller.actor(mine.id),
        subject=("task", body.task_id) if body.task_id else None,
        conversation_id=body.conversation_id,
    )
    return load_event(conn, str(seq))


@router.post("/projects/{slug}/events")
def post_event(slug: str, body: MessageIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("events:post")
        view = post_message(conn, mine, caller, body)
        return idempotency.Outcome(201, "event", str(view["seq"]), view)

    return idempotency.run(engine_of(request), request, caller, action)


# --- redaction --------------------------------------------------------------------------------


@router.post("/projects/{slug}/events/{seq}/redact")
def redact(
    slug: str, seq: int, body: RedactIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("events:admin")
        row = conn.execute(
            select(t.event).where(t.event.c.seq == seq, t.event.c.project_id == mine.project.id)
        ).first()
        if row is None:
            raise not_found()
        if not row.redacted:
            # The one mutation the log allows, itself on record (§8.5).
            tombstone = {
                "redacted": True,
                "reason": body.reason,
                "by": mine.principal_id,
                "at": clock.rfc3339(clock.now()),
            }
            conn.execute(
                update(t.event).where(t.event.c.seq == seq).values(payload=tombstone, redacted=True)
            )
            events.emit(
                conn,
                mine.project.id,
                "event_redacted",
                ["role:owner", "role:admin"],
                {"seq": seq, "reason": body.reason},
                actor=caller.actor(mine.id),
                subject=("event", str(seq)),
            )
        return idempotency.Outcome(200, "event", str(seq), load_event(conn, str(seq)))

    return idempotency.run(engine_of(request), request, caller, action)
