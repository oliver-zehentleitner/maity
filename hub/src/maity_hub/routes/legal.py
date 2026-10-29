"""`/admin/settings/legal` for the instance admin and the public `GET /legal` (docs/api.md
§16.7.1). The pages themselves are served as HTML by the hub (§16.7.1, `routes/pages.py`)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import Connection

from maity_hub import clock, landing, legal, previews, render
from maity_hub.admin import instance_admin_id
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import forbidden, invalid
from maity_hub.landing import etag
from maity_hub.routes.pages import LEGAL_CSP

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


@router.post("/admin/settings/legal/preview", status_code=201)
def create_legal_preview(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()], page: str = ""
) -> JSONResponse:
    """A draft of one legal page, seen before it is saved (§16.7.1): the body `PATCH` takes for
    that page, or just the page's languages; nothing is saved and no limit is counted."""
    if page not in legal.PAGES:
        raise invalid({"page": "invalid"})
    languages = body.get(page) if page in body else body
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        change = legal.check({page: languages})
        if change.languages is None:
            raise invalid({page: "invalid"})
        draft_id, expires = previews.create(
            conn, caller.human_session or "", "legal", change.languages, page
        )
    base = settings_of(request).public_url.rstrip("/")
    return JSONResponse(
        {
            "id": draft_id,
            "url": f"{base}/api/v1/admin/settings/legal/preview/{draft_id}",
            "expires_at": clock.rfc3339(expires),
        },
        status_code=201,
    )


@router.get("/admin/settings/legal/preview/{draft_id}", response_class=HTMLResponse)
def show_legal_preview(
    draft_id: str, request: Request, caller: HumanCaller, lang: str | None = None
) -> Response:
    """The page the hub would serve for that draft, with "Draft" where it says "as of …"
    and no list of earlier versions."""
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        row = previews.read(conn, draft_id, caller.human_session or "", "legal")
        texts = row.payload
        setting = legal.stored(conn)
        chosen = render.choose_language(
            list(texts), setting["default_language"], lang, request.headers.get("accept-language")
        )
        body = render.legal_document(
            page=row.page,
            lang=chosen,
            title=texts[chosen]["title"],
            source=texts[chosen]["markdown"],
            version=None,
            earlier=[],
            current=None,
            languages=list(texts),
            legal=legal.public(setting),
            setting=landing.stored(conn),
            public_url=settings_of(request).public_url,
        )
    return HTMLResponse(
        body,
        headers={
            "Content-Security-Policy": LEGAL_CSP,
            "X-Robots-Tag": "noindex",
            "Cache-Control": "no-store",
        },
    )
