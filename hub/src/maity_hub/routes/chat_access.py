"""`/me/chat-access` (docs/api.md §9.6, "The lists"): a human's allow and deny entries for their
agents. Only that human reads and changes them; an agent is `humans_only`, since an agent does
not open its own door."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from maity_hub import chat_access
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import forbidden, humans_only
from maity_hub.models import Strict

router = APIRouter()

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
    with engine_of(request).begin() as conn:
        entry_id = chat_access.create_allow(conn, me, sent)
        entry = chat_access.one(conn, me, chat_access.ALLOW, entry_id)
    return JSONResponse(entry, status_code=201)


@router.patch("/me/chat-access/allow/{entry_id}")
def patch_allow(
    entry_id: str, body: AllowPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    me = _caller(caller)
    with engine_of(request).begin() as conn:
        chat_access.patch_allow(conn, me, entry_id, _sent(body))
        entry = chat_access.one(conn, me, chat_access.ALLOW, entry_id)
    return JSONResponse(entry)


@router.post("/me/chat-access/deny")
def create_deny(body: DenyIn, request: Request, caller: AnyCaller) -> JSONResponse:
    me = _caller(caller)
    sent = _sent(body)
    chat_access.lock_rows(engine_of(request), me, sent.get("owner_id"), sent.get("human_id"))
    with engine_of(request).begin() as conn:
        entry_id = chat_access.create_deny(conn, me, sent)
        entry = chat_access.one(conn, me, chat_access.DENY, entry_id)
    return JSONResponse(entry, status_code=201)


@router.delete("/me/chat-access/allow/{entry_id}")
def delete_allow(entry_id: str, request: Request, caller: AnyCaller) -> Response:
    me = _caller(caller)
    with engine_of(request).begin() as conn:
        chat_access.delete_entry(conn, me, chat_access.ALLOW, entry_id)
    return Response(status_code=204)


@router.delete("/me/chat-access/deny/{entry_id}")
def delete_deny(entry_id: str, request: Request, caller: AnyCaller) -> Response:
    me = _caller(caller)
    with engine_of(request).begin() as conn:
        chat_access.delete_entry(conn, me, chat_access.DENY, entry_id)
    return Response(status_code=204)
