"""`/admin/settings/landing` for the instance admin and the public `GET /landing`
(docs/api.md §16.7). The public answer is the same for every visitor, carries no author,
and may be cached for a minute."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import Connection

from maity_hub import campaigns, clock, landing, landing_stats, legal, previews, render
from maity_hub.admin import instance_admin_id
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import forbidden, invalid, not_found
from maity_hub.routes.pages import LANDING_CSP

router = APIRouter()


def _require_admin(conn: Connection, caller: HumanCaller) -> None:
    if caller.principal_id != instance_admin_id(conn):
        raise forbidden("instance:admin")


def _admin_view(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in (*landing.ADMIN_FIELDS, "updated_at", "updated_by")}


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
        setting = landing.stored(conn)
        body = landing.public(setting)
        if body["enabled"]:  # the counters an enabled `stats` section names, shared (§16.7)
            body["stats"] = landing_stats.published(conn, setting)
    tag = landing.etag(body)
    headers = {"Cache-Control": "public, max-age=60", "ETag": tag}
    wanted = request.headers.get("if-none-match", "")
    if tag in [part.strip() for part in wanted.split(",")]:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)


@router.post("/admin/settings/landing/preview", status_code=201)
def create_landing_preview(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    """A draft, seen before it is saved (§16.7): the body a `PATCH` takes, a field it leaves
    out from the saved setting, `enabled` ignored; nothing is saved."""
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        draft = {k: v for k, v in body.items() if k != "enabled"}
        # Checked as an enabled page: a draft has to have a page to show in its language.
        after = landing.check({**draft, "enabled": True}, landing.stored(conn))
        payload = {k: after[k] for k in ("default_language", "pages", "footer", "variants")}
        draft_id, expires = previews.create(conn, caller.human_session or "", "landing", payload)
    return JSONResponse(
        {
            "id": draft_id,
            "url": f"/api/v1/admin/settings/landing/preview/{draft_id}",
            "expires_at": clock.rfc3339(expires),
        },
        status_code=201,
    )


@router.get("/admin/settings/landing/preview/{draft_id}", response_class=HTMLResponse)
def show_landing_preview(
    draft_id: str,
    request: Request,
    caller: HumanCaller,
    lang: str | None = None,
    variant: str | None = None,
) -> Response:
    """The page the hub would serve at `/` for that draft: the served page's own policy,
    `no-store`, `noindex`; another session's draft, an expired one and an unknown one are
    `not_found`."""
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        row = previews.read(conn, draft_id, caller.human_session or "", "landing")
        draft = row.payload
        # The draft of a variant (`?variant=<slug>`), else the main page's; a slug the draft does
        # not have is `not_found`, like an unknown draft.
        if variant is not None and variant not in draft.get("variants", {}):
            raise not_found()
        pages = draft["variants"][variant]["pages"] if variant else draft["pages"]
        # No `Accept-Language`: without `lang` the draft's own default language (§16.7).
        chosen = render.choose_language(list(pages), draft["default_language"], lang, None)
        setting = {**landing.stored(conn), **draft}
        body = render.landing_document(
            setting,
            chosen,
            public_url=settings_of(request).public_url,
            legal=legal.public(legal.stored(conn)),
            stats=landing_stats.current(conn) if landing_stats.named(setting) else None,
            preview=True,
            variant=variant,
        )
    return HTMLResponse(
        body,
        headers={
            "Content-Security-Policy": LANDING_CSP,
            "X-Robots-Tag": "noindex",
            "Cache-Control": "no-store",
        },
    )


@router.get("/admin/statistics/campaigns")
def campaign_statistics(
    request: Request, caller: HumanCaller, days: int = campaigns.DEFAULT_DAYS, format: str = "json"
) -> Response:
    """What the hub counted per variant and campaign (§16.7.2): the rows with a non-zero sum,
    newest day first, as JSON or, with `format=csv`, as an attachment. The counts, not which
    variant won: that is the reader's."""
    problems: dict[str, str] = {}
    if not 1 <= days <= campaigns.MAX_DAYS:
        problems["days"] = "invalid"
    if format not in ("json", "csv"):
        problems["format"] = "invalid"
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        if problems:
            raise invalid(problems)
        found = campaigns.statistics(conn, days)
    if format == "csv":
        return Response(
            campaigns.as_csv(found),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="campaigns.csv"'},
        )
    return JSONResponse(found)
