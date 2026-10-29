"""`/admin/settings/legal` for the instance admin and the public `GET /legal` (docs/api.md
§16.7.1). The pages themselves are served as HTML by the hub (§16.7.1, `routes/pages.py`)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection

from maity_hub import legal
from maity_hub.admin import instance_admin_id
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import forbidden
from maity_hub.landing import etag

router = APIRouter()


def _require_admin(conn: Connection, caller: HumanCaller) -> None:
    if caller.principal_id != instance_admin_id(conn):
        raise forbidden("instance:admin")


@router.get("/admin/settings/legal")
def get_legal_settings(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        return JSONResponse(legal.stored(conn))


@router.patch("/admin/settings/legal")
def patch_legal_settings(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        change = legal.check(body)  # after who may edit: a refusal never tells a stranger a rule
        legal.lock(conn)  # before the read: a version is decided on the setting as locked
        legal.apply(conn, change, caller.principal_id)
        return JSONResponse(legal.stored(conn))


@router.get("/legal")
def get_legal(request: Request) -> Response:
    """Unauthenticated, on the public host only (the join host never routes here): which
    pages are set and in which languages, without the text, for the dashboard's links."""
    with engine_of(request).begin() as conn:
        body = legal.public(legal.stored(conn))
    tag = etag(body)
    headers = {"Cache-Control": "public, max-age=60", "ETag": tag}
    wanted = request.headers.get("if-none-match", "")
    if tag in [part.strip() for part in wanted.split(",")]:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)
