"""`/me/chat-access` (docs/api.md §9.6, "The lists"): a human's allow and deny entries for their
agents. Only that human reads and changes them; an agent is `humans_only`, since an agent does
not open its own door. Every change settles the owner's chats again (`chat_gate.recheck`): an
agent an entry no longer covers waits, one a new entry covers is admitted, one a deny entry
stops leaves."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from maity_hub import chat_access, chat_gate, events, idempotency
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import forbidden, humans_only
from maity_hub.models import Strict

router = APIRouter()

# A repeat with the same `Idempotency-Key` answers what the first call answered (§1.5).
idempotency.LOADERS["chat_access"] = idempotency.plain(chat_access.replayed)

CACHE = "private, no-store"


class AllowIn(Strict):
    """Checked by `chat_access`: a field sent as `null` differs from one not sent."""

    agents: Any = None
    owner_id: Any = None
    project: Any = None
    their_agents: Any = None
    their_human: Any = None
    duration: Any = None
    allowed: Any = None
    denied: Any = None


class AllowPatch(Strict):
    agents: Any = None
    their_agents: Any = None
    their_human: Any = None
    duration: Any = None
    allowed: Any = None
    denied: Any = None


class DenyIn(Strict):
    agents: Any = None
    owner_id: Any = None
    human_id: Any = None
    agent_id: Any = None
    project: Any = None


def _caller(caller: AnyCaller) -> str:
    if caller.kind == "agent":
        raise humans_only("an agent does not open its own door")
    if caller.kind != "human" or caller.human_id is None:
        raise forbidden()
    return caller.human_id


def _sent(body: Strict) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


@router.get("/me/chat-access")
def listing(request: Request, caller: AnyCaller, agent: str | None = None) -> JSONResponse:
    me = _caller(caller)
    with engine_of(request).connect() as conn:
        body = chat_access.listing(conn, me, agent)
    return JSONResponse(body, headers={"Cache-Control": CACHE})


@router.post("/me/chat-access/allow")
def create_allow(body: AllowIn, request: Request, caller: AnyCaller) -> JSONResponse:
    me = _caller(caller)
    sent = _sent(body)
    chat_access.lock_rows(engine_of(request), me, sent.get("owner_id"))

    def action(conn: Connection) -> idempotency.Outcome:
        entry_id = chat_access.create_allow(conn, me, sent)
        chat_gate.recheck(conn, me)
        entry = chat_access.one(conn, me, chat_access.ALLOW, entry_id)
        return idempotency.Outcome(201, "chat_access", entry_id, entry)

    return idempotency.run(engine_of(request), request, caller, action)


@router.patch("/me/chat-access/allow/{entry_id}")
def patch_allow(
    entry_id: str, body: AllowPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    me = _caller(caller)
    sent = _sent(body)

    def action(conn: Connection) -> idempotency.Outcome:
        chat_access.patch_allow(conn, me, entry_id, sent)
        chat_gate.recheck(conn, me)
        entry = chat_access.one(conn, me, chat_access.ALLOW, entry_id)
        return idempotency.Outcome(200, "chat_access", entry_id, entry)

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/me/chat-access/deny")
def create_deny(body: DenyIn, request: Request, caller: AnyCaller) -> JSONResponse:
    me = _caller(caller)
    sent = _sent(body)
    chat_access.lock_rows(engine_of(request), me, sent.get("owner_id"), sent.get("human_id"))

    def action(conn: Connection) -> idempotency.Outcome:
        entry_id = chat_access.create_deny(conn, me, sent)
        chat_gate.recheck(conn, me)
        entry = chat_access.one(conn, me, chat_access.DENY, entry_id)
        return idempotency.Outcome(201, "chat_access", entry_id, entry)

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/me/chat-access/allow/{entry_id}")
def delete_allow(entry_id: str, request: Request, caller: AnyCaller) -> Response:
    me = _caller(caller)
    with events.transaction(engine_of(request)) as conn:
        chat_access.delete_entry(conn, me, chat_access.ALLOW, entry_id)
        chat_gate.recheck(conn, me)
    return Response(status_code=204)


@router.delete("/me/chat-access/deny/{entry_id}")
def delete_deny(entry_id: str, request: Request, caller: AnyCaller) -> Response:
    me = _caller(caller)
    with events.transaction(engine_of(request)) as conn:
        chat_access.delete_entry(conn, me, chat_access.DENY, entry_id)
        chat_gate.recheck(conn, me)
    return Response(status_code=204)
