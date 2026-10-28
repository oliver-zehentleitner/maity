"""`/admin/settings/landing` for the instance admin and the public `GET /landing`
(docs/api.md §16.7). The public answer is the same for every visitor, carries no author,
and may be cached for a minute."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection

from maity_hub import landing
from maity_hub.admin import instance_admin_id
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import forbidden

router = APIRouter()


def _require_admin(conn: Connection, caller: HumanCaller) -> None:
    if caller.principal_id != instance_admin_id(conn):
        raise forbidden("instance:admin")


def _admin_view(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in (*landing.FIELDS, "updated_at", "updated_by")}


@router.get("/admin/settings/landing")
def get_landing_settings(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        return JSONResponse(_admin_view(landing.stored(conn)))


@router.patch("/admin/settings/landing")
def patch_landing_settings(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        landing.lock(conn)  # before the read: the edit decides on the setting as locked
        after = landing.check(body, landing.stored(conn))
        landing.save(conn, after, caller.principal_id)
        return JSONResponse(_admin_view(landing.stored(conn)))


@router.get("/landing")
def get_landing(request: Request) -> Response:
    """Unauthenticated, on the public host only (the join host never routes here)."""
    with engine_of(request).begin() as conn:
        body = landing.public(landing.stored(conn))
    tag = landing.etag(body)
    headers = {"Cache-Control": "public, max-age=60", "ETag": tag}
    wanted = request.headers.get("if-none-match", "")
    if tag in [part.strip() for part in wanted.split(",")]:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)
