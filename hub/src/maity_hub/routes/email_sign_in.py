"""Mailed first factors: anonymous request, browser-bound code, scanner-safe link (§2.6)."""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select

from maity_hub import clock, paths
from maity_hub import tables as t
from maity_hub.auth import email_links as links
from maity_hub.auth import second_factor, sessions, sign_in_settings
from maity_hub.auth.caller import (
    SESSION_COOKIE,
    require_secure_transport,
    session_alive,
    session_id_hash,
)
from maity_hub.config import Settings
from maity_hub.deps import engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, rate_limited
from maity_hub.mail import address, outbox
from maity_hub.notifications import preferences, tokens
from maity_hub.routes import auth, device_codes

router = APIRouter(prefix="/auth")
page_router = APIRouter()
LIMITS = links.RequestLimits()
FORM_COOKIE = "maity_form"
FORM_PATH = "/mail/sign-in"


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(max_length=254)
    next: str | None = None


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=128)


def _enabled(conn: Connection, hub: Settings) -> None:
    if not sign_in_settings.email_link_enabled(conn, hub):
        raise ApiError(
            403, "forbidden", "mail sign-in is switched off", {"reason": "method_disabled"}
        )


def _anonymous(request: Request) -> None:
    device_codes._anonymous(request)
    presented = request.cookies.get(SESSION_COOKIE)
    if not presented:
        return
    with engine_of(request).connect() as conn:
        row = conn.execute(
            select(t.human_session).where(t.human_session.c.id_hash == session_id_hash(presented))
        ).first()
    if row is not None and row.ended_at is None and session_alive(row, clock.now()):
        given = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(given.encode(), row.csrf_token.encode()):
            raise ApiError(403, "csrf_mismatch", "X-CSRF-Token does not match the session")


@router.post("/email-link")
def request_link(body: LinkRequest, request: Request, background: BackgroundTasks) -> JSONResponse:
    _anonymous(request)
    hub, engine = settings_of(request), engine_of(request)
    with engine.begin() as conn:
        _enabled(conn, hub)
    origin = origin_of(request)
    wait, allowed = LIMITS.take(body.address, origin.address)
    if wait:
        raise rate_limited(wait)
    pending = secrets.token_urlsafe(32)
    requested_at = clock.now()
    if allowed:
        background.add_task(
            deliver,
            engine,
            hub,
            body.address,
            pending,
            origin.address,
            paths.safe_next(body.next),
            request.headers.get("user-agent"),
            requested_at,
        )
    response = JSONResponse({"expires_in": 900}, status_code=202)
    response.set_cookie(
        device_codes.PENDING_COOKIE,
        pending,
        max_age=900,
        path=device_codes.PENDING_PATH,
        secure=origin.tls,
        httponly=True,
        samesite="strict",
    )
    return response


def _eligible(conn: Connection, hub: Settings, human_id: str, epoch: int | None = None) -> Any:
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    row = conn.execute(
        select(t.notification_settings)
        .where(t.notification_settings.c.human_id == human_id)
        .with_for_update()
    ).first()
    if (
        human is None
        or human.account_status != "active"
        or human.suspended_at is not None  # no way in for a suspended account (§16.8)
        or row is None
        or row.address_status != "verified"
        or row.address is None
        or (epoch is not None and epoch != row.epoch)
        or not preferences.preferences(conn, human_id)["email"]["sign_in_link"]
        or not sign_in_settings.view(conn, hub)["email_link_available"]
    ):
        return None
    return row


def deliver(
    engine: Engine,
    hub: Settings,
    given: str,
    pending: str,
    source: str,
    next_path: str,
    user_agent: str | None,
    requested_at: datetime,
) -> None:
    """Runs after the response is sent; no lookup of an address on the response path."""
    if not address.valid(given.strip()):
        return
    with engine.begin() as conn:
        human_id = conn.execute(
            select(t.notification_settings.c.human_id).where(
                t.notification_settings.c.address_normalized == address.normalized(given)
            )
        ).scalar()
        if human_id is None:
            return
        links.lock_human(conn, human_id)
        row = _eligible(conn, hub, human_id)
        # The address may have changed after the non-locking lookup.
        if row is None or row.address_normalized != address.normalized(given):
            return
        key = hub.mail.signing_key
        assert key is not None
        issued = links.issue(
            conn,
            human_id=human_id,
            address_epoch=row.epoch,
            pending=pending,
            source=source,
            next_path=next_path,
            signing_key=key,
            requested_at=requested_at,
        )
        if issued is None:
            return
        token = tokens.make(
            key,
            {
                "h": human_id,
                "p": "sign_in",
                "n": issued.nonce,
                "x": int(issued.expires_at.timestamp()),
            },
        )
        human = conn.execute(select(t.human).where(t.human.c.id == human_id)).one()
        language = preferences.preferences(conn, human_id)["email"]["language"]
        browser, system = sessions.describe(user_agent)
        body = links.mail_body(
            language=language,
            display_name=human.display_name,
            link=f"{hub.public_url.rstrip('/')}/mail/sign-in/{token}",
            code=issued.code,
            requested_at=clock.rfc3339(requested_at),
            browser=browser,
            system=system,
            address=source,
        )
        outbox.enqueue(
            conn,
            kind="sign_in",
            to=row.address,
            human_id=human_id,
            subject="[Maity] Anmeldelink" if language == "de" else "[Maity] Sign-in link",
            body=body,
        )


