"""The pages the links in mails open (docs/api.md §18.6), outside the API, on the public
host only.

They are unauthenticated, the token is the authority, and they set and read no cookie.
A `GET` never changes anything, since mail scanners open links before the human does;
the change is the `POST`, the page's button or the RFC 8058 one-click request alike. A
link that does not work is one page, `not_found`, never saying why.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import Connection

from maity_hub.deps import engine_of, settings_of
from maity_hub.notifications import preferences, tokens

page_router = APIRouter()

_WORDS = {
    "en": {
        "unsub_title": "Stop these mails",
        "unsub_text": "Stop the {kind} mails from Maity.",
        "unsub_button": "Stop these mails",
        "unsub_done": "You will get no more {kind} mails. The settings can switch them on again.",
        "dead": "This link no longer works.",
    },
    "de": {
        "unsub_title": "Diese Mails abbestellen",
        "unsub_text": "Die {kind}-Mails von Maity abbestellen.",
        "unsub_button": "Diese Mails abbestellen",
        "unsub_done": (
            "Du bekommst keine {kind}-Mails mehr. "
            "In den Einstellungen lassen sie sich wieder einschalten."
        ),
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
    """The human's language when the token is ours, else English: a page for a forged
    token says nothing about who it names."""
    payload = tokens.read(settings_of(request).mail.signing_key, token)
    if payload is None:
        return "en"
    return str(preferences.preferences(conn, str(payload.get("h")))["email"]["language"])


def _dead(words: dict[str, str]) -> HTMLResponse:
    """Invalid, expired or used: one page, `not_found`, never which (§18.6)."""
    return _page(words["dead"], words["dead"], status=404)


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
    """The page's button and the RFC 8058 one-click `POST` (`List-Unsubscribe=One-Click`)
    alike; the body is not read."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        kind = preferences.unsubscribe(conn, token, hub.mail.signing_key)
        if kind is None:
            return _dead(words)
        return _page(words["unsub_title"], words["unsub_done"].format(kind=kind))
