"""`/me/forge` and `/forge/github/setup` (docs/api.md §11.4): a human's links to
installations of the instance's GitHub App.

Links are the human's own: readable by them alone, never by an instance admin, an
agent or a runner. Starting a link needs a dashboard session, which the `state` is
bound to; the setup is that session's browser coming back from the forge.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import Field

from maity_hub import forge, forge_links, forge_tokens
from maity_hub.auth import second_factor
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, not_found
from maity_hub.github_app import GitHubApp
from maity_hub.models import Strict

router = APIRouter()

SETTINGS_PAGE = "/#/settings/forge"


def _human(caller: Caller) -> tuple[str, str]:
    """The human and their dashboard session; an agent is `humans_only`."""
    if caller.kind == "agent":
        raise humans_only("forge access is a human's own")
    if caller.kind != "human" or caller.human_session is None:
        raise forbidden(message="forge access needs a dashboard session")
    return caller.principal_id, caller.human_session


def _app(request: Request) -> GitHubApp:
    app = settings_of(request).github_app
    if app is None:
        raise _refusal("forge_app_missing")
    return app


@router.post("/me/forge/github/link")
def start_link(request: Request, caller: AnyCaller) -> JSONResponse:
    human_id, session = _human(caller)
    app = _app(request)
    with engine_of(request).begin() as conn:
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        url = forge_links.start(conn, app, human_id, session)
    return JSONResponse({"url": url})


@router.get("/forge/github/setup")
def setup(
    request: Request,
    caller: AnyCaller,
    installation_id: int = Query(ge=1, le=2**53),
    code: str = Query(min_length=1, max_length=512),
    state: str = Query(min_length=1, max_length=512),
) -> Response:
    """The forge sends the browser back here: every outcome is a 303 to the dashboard's
    forge settings, `?error=<reason>` when the link failed, never a code, state or token
    in the URL. A client that asks for JSON gets the reasons as 403 or 409 instead."""
    human_id, session = _human(caller)
    wants_json = "application/json" in request.headers.get("accept", "")
    app = settings_of(request).github_app
    engine = engine_of(request)
    try:
        if app is None:
            raise forge_links.LinkError("forge_app_missing")
        with engine.begin() as conn:
            forge_links.take_state(conn, state, human_id, session)
        found = forge_links.verify(app, installation_id, code)
        with engine.begin() as conn:
            link_id = forge_links.link(conn, human_id, found)
            row = forge_links.row(conn, link_id)
    except forge_links.LinkError as error:
        if wants_json:
            raise _refusal(error.reason) from None
        return _back(request, {"error": error.reason})
    except forge.ForgeUnavailableError:
        if wants_json:
            raise ApiError(503, "forge_unavailable", "the forge did not answer") from None
        return _back(request, {"error": "forge_unavailable"})
    if wants_json:
        return JSONResponse(forge_links.view(row, [], row.status))
    return _back(request, {})


def _refusal(reason: str) -> ApiError:
    if reason == "forge_app_missing":
        return ApiError(409, "forge_app_missing", "the instance has no GitHub App configured")
    if reason == "installation_linked":
        return ApiError(
            409, "conflict", "the installation is linked to another human", {"reason": reason}
        )
    return ApiError(403, "forbidden", "the installation is not linked", {"reason": reason})


def _back(request: Request, query: dict[str, str]) -> RedirectResponse:
    base = settings_of(request).public_url
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(f"{base}{SETTINGS_PAGE}{suffix}", status_code=303)


@router.get("/me/forge")
def list_links(request: Request, caller: AnyCaller) -> JSONResponse:
    human_id, _ = _human(caller)
    app = settings_of(request).github_app
    engine = engine_of(request)
    with engine.connect() as conn:
        rows = forge_links.rows(conn, human_id)
    with engine.connect() as conn:
        token = forge_tokens.view(conn, human_id)
    links: list[dict[str, Any]] = []
    for row in rows:
        repositories, gone = forge_links.shown(app, row)
        if gone is not None and gone != row.status:
            with engine.begin() as conn:
                forge_links.set_status(conn, row.id, gone)
        links.append(forge_links.view(row, repositories, gone or row.status))
    return JSONResponse(
        {
            "app_configured": app is not None,
            "links": links,
            "token": token,
        }
    )


@router.delete("/me/forge/github/links/{link_id}")
def delete_link(link_id: str, request: Request, caller: AnyCaller) -> Response:
    human_id, _ = _human(caller)
    with engine_of(request).begin() as conn:
        if not forge_links.unlink(conn, settings_of(request).github_app, human_id, link_id):
            raise not_found()
    return Response(status_code=204)


class TokenIn(Strict):
    token: str = Field(min_length=1, max_length=255, repr=False)


@router.put("/me/forge/github/token")
def put_token(body: TokenIn, request: Request, caller: AnyCaller) -> JSONResponse:
    """Store the human's own fine-grained token, checked with the forge first; it is
    never returned."""
    human_id, _ = _human(caller)
    key = forge_tokens.require_key(settings_of(request).secret_key)
    with engine_of(request).begin() as conn:  # before the token goes to the forge
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
    try:
        login = forge_tokens.login_of(body.token)
    except forge.ForgeUnavailableError:
        raise ApiError(503, "forge_unavailable", "the forge did not answer") from None
    with engine_of(request).begin() as conn:
        forge_tokens.store(conn, key, human_id, body.token, login)
    return JSONResponse({"configured": True, "login": login})


@router.delete("/me/forge/github/token")
def delete_token(request: Request, caller: AnyCaller) -> Response:
    human_id, _ = _human(caller)
    with engine_of(request).begin() as conn:
        if not forge_tokens.remove(conn, human_id):
            raise not_found()
    return Response(status_code=204)
