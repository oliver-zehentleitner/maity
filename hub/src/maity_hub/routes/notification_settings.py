"""`/me/notification-settings` (docs/api.md §18.4) and the two pages mails link to,
`/mail/verify/{token}` and `/mail/unsubscribe/{token}` (§18.6).

The settings are a human's own: an agent credential is `forbidden` with `humans_only`.
The pages are unauthenticated, the token is the authority; they set and read no cookie,
and a `GET` never changes anything, since mail scanners open links first.
"""

from __future__ import annotations

from html import escape
from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.auth import second_factor, second_factor_reset
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of, origin_of, settings_of
from maity_hub.errors import forbidden, humans_only, invalid, not_found
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import preferences, tokens
from maity_hub.notifications.mailer import quoted
from maity_hub.routes.auth import LOGIN_BY_ADDRESS, LOGIN_BY_HANDLE

router = APIRouter()
page_router = APIRouter()  # /mail/*, outside the API prefix


def _human(caller: Caller) -> str:
    if caller.kind == "agent":
        raise humans_only("notification settings are a human's own")
    if caller.kind != "human" or caller.human_session is None:
        raise forbidden(message="notification settings need a dashboard session")
    return caller.human_session


def _mail_ready(conn: Connection, request: Request) -> bool:
    hub = settings_of(request)
    return mail_settings.resolve(conn, hub.mail, hub.secret_key).complete


def _context(conn: Connection, caller: Caller, session_hash: str) -> tuple[Any, Any]:
    human = conn.execute(select(t.human).where(t.human.c.id == caller.principal_id)).one()
    session = conn.execute(
        select(t.human_session).where(t.human_session.c.id_hash == session_hash)
    ).one()
    return human, session


@router.get("/me/notification-settings")
def get_settings(request: Request, caller: AnyCaller) -> JSONResponse:
    _human(caller)
    with engine_of(request).begin() as conn:
        return JSONResponse(preferences.view(conn, caller.principal_id, _mail_ready(conn, request)))