def _complete(
    conn: Connection, request: Request, row: Any, method: str
) -> tuple[dict[str, Any], str, str, str | None]:
    auth.end_presented(conn, request.cookies.get(SESSION_COOKIE))
    sid, csrf, _, state = second_factor.begin(
        conn,
        settings_of(request),
        row.human_id,
        method=method,  # `email_link` or `email_code` (§2.6.5)
        address=origin_of(request).address,
        user_agent=request.headers.get("user-agent"),
        next_route=row.next_path,
    )
    if state != "full":
        via = second_factor.via(conn, settings_of(request), row.human_id)
        return auth.pending_answer(state, via), sid, csrf, None
    return (
        {"member": auth.member_of(conn, row.human_id), "next": row.next_path},
        sid,
        csrf,
        sessions.remember_device(conn, row.human_id, request.cookies.get(sessions.DEVICE_COOKIE)),
    )


def _cookies(response: Any, request: Request, sid: str, csrf: str, device: str | None) -> None:
    auth.set_session_cookies(response, request, sid, csrf, device)
    for name, path in (
        (device_codes.PENDING_COOKIE, device_codes.PENDING_PATH),
        (FORM_COOKIE, FORM_PATH),
    ):
        response.delete_cookie(
            name, path=path, secure=origin_of(request).tls, httponly=True, samesite="strict"
        )


@router.post("/email-code")
def redeem_code(body: CodeRequest, request: Request) -> JSONResponse:
    _anonymous(request)
    wait = auth.LOGIN_BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    hub = settings_of(request)
    result = None
    with engine_of(request).begin() as conn:
        _enabled(conn, hub)
        row = links.live(conn, pending=request.cookies.get(device_codes.PENDING_COOKIE))
        if row is not None:
            links.lock_human(conn, row.human_id)
            if (
                _eligible(conn, hub, row.human_id, row.address_epoch) is not None
                and hub.mail.signing_key is not None
                and links.try_code(conn, row, body.code, hub.mail.signing_key)
            ):
                result = _complete(conn, request, row, "email_code")
    # Wrong guesses must commit, so refusal is outside the transaction.
    if result is None:
        raise ApiError(403, "code_invalid", "this code does not work")
    answer, sid, csrf, device = result
    response = JSONResponse(answer)
    _cookies(response, request, sid, csrf, device)
    return response


def _token(hub: Settings, token: str) -> dict[str, Any] | None:
    payload = tokens.read(hub.mail.signing_key, token)
    if (
        payload is None
        or payload.get("p") != "sign_in"
        or not isinstance(payload.get("n"), str)
        or not isinstance(payload.get("h"), str)
        or not isinstance(payload.get("x"), int)
        or payload["x"] <= clock.now().timestamp()
    ):
        return None
    return payload


def _dead() -> HTMLResponse:
    return HTMLResponse(
        "<h1>This link no longer works.</h1>",
        status_code=404,
        headers={"Referrer-Policy": "no-referrer"},
    )


@page_router.get("/mail/sign-in/{token}")
def link_page(token: str, request: Request) -> HTMLResponse:
    if request.headers.get("authorization"):
        raise humans_only("a sign-in link is for a browser, never a credential")
    require_secure_transport(origin_of(request), settings_of(request).allow_plain_http)
    hub = settings_of(request)
    payload = _token(hub, token)
    if payload is None:
        return _dead()
    with engine_of(request).begin() as conn:
        _enabled(conn, hub)
        row = links.live(conn, nonce_hash=links.digest(payload["n"]))
        if (
            row is None
            or row.human_id != payload["h"]
            or _eligible(conn, hub, row.human_id, row.address_epoch) is None
        ):
            return _dead()
        human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).one()
        language = preferences.preferences(conn, row.human_id)["email"]["language"]
        name = f"{human.display_name} ({human.handle})"
    form = secrets.token_urlsafe(32)
    title = f"Bei Maity anmelden als {name}" if language == "de" else f"Sign in to Maity as {name}"
    button = "Auf diesem Gerät anmelden" if language == "de" else "Sign in on this device"
    response = HTMLResponse(
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        f"<title>{escape(title)}</title></head><body><h1>{escape(title)}</h1>"
        f'<form method="post"><input type="hidden" name="form" value="{form}">'
        f'<button type="submit">{button}</button></form></body></html>',
        headers={"Referrer-Policy": "no-referrer"},
    )
    response.set_cookie(
        FORM_COOKIE,
        form,
        max_age=600,
        path=FORM_PATH,
        secure=origin_of(request).tls,
        httponly=True,
        samesite="strict",
    )
    return response


@page_router.post("/mail/sign-in/{token}")
async def complete_link(token: str, request: Request) -> Response:
    device_codes._anonymous(request)
    if request.headers.get("sec-fetch-site") != "same-origin":
        raise forbidden(message="a sign-in needs a same-origin form")
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise forbidden(message="a sign-in needs a form")
    fields = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    given = fields.get("form", [])
    cookie = request.cookies.get(FORM_COOKIE)
    if not cookie or len(given) != 1 or not hmac.compare_digest(given[0].encode(), cookie.encode()):
        raise forbidden(message="the form does not match")
    hub = settings_of(request)
    payload = _token(hub, token)
    if payload is None:
        return _dead()
    with engine_of(request).begin() as conn:
        _enabled(conn, hub)
        row = links.live(conn, nonce_hash=links.digest(payload["n"]))
        if row is None or row.human_id != payload["h"]:
            return _dead()
        links.lock_human(conn, row.human_id)
        if _eligible(conn, hub, row.human_id, row.address_epoch) is None or not links.use(
            conn, row
        ):
            return _dead()
        answer, sid, csrf, device = _complete(conn, request, row, "email_link")
    response = RedirectResponse(answer.get("next", "/"), status_code=303)
    _cookies(response, request, sid, csrf, device)
    return response
