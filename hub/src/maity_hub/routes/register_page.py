"""The registration's link page (docs/api.md §2.7.1 steps 5 and 6), outside the API, on the
public host only.

The mail's link proves the mailbox, the form proves the person who asked: the password
chosen at registration, the handle, the display name and, when the instance has terms,
their acceptance. A `GET` changes nothing and sets only the form cookie, since mail
scanners open links before the human does; the account is made by the `POST`, which needs
the form field next to that cookie and a `Sec-Fetch-Site` of `same-origin`. A link that
does not work is one page, `not_found`, never saying why (§18.6).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from html import escape
from typing import Any, NamedTuple
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import Connection, select

from maity_hub import clock, legal, registration, registration_accounts, registration_mail
from maity_hub import tables as t
from maity_hub.auth import sessions
from maity_hub.auth.caller import SESSION_COOKIE, require_secure_transport
from maity_hub.deps import engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, rate_limited
from maity_hub.mail import address as addresses
from maity_hub.notifications import tokens
from maity_hub.routes.auth import LOGIN_BY_ADDRESS, end_presented, set_session_cookies

page_router = APIRouter()

FORM_COOKIE = "maity_form"
FORM_PATH = "/mail/register"
FORM_FOR = 600  # seconds the form cookie lives
BODY_MAX = 8192

_WORDS = {
    "en": {
        "title": "Create your Maity account",
        "intro": "Create your Maity account for {address}.",
        "password": "The password you chose when you asked for the account",
        "handle": "Handle",
        "display_name": "Display name",
        "terms": "I accept the terms ({url}, version {version})",
        "button": "Create account",
        "dead": "This link no longer works.",
        "closed": "Registration is closed.",
        "later": (
            "Too many accounts were made in the last hour. "
            "Try again later; the link stays valid."
        ),
        "terms_changed": "The terms changed while this page was open. Read them again and confirm.",
        "error_password": "That is not the password chosen at registration.",
        "error_handle_invalid": "A handle has 2 to 31 letters, digits or hyphens.",
        "error_handle_reserved": "This handle is reserved.",
        "error_handle_taken": "This handle is taken.",
        "error_display_name_invalid": "A display name has 1 to 64 characters.",
        "error_terms_required": "Accept the terms to create the account.",
        "legal_imprint": "Imprint",
        "legal_privacy": "Privacy notice",
        "legal_terms": "Terms of use",
    },
    "de": {
        "title": "Maity-Konto anlegen",
        "intro": "Lege dein Maity-Konto für {address} an.",
        "password": "Das Passwort, das du bei der Anfrage gewählt hast",
        "handle": "Handle",
        "display_name": "Anzeigename",
        "terms": "Ich akzeptiere die Bedingungen ({url}, Version {version})",
        "button": "Konto anlegen",
        "dead": "Dieser Link funktioniert nicht mehr.",
        "closed": "Die Registrierung ist geschlossen.",
        "later": (
            "In der letzten Stunde wurden zu viele Konten angelegt. "
            "Versuche es später noch einmal; der Link bleibt gültig."
        ),
        "terms_changed": (
            "Die Bedingungen haben sich geändert, während die Seite offen war. "
            "Lies sie noch einmal und bestätige sie."
        ),
        "error_password": "Das ist nicht das bei der Anfrage gewählte Passwort.",
        "error_handle_invalid": "Ein Handle hat 2 bis 31 Buchstaben, Ziffern oder Bindestriche.",
        "error_handle_reserved": "Dieses Handle ist reserviert.",
        "error_handle_taken": "Dieses Handle ist schon vergeben.",
        "error_display_name_invalid": "Ein Anzeigename hat 1 bis 64 Zeichen.",
        "error_terms_required": "Akzeptiere die Bedingungen, um das Konto anzulegen.",
        "legal_imprint": "Impressum",
        "legal_privacy": "Datenschutzerklärung",
        "legal_terms": "Nutzungsbedingungen",
    },
}


def _html(body: str, title: str, status: int = 200) -> HTMLResponse:
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        f"<title>{escape(title)}</title></head><body>{body}</body></html>"
    )
    # The token is in the address and the form holds a password: nothing that carries
    # either may leak in a `Referer` or sit in a cache.
    return HTMLResponse(
        html,
        status_code=status,
        headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"},
    )


def _message(title: str, text: str, status: int) -> HTMLResponse:
    return _html(f"<h1>{escape(title)}</h1><p>{escape(text)}</p>", title, status)


def _dead() -> HTMLResponse:
    """Invalid, expired, used or voided: one page, `not_found`, never which (§18.6)."""
    return _message(_WORDS["en"]["dead"], _WORDS["en"]["dead"], 404)


def _humans_only(request: Request) -> None:
    if request.headers.get("authorization"):  # an agent's or a runner's credential
        raise ApiError(403, "forbidden", "only a person registers", {"reason": "humans_only"})


def _pending(conn: Connection, request: Request, token: str) -> tuple[Any, dict[str, Any]] | None:
    """The pending registration the link names, when the link still works: signed by the
    hub, not expired, not used or voided, and its nonce the one the registration kept."""
    payload = tokens.read(settings_of(request).mail.signing_key, token)
    if payload is None or payload.get("p") != "register":
        return None
    row = conn.execute(
        select(t.pending_registration).where(t.pending_registration.c.id == payload.get("i"))
    ).first()
    if (
        row is None
        or row.voided_at is not None
        or row.expires_at <= clock.now()
        or payload.get("x") != int(row.expires_at.timestamp())
        or not row.nonce_hash
        or not hmac.compare_digest(
            hashlib.sha256(str(payload.get("n")).encode()).hexdigest(), row.nonce_hash
        )
    ):
        return None
    return row, payload


def _terms(conn: Connection, request: Request) -> dict[str, str] | None:
    hub = settings_of(request)
    env = hub.registration or registration.RegistrationEnvironment()
    found = registration.resolve(
        conn, env, registration.mail_ready(conn, hub), hub.public_url
    ).value("terms")
    return found if isinstance(found, dict) else None


def _legal(conn: Connection) -> list[str]:
    """The legal pages the instance serves (§16.7.1), in their order: the page links
    them as the dashboard's registration form does, the privacy notice included."""
    served = set(
        conn.execute(
            select(t.legal_page.c.page).where(t.legal_page.c.current.is_not(None))
        ).scalars()
    )
    return [page for page in legal.PAGES if page in served]


