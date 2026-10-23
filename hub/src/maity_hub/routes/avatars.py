"""`/avatars/{id}`, `/me/avatar` and `/agents/{id}/avatar` (docs/api.md §6.10).

`GET` serves the stored picture to the callers §6.10 lists and is `not_found` for
everyone else, before `If-None-Match` is compared. `PUT` takes the raw image, has it
decoded and encoded again outside the transaction, and stores the result; `DELETE`
removes the upload. A human uses the cookie session; an agent credential sets its own
profile's picture, paused or not, in a closed project or not.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from maity_hub import avatars, idempotency, images
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.routes.agents import owned
from maity_hub.routes.project_images import _matches

router = APIRouter()

idempotency.LOADERS["avatar"] = idempotency.plain(avatars.state)


@router.get("/avatars/{member_id}")
def get_avatar(member_id: str, request: Request, caller: AnyCaller) -> Response:
    with engine_of(request).begin() as conn:
        found = (
            avatars.current(conn, member_id) if avatars.may_read(conn, caller, member_id) else None
        )
    if found is None:  # whether it exists is not told: authorized first, then compared
        raise not_found()
    data, tag = found
    headers = {**avatars.HEADERS, "ETag": tag}
    if _matches(request.headers.get("if-none-match"), tag):
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/png", headers=headers)


def _me(caller: Caller) -> str:
    if caller.kind not in ("human", "agent"):
        raise forbidden()
    return caller.principal_id


def _change(
    request: Request,
    caller: Caller,
    owner_id: str,
    check: Callable[[Connection], None] | None = None,
) -> JSONResponse:
    """A `PUT` (with a body) or `DELETE` of `owner_id`'s upload."""
    engine = engine_of(request)
    replayed = idempotency.replay_first(engine, request, caller)
    if replayed is not None:  # a repeat is the stored answer: no decode, no count (§6.10)
        return replayed
    png = None
    if request.method == "PUT":
        data: bytes = request.scope["state"].get("body", b"")
        declared = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if len(data) > images.CAP:
            raise invalid({"body": "too_large"}, "the image is over 1 MiB")
        sniffed = images.sniff(data)
        if sniffed is None or declared != sniffed:
            raise invalid({"body": "unsupported_type"}, "PNG, JPEG or WebP only")
        avatars.check_rate(owner_id)
        try:
            png = avatars.decode(settings_of(request), data, sniffed)
        except ApiError as refused:
            if refused.status == 400:  # a refused image counts as a change tried
                avatars.count_change(None, owner_id)
            raise

    def action(conn: Connection) -> idempotency.Outcome:
        if check is not None:
            check(conn)
        avatars.count_change(conn, owner_id)  # given back if this transaction rolls back
        avatars.lock_owner(conn, owner_id)
        before = avatars.state(conn, owner_id)
        if png is None:
            avatars.remove_upload(conn, owner_id)
        else:
            avatars.store_upload(conn, owner_id, png)
        avatars.announce(conn, owner_id, before, caller)
        return idempotency.Outcome(200, "avatar", owner_id, avatars.state(conn, owner_id))

    return idempotency.run(engine, request, caller, action)


@router.put("/me/avatar")
def put_my_avatar(request: Request, caller: AnyCaller) -> JSONResponse:
    return _change(request, caller, _me(caller))


@router.delete("/me/avatar")
def delete_my_avatar(request: Request, caller: AnyCaller) -> JSONResponse:
    return _change(request, caller, _me(caller))


def _owners_agent(agent_id: str, caller: Caller) -> Callable[[Connection], None]:
    def check(conn: Connection) -> None:
        owned(conn, agent_id, caller.principal_id)

    return check


@router.put("/agents/{agent_id}/avatar")
def put_agent_avatar(agent_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        owned(conn, agent_id, caller.principal_id)  # before anything is decoded
    return _change(request, caller, agent_id, _owners_agent(agent_id, caller))


@router.delete("/agents/{agent_id}/avatar")
def delete_agent_avatar(agent_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    return _change(request, caller, agent_id, _owners_agent(agent_id, caller))