@router.patch("/me/notification-settings")
def patch_settings(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    session_hash = _human(caller)
    hub = settings_of(request)
    address = origin_of(request).address
    with engine_of(request).begin() as conn:
        human, session = _context(conn, caller, session_hash)
        email = body.get("email")
        if isinstance(email, dict) and "address" in email:
            second_factor.require_step_up(conn, hub, caller)  # §2.8.4

        def wrong_password() -> None:
            # A wrong current password counts against the login limit (§2.1, §18.4).
            LOGIN_BY_ADDRESS.hit(address)
            LOGIN_BY_HANDLE.hit(human.handle)

        def password_blocked() -> int:
            return max(LOGIN_BY_ADDRESS.blocked(address), LOGIN_BY_HANDLE.blocked(human.handle))

        status = preferences.patch(
            conn,
            human=human,
            session=session,
            body=body,
            signing_key=hub.mail.signing_key,
            public_url=hub.public_url,
            mail_ready=_mail_ready(conn, request),
            wrong_password=wrong_password,
            password_blocked=password_blocked,
        )
        answer = preferences.view(conn, human.id, _mail_ready(conn, request))
    return JSONResponse(answer, status_code=status)


@router.post("/me/notification-settings/email/verify")
def verify_from_dashboard(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    _human(caller)
    token = body.get("token")
    if set(body) != {"token"} or not isinstance(token, str):
        raise invalid({"token": "required"})
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        # Another human's token is `not_found`, the same as an invalid one (§18.4).
        done = preferences.verify(
            conn, token, hub.mail.signing_key, hub.public_url, human_id=caller.principal_id
        )
        if not done:
            raise not_found()
        return JSONResponse(preferences.view(conn, caller.principal_id, True))


@router.post("/me/notification-settings/email/address-change/approve")
def approve_change(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    return _decide(request, caller, body, approve=True)


@router.post("/me/notification-settings/email/address-change/reject")
def reject_change(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    return _decide(request, caller, body, approve=False)


def _decide(
    request: Request, caller: Caller, body: dict[str, Any], *, approve: bool
) -> JSONResponse:
    session_hash = _human(caller)
    if set(body) != {"id", "address"}:
        raise invalid({"body": "id_and_address"})
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        human, session = _context(conn, caller, session_hash)
        if approve:
            second_factor.require_step_up(conn, hub, caller)  # §2.8.4
        preferences.decide_held(
            conn,
            human=human,
            session=session,
            change_id=body["id"],
            address=body["address"],
            approve=approve,
            signing_key=hub.mail.signing_key,
            public_url=hub.public_url,
        )
        return JSONResponse(preferences.view(conn, human.id, _mail_ready(conn, request)))


# --- the pages (§18.6) ---------------------------------------------------------------

_WORDS = {
    "en": {
        "verify_title": "Confirm your address",
        "verify_text": "Confirm that Maity may send mail to {address}.",
        "verify_button": "Confirm",
        "verify_done": "The address is confirmed.",
        "unsub_title": "Stop these mails",
        "unsub_text": "Stop the {kind} mails from Maity.",
        "unsub_button": "Stop these mails",
        "unsub_done": "You will get no more {kind} mails. The settings can switch them on again.",
        "reset_title": "Reset the two-factor sign-in of {handle}",
        "reset_text": (
            "{admin}, your Maity administrator, asked to reset it. Their reason: {reason}. "
            "Resetting ends every session of your account; your next sign-in sets up the "
            "second factor again."
        ),
        "reset_button": "Reset my two-factor sign-in",
        "reset_done": "Your two-factor sign-in is reset, and every session has ended.",
        "dead": "This link no longer works.",
    },
    "de": {
        "verify_title": "Adresse bestätigen",
        "verify_text": "Bestätige, dass Maity Mails an {address} schicken darf.",
        "verify_button": "Bestätigen",
        "verify_done": "Die Adresse ist bestätigt.",
        "unsub_title": "Diese Mails abbestellen",
        "unsub_text": "Die {kind}-Mails von Maity abbestellen.",
        "unsub_button": "Diese Mails abbestellen",
        "unsub_done": (
            "Du bekommst keine {kind}-Mails mehr. "
            "In den Einstellungen lassen sie sich wieder einschalten."
        ),
        "reset_title": "Zwei-Faktor-Anmeldung von {handle} zurücksetzen",
        "reset_text": (
            "{admin}, dein Maity-Administrator, möchte sie zurücksetzen. Begründung: "
            "{reason}. Das beendet alle Sitzungen deines Kontos; bei der nächsten Anmeldung "
            "richtest du den zweiten Faktor neu ein."
        ),
        "reset_button": "Meine Zwei-Faktor-Anmeldung zurücksetzen",
        "reset_done": "Deine Zwei-Faktor-Anmeldung ist zurückgesetzt, alle Sitzungen sind beendet.",
        "dead": "Dieser Link funktioniert nicht mehr.",
    },
}


def _page(title: str, text: str, *, button: str | None = None, status: int = 200) -> HTMLResponse:
    form = (
        f'<form method="post"><button type="submit">{escape(button)}</button></form>'
        if button
        else ""
    )
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        f"<title>{escape(title)}</title></head><body>"
        f"<h1>{escape(title)}</h1><p>{escape(text)}</p>{form}</body></html>"
    )
    return HTMLResponse(html, status_code=status)


def _language(conn: Connection, request: Request, token: str) -> str:
    payload = tokens.read(settings_of(request).mail.signing_key, token)
    if payload is None:
        return "en"
    return str(preferences.preferences(conn, str(payload.get("h")))["email"]["language"])


def _dead(words: dict[str, str]) -> HTMLResponse:
    """Invalid, expired or used: one page, `not_found`, never which (§18.6)."""
    return _page(words["dead"], words["dead"], status=404)


@page_router.get("/mail/verify/{token}")
def verify_page(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        payload = tokens.read(hub.mail.signing_key, token) or {}
        row = None
        if payload.get("p") == "verify":
            row = conn.execute(
                select(t.notification_settings).where(
                    t.notification_settings.c.human_id == str(payload.get("h"))
                )
            ).first()
        alive = (
            row is not None
            and row.pending_nonce == payload.get("n")
            and row.pending_address == payload.get("a")
        )
        if not alive:
            return _dead(words)
        text = words["verify_text"].format(address=payload.get("a"))
        return _page(words["verify_title"], text, button=words["verify_button"])


@page_router.post("/mail/verify/{token}")
def verify_confirm(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        if not preferences.verify(conn, token, hub.mail.signing_key, hub.public_url):
            return _dead(words)
        return _page(words["verify_title"], words["verify_done"])


@page_router.get("/mail/unsubscribe/{token}")
def unsubscribe_page(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        payload = tokens.read(hub.mail.signing_key, token)
        if payload is None or payload.get("p") != "unsubscribe":
            return _dead(words)
        row = preferences.row_of(conn, str(payload.get("h")))
        if payload.get("e") != row.epoch or payload.get("k") not in preferences.KINDS:
            return _dead(words)
        text = words["unsub_text"].format(kind=payload["k"])
        return _page(words["unsub_title"], text, button=words["unsub_button"])


@page_router.post("/mail/unsubscribe/{token}")
def unsubscribe_confirm(token: str, request: Request) -> HTMLResponse:
    """The page's button and the RFC 8058 one-click `POST` alike."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        kind = preferences.unsubscribe(conn, token, hub.mail.signing_key)
        if kind is None:
            return _dead(words)
        return _page(words["unsub_title"], words["unsub_done"].format(kind=kind))


@page_router.get("/mail/second-factor-reset/{token}")
def reset_page(token: str, request: Request) -> HTMLResponse:
    """Names the account and who asked, with the reason as quoted text; changes nothing."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        shown = second_factor_reset.page(conn, hub.mail.signing_key, token)
        if shown is None:
            return _dead(words)
        title = words["reset_title"].format(handle=shown["handle"])
        text = words["reset_text"].format(admin=shown["admin"], reason=quoted(shown["reason"]))
        return _page(title, text, button=words["reset_button"])


@page_router.post("/mail/second-factor-reset/{token}")
def reset_confirm(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        if not second_factor_reset.confirm(conn, hub.mail.signing_key, token):
            return _dead(words)
        return _page(words["reset_done"], words["reset_done"])
