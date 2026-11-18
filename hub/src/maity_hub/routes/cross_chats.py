"""Cross-project group chats (docs/api.md §9.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select

from maity_hub import cross_chats, idempotency, paging
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import humans_only, invalid, not_found
from maity_hub.models import Strict, Written, markdown, title
from maity_hub.paging import SEQ_MAX

router = APIRouter()
PAGE_DEFAULT, PAGE_MAX = 50, 200


class CreateIn(Strict):
    title: str | None = title(default=None)
    participants: list[str] = Field(max_length=200)


class PatchIn(Strict):
    title: str | None = title()


class AddIn(Strict):
    member_id: str


class MessageIn(Written):
    body: str = markdown(min_length=1)
    attachments: Any = None
    to_instance: Any = None

    @field_validator("attachments", mode="before")
    @classmethod
    def _no_attachments(cls, value: Any) -> Any:
        if value is None:
            return None
        raise PydanticCustomError("not_in_cross_chat", "an attachment belongs to a project")

    @field_validator("to_instance", mode="before")
    @classmethod
    def _no_instance(cls, value: Any) -> Any:
        if value is None:
            return None
        raise PydanticCustomError("direct_chat_only", "an instance is named in a direct chat")


class RedactIn(Strict):
    reason: str = markdown(min_length=1)


def _reader_id(caller: Caller) -> str:
    if caller.kind == "human":
        assert caller.human_id is not None
        return caller.human_id
    if caller.kind == "agent":
        assert caller.agent_id is not None
        return caller.agent_id
    raise not_found()


def _owner(caller: Caller) -> str:
    if caller.kind != "human" or caller.human_id is None:
        raise humans_only("only the owning human manages a cross-project group chat")
    return caller.human_id


def _chat(conn: Any, chat_id: str) -> Any:
    row = cross_chats.find(conn, chat_id)
    if row is None:
        raise not_found()
    return row


def _visible(conn: Any, chat: Any, reader_id: str) -> dict[str, Any]:
    shown = cross_chats.view(conn, chat, reader_id)
    if shown is None:
        raise not_found()
    return shown


@router.post("/me/cross-chats")
def create_chat(body: CreateIn, request: Request, caller: AnyCaller) -> JSONResponse:
    owner_id = _owner(caller)

    def action(conn: Any) -> idempotency.Outcome:
        chat_id = cross_chats.create(conn, owner_id, body.title, body.participants)
        shown = _visible(conn, _chat(conn, chat_id), owner_id)
        return idempotency.Outcome(201, "cross_chat", chat_id, shown)

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/me/cross-chats")
def list_chats(
    request: Request,
    caller: AnyCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    reader = _reader_id(caller)
    bound = paging.scope(reader=reader)
    with engine_of(request).begin() as conn:
        return JSONResponse(
            cross_chats.listing(
                conn,
                reader,
                as_owner=caller.kind == "human",
                limit=limit,
                cursor=cursor,
                bound=bound,
            )
        )


@router.get("/me/cross-chats/{chat_id}")
def get_chat(chat_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        return JSONResponse(_visible(conn, _chat(conn, chat_id), _reader_id(caller)))


@router.patch("/me/cross-chats/{chat_id}")
def patch_chat(chat_id: str, body: PatchIn, request: Request, caller: AnyCaller) -> JSONResponse:
    owner_id = _owner(caller)

    def action(conn: Any) -> idempotency.Outcome:
        chat = _chat(conn, chat_id)
        if cross_chats.view(conn, chat, owner_id) is None:
            raise not_found()
        cross_chats.rename(conn, chat, body.title)
        shown = _visible(conn, _chat(conn, chat_id), owner_id)
        return idempotency.Outcome(200, "cross_chat", chat_id, shown)

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/me/cross-chats/{chat_id}/participants")
def add_participant(chat_id: str, body: AddIn, request: Request, caller: AnyCaller) -> JSONResponse:
    owner_id = _owner(caller)

    def action(conn: Any) -> idempotency.Outcome:
        chat = _chat(conn, chat_id)
        if cross_chats.view(conn, chat, owner_id) is None:
            raise not_found()
        cross_chats.add(conn, chat, body.member_id)
        shown = _visible(conn, _chat(conn, chat_id), owner_id)
        return idempotency.Outcome(200, "cross_chat", chat_id, shown)

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/me/cross-chats/{chat_id}/participants/{member_id}")
def remove_participant(
    chat_id: str, member_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    reader = _reader_id(caller)

    def action(conn: Any) -> idempotency.Outcome:
        chat = _chat(conn, chat_id)
        if caller.kind == "agent" and member_id != reader:
            raise humans_only("an agent leaves only itself")
        if cross_chats.view(conn, chat, reader) is None:
            raise not_found()
        current = cross_chats.stay(conn, chat.id, member_id)
        if current is not None:
            cross_chats.refuse_closed(chat)
            ended = cross_chats.end_stay(
                conn, chat, member_id, reader, "left" if member_id == reader else "removed"
            )
        else:
            ended = cross_chats.last_stay(conn, chat.id, member_id)
        if ended is None:
            raise not_found()
        return idempotency.Outcome(
            200, "cross_participation", str(ended.id), cross_chats.participation(ended)
        )

    return idempotency.run(engine_of(request), request, caller, action)


def _load_chat(conn: Any, chat_id: str, request: Request) -> dict[str, Any]:
    caller: Caller = request.state.caller
    return _visible(conn, _chat(conn, chat_id), _reader_id(caller))


def _load_participation(conn: Any, stay_id: str, _request: Request) -> dict[str, Any]:
    from maity_hub import tables as t

    row = conn.execute(
        select(t.cross_chat_participant).where(t.cross_chat_participant.c.id == int(stay_id))
    ).one()
    return cross_chats.participation(row)


def _sees_chat(conn: Any, chat_id: str, caller: Caller) -> bool:
    """As the chat's GET (§9.5): a chat the caller reads now."""
    if caller.kind not in ("human", "agent"):
        return False
    chat = cross_chats.find(conn, chat_id)
    return chat is not None and cross_chats.view(conn, chat, _reader_id(caller)) is not None


