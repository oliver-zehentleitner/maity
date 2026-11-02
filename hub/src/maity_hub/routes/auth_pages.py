"""`/admin/settings/auth-pages` and `GET /auth/pages/{page}` (docs/api.md §16.7.4)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, Response

from maity_hub import auth_pages, landing
from maity_hub.admin import require_instance_admin
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import not_found

router = APIRouter()


@router.get("/admin/settings/auth-pages")
def get_auth_pages(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        return JSONResponse(auth_pages.view(conn))


@router.patch("/admin/settings/auth-pages")
def patch_auth_pages(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        auth_pages.save(conn, auth_pages.check(body), caller.principal_id)
        return JSONResponse(auth_pages.view(conn))


@router.post("/admin/settings/auth-pages/check", status_code=204)
def check_auth_pages(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> Response:
    """Refuses as the `PATCH` would and stores nothing, so it asks for no second factor."""
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
    auth_pages.check(body)
    return Response(status_code=204)


@router.get("/auth/pages/{page}")
def get_auth_page(page: str, request: Request, lang: str | None = None) -> Response:
    """Unauthenticated, on the public host only (the join host never routes here)."""
    if page not in auth_pages.PAGES:
        raise not_found()
    with engine_of(request).begin() as conn:
        setting = auth_pages.stored(conn)
    body = auth_pages.public(setting, page, lang, request.headers.get("accept-language"))
    tag = landing.etag(body)
    headers = {"Cache-Control": "public, max-age=60", "ETag": tag, "Vary": "Accept-Language"}
    wanted = request.headers.get("if-none-match", "")
    if tag in [part.strip() for part in wanted.split(",")]:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)