def _terms_field(hub: Any, nonce: str, terms: dict[str, str] | None) -> str:
    """The version the person saw, signed together with the registration's nonce (§2.7.2)."""
    if terms is None:
        return ""
    return tokens.make(hub.mail.signing_key, {"p": "terms", "n": nonce, "v": terms["version"]})


def _seen_terms(hub: Any, nonce: str, signed: str) -> str | None:
    found = tokens.read(hub.mail.signing_key, signed) if signed else None
    if found is None or found.get("p") != "terms" or found.get("n") != nonce:
        return None
    version = found.get("v")
    return version if isinstance(version, str) else None


def _form(
    words: dict[str, str],
    *,
    address: str,
    form_value: str,
    terms: dict[str, str] | None,
    terms_field: str,
    given: dict[str, str],
    errors: dict[str, str],
    pages: list[str],
    notice: str | None = None,
    status: int = 200,
) -> HTMLResponse:
    def row(name: str, label: str, kind: str, extra: str = "") -> str:
        problem = errors.get(name)
        shown = "" if kind == "password" else escape(given.get(name, ""))
        message = f'<p role="alert">{escape(problem)}</p>' if problem else ""
        return (
            f'<p><label>{escape(label)}<br><input name="{name}" type="{kind}" '
            f'value="{shown}" required {extra}></label></p>{message}'
        )

    box = ""
    if terms is not None:
        problem = errors.get("terms")
        box = (
            '<p><label><input name="terms_accepted" type="checkbox" value="1"> '
            f"{escape(words['terms'].format(url=terms['url'], version=terms['version']))}"
            "</label></p>" + (f'<p role="alert">{escape(problem)}</p>' if problem else "")
        )
    body = (
        f"<h1>{escape(words['title'])}</h1>"
        f"<p>{escape(words['intro'].format(address=address))}</p>"
        + (f'<p role="alert">{escape(notice)}</p>' if notice else "")
        + '<form method="post">'
        + row("password", words["password"], "password", 'autocomplete="current-password"')
        + row("handle", words["handle"], "text", 'autocomplete="username" autocapitalize="none"')
        + row("display_name", words["display_name"], "text", 'autocomplete="name"')
        + box
        + f'<input type="hidden" name="form" value="{escape(form_value)}">'
        + f'<input type="hidden" name="terms_seen" value="{escape(terms_field)}">'
        + f'<button type="submit">{escape(words["button"])}</button></form>'
        + _legal_links(words, pages)
    )
    return _html(body, words["title"], status)


def _legal_links(words: dict[str, str], pages: list[str]) -> str:
    """The served legal pages under the form, each at its address (§16.11)."""
    if not pages:
        return ""
    links = " · ".join(
        f'<a href="/{legal.ADDRESS[page]}">{escape(words["legal_" + page])}</a>' for page in pages
    )
    return f"<p>{links}</p>"


def _set_form_cookie(response: Response, request: Request, value: str) -> None:
    response.set_cookie(
        FORM_COOKIE,
        value,
        max_age=FORM_FOR,
        path=FORM_PATH,
        secure=origin_of(request).tls,
        httponly=True,
        samesite="strict",
    )


@page_router.get("/mail/register/{token}")
def register_page(token: str, request: Request) -> Response:
    _humans_only(request)
    hub = settings_of(request)
    require_secure_transport(origin_of(request), hub.allow_plain_http)
    with engine_of(request).begin() as conn:
        found = _pending(conn, request, token)
        if found is None:
            return _dead()
        row, payload = found
        terms = _terms(conn, request)
        pages = _legal(conn)
    form_value = secrets.token_urlsafe(24)
    page = _form(
        _WORDS[registration_mail.language_of(row.language)],
        address=row.address,
        form_value=form_value,
        terms=terms,
        terms_field=_terms_field(hub, str(payload["n"]), terms),
        given={},
        errors={},
        pages=pages,
    )
    _set_form_cookie(page, request, form_value)
    return page