def _sees_stay(conn: Any, stay_id: str, caller: Caller) -> bool:
    """One's own stay, the one a leave ended included, or a stay in a chat the caller reads."""
    from maity_hub import tables as t

    row = conn.execute(
        select(t.cross_chat_participant).where(t.cross_chat_participant.c.id == int(stay_id))
    ).first()
    if row is None or caller.kind not in ("human", "agent"):
        return False
    return row.member_id == _reader_id(caller) or _sees_chat(conn, row.conversation_id, caller)


def _sees_message(conn: Any, message_id: str, caller: Caller) -> bool:
    from maity_hub import tables as t

    chat_id = conn.execute(
        select(t.cross_chat_message.c.conversation_id).where(
            t.cross_chat_message.c.id == message_id
        )
    ).scalar()
    return chat_id is not None and _sees_chat(conn, chat_id, caller)


idempotency.register("cross_chat", _load_chat, _sees_chat)
idempotency.register("cross_participation", _load_participation, _sees_stay)


@router.get("/me/cross-chats/{chat_id}/messages")
def read_messages(
    chat_id: str,
    request: Request,
    caller: AnyCaller,
    after: int | None = Query(default=None, ge=0, le=SEQ_MAX),
    before: int | None = Query(default=None, ge=1, le=SEQ_MAX),
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
) -> JSONResponse:
    if after is not None and before is not None:
        raise invalid({"before": "with_after"}, "after or before, not both")
    with engine_of(request).begin() as conn:
        chat = _chat(conn, chat_id)
        return JSONResponse(
            cross_chats.messages(
                conn, chat, _reader_id(caller), after=after, before=before, limit=limit
            )
        )


@router.post("/me/cross-chats/{chat_id}/messages")
def post_message(
    chat_id: str, body: MessageIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Any) -> idempotency.Outcome:
        chat = _chat(conn, chat_id)
        shown = cross_chats.post(conn, caller, chat, body.body)
        return idempotency.Outcome(201, "cross_message", shown["id"], shown)

    return idempotency.run(engine_of(request), request, caller, action)


def _load_message(conn: Any, message_id: str, request: Request) -> dict[str, Any]:
    from maity_hub import tables as t

    row = conn.execute(
        select(t.cross_chat_message).where(t.cross_chat_message.c.id == message_id)
    ).one()
    caller: Caller = request.state.caller
    chat = _chat(conn, row.conversation_id)
    reader = _reader_id(caller)
    if cross_chats.view(conn, chat, reader) is None:
        raise not_found()
    return cross_chats.message_view(row, show_reason=reader == chat.owner_id)


idempotency.register("cross_message", _load_message, _sees_message)


@router.post("/me/cross-chats/{chat_id}/messages/{message_id}/redact")
def redact_message(
    chat_id: str, message_id: str, body: RedactIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    owner_id = _owner(caller)

    def action(conn: Any) -> idempotency.Outcome:
        chat = _chat(conn, chat_id)
        if cross_chats.view(conn, chat, owner_id) is None:
            raise not_found()
        row = cross_chats.message_row(conn, chat_id, message_id)
        if row is None:
            raise not_found()
        shown = cross_chats.redact(conn, chat, row, body.reason, owner_id)
        return idempotency.Outcome(200, "cross_message", message_id, shown)

    return idempotency.run(engine_of(request), request, caller, action)