def _read_form(raw: bytes) -> dict[str, str]:
    parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {name: values[0] for name, values in parsed.items() if values}


def _session_cookies(
    response: Response, request: Request, session_id: str, csrf: str, device: str | None
) -> None:
    """The cookies of a completed sign-in, as the login sets them, and the form cookie gone."""
    set_session_cookies(response, request, session_id, csrf, device)
    response.delete_cookie(
        FORM_COOKIE,
        path=FORM_PATH,
        secure=origin_of(request).tls,
        httponly=True,
        samesite="strict",
    )


class Outcome(NamedTuple):
    done: registration_accounts.Completion
    row: Any
    payload: dict[str, Any]
    terms: dict[str, str] | None
    device: str | None  # the device cookie's new value, when this browser needs one
    pages: list[str]  # the legal pages served (§16.7.1)


def _complete(request: Request, token: str, fields: dict[str, str]) -> Outcome | None:
    """The completion in its own transaction, which commits what a refusal leaves behind
    (a wrong password counted, a pending registration voided)."""
    hub = settings_of(request)
    origin = origin_of(request)
    addresses.prepare(engine_of(request), hub.secret_key)  # before the locks' transaction
    with engine_of(request).begin() as conn:
        found = _pending(conn, request, token)
        if found is None:
            return None
        row, payload = found
        env = hub.registration or registration.RegistrationEnvironment()
        done = registration_accounts.complete(
            conn,
            lambda c: registration.resolve(c, env, registration.mail_ready(c, hub), hub.public_url),
            row.id,
            password=fields.get("password", ""),
            handle=fields.get("handle", "").strip(),
            display_name=fields.get("display_name", "").strip(),
            terms_seen=_seen_terms(hub, str(payload["n"]), fields.get("terms_seen", "")),
            terms_accepted=fields.get("terms_accepted") == "1",
            source=origin.address,
            secret_key=hub.secret_key,
            user_agent=request.headers.get("user-agent"),
        )
        device = None
        if done.kind == "created":
            assert done.human_id is not None
            # A browser that holds a session, of any human, loses it (§2.6.5, session
            # fixation); it is a sign-in, so this browser is known to the human now.
            end_presented(conn, request.cookies.get(SESSION_COOKIE))
            device = sessions.remember_device(
                conn, done.human_id, request.cookies.get(sessions.DEVICE_COOKIE)
            )
        return Outcome(done, row, payload, _terms(conn, request), device, _legal(conn))


@page_router.post("/mail/register/{token}")
async def register_complete(token: str, request: Request) -> Response:
    _humans_only(request)
    hub = settings_of(request)
    require_secure_transport(origin_of(request), hub.allow_plain_http)
    if request.headers.get("sec-fetch-site") != "same-origin":
        raise ApiError(403, "csrf_mismatch", "the form is submitted from its own page")
    raw = await request.body()
    if len(raw) > BODY_MAX:
        raise ApiError(413, "payload_too_large", "the form is too large")
    fields = _read_form(raw)
    cookie = request.cookies.get(FORM_COOKIE, "")
    if not cookie or not hmac.compare_digest(
        cookie.encode("utf-8", "replace"), fields.get("form", "").encode("utf-8", "replace")
    ):
        raise ApiError(403, "csrf_mismatch", "the form is not the one the page gave")
    wait = LOGIN_BY_ADDRESS.hit(origin_of(request).address)  # shared with the login (§2.7.3)
    if wait:
        raise rate_limited(wait)
    result = await run_in_threadpool(_complete, request, token, fields)
    if result is None:
        return _dead()
    done, row, payload, terms, device, pages = result
    words = _WORDS[registration_mail.language_of(row.language)]
    if done.kind == "created":
        assert done.session_id is not None and done.csrf is not None and done.next is not None
        response = RedirectResponse(done.next, status_code=303)
        _session_cookies(response, request, done.session_id, done.csrf, device)
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
    if done.kind == "gone":
        return _dead()
    if done.kind == "closed":
        return _message(words["title"], words["closed"], 403)
    if done.kind == "later":
        return _message(words["title"], words["later"], 503)
    given = {"handle": fields.get("handle", ""), "display_name": fields.get("display_name", "")}
    errors: dict[str, str] = {}
    notice = None
    status = 400
    if done.kind == "wrong_password":
        errors["password"] = words["error_password"]
    elif done.kind == "invalid":
        errors = {name: words.get(f"error_{name}_{why}", why) for name, why in done.fields.items()}
    elif done.kind == "terms_changed":
        notice, status = words["terms_changed"], 409  # the page asks again, unchecked
    return _form(
        words,
        address=row.address,
        form_value=fields.get("form", ""),
        terms=terms,
        terms_field=_terms_field(hub, str(payload["n"]), terms),
        given=given,
        errors=errors,
        pages=pages,
        notice=notice,
        status=status,
    )
