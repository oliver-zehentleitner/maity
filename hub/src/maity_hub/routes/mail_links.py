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
from sqlalchemy import Connection, select

from maity_hub import account_deletion, clock, events
from maity_hub import tables as t
from maity_hub.deps import engine_of, settings_of
from maity_hub.notifications import preferences, tokens
from maity_hub.notifications.preferences import KINDS

page_router = APIRouter()

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
        "dead": "This link no longer works.",
        "delete_title": "Delete my account",
        "delete_text": "This deletes the Maity account {handle}.",
        "delete_removes": (
            "Every session ends. Your address, name, picture, languages and settings are "
            "deleted, your memberships end, your agent profiles are deleted and your "
            "runners are removed."
        ),
        "delete_keeps": (
            "What you wrote stays in its projects, shown as written by a deleted account. "
            "Redact it first if you want it gone. Your handle is never given to anyone else."
        ),
        "delete_export": "Take your data with you first",
        "delete_button": "Delete my account",
        "delete_done": "Your account is deleted. Every session has ended.",
        "namespace_owner": (
            "Nothing was deleted: a project in your namespace is not archived. Transfer it "
            "or archive it first; this link keeps working until it expires."
        ),
        "last_instance_admin": (
            "Nothing was deleted: you are the instance's last admin. This link keeps "
            "working until it expires."
        ),
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
        "dead": "Dieser Link funktioniert nicht mehr.",
        "delete_title": "Mein Konto löschen",
        "delete_text": "Damit wird das Maity-Konto {handle} gelöscht.",
        "delete_removes": (
            "Jede Sitzung endet. Deine Adresse, dein Name, dein Bild, deine Sprachen und "
            "Einstellungen werden gelöscht, deine Mitgliedschaften enden, deine "
            "Agentenprofile werden gelöscht und deine Runner entfernt."
        ),
        "delete_keeps": (
            "Was du geschrieben hast, bleibt in seinen Projekten, gezeigt als von einem "
            "gelöschten Konto geschrieben. Schwärze es vorher, wenn es weg soll. Dein "
            "Handle wird nie an jemand anderen vergeben."
        ),
        "delete_export": "Nimm vorher deine Daten mit",
        "delete_button": "Mein Konto löschen",
        "delete_done": "Dein Konto ist gelöscht. Jede Sitzung ist beendet.",
        "namespace_owner": (
            "Nichts wurde gelöscht: ein Projekt in deinem Namensraum ist nicht archiviert. "
            "Übertrage oder archiviere es zuerst; dieser Link funktioniert, bis er abläuft."
        ),
        "last_instance_admin": (
            "Nichts wurde gelöscht: du bist der letzte Admin der Instanz. Dieser Link "
            "funktioniert, bis er abläuft."
        ),
    },
}


def _page(
    title: str,
    text: str,
    *,
    button: str | None = None,
    status: int = 200,
    more: tuple[str, ...] = (),
    link: tuple[str, str] | None = None,
) -> HTMLResponse:
    form = (
        f'<form method="post"><button type="submit">{escape(button)}</button></form>'
        if button
        else ""
    )
    paragraphs = "".join(f"<p>{escape(p)}</p>" for p in (text, *more))
    if link is not None:  # only a link the hub builds from its public URL
        paragraphs += f'<p><a href="{escape(link[1])}">{escape(link[0])}</a></p>'
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        f"<title>{escape(title)}</title></head><body>"
        f"<h1>{escape(title)}</h1>{paragraphs}{form}</body></html>"
    )
    # The token is in the address: no page that carries it may leak it in a `Referer`.
    return HTMLResponse(html, status_code=status, headers={"Referrer-Policy": "no-referrer"})


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
            and row.pending_expires_at is not None
            and clock.now() < row.pending_expires_at
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
        # The row itself, not the defaults a read falls back to: a human with no stored
        # settings has no link that works, and a `GET` writes nothing.
        row = conn.execute(
            select(t.notification_settings).where(
                t.notification_settings.c.human_id == str(payload.get("h"))
            )
        ).first()
        if row is None or payload.get("e") != row.epoch or payload.get("k") not in KINDS:
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


@page_router.get("/mail/account-deletion/{token}")
def account_deletion_page(token: str, request: Request) -> HTMLResponse:
    """Asks once more (§2.9): the account, what deletion removes and keeps, the export
    on the dashboard's account page, and the button. Writes nothing."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        words = _WORDS[_language(conn, request, token)]
        human = account_deletion.page(conn, hub.mail.signing_key, token)
        if human is None:
            return _dead(words)
        return _page(
            words["delete_title"],
            words["delete_text"].format(handle=human.handle),
            more=(words["delete_removes"], words["delete_keeps"]),
            link=(words["delete_export"], account_deletion.export_url(hub.public_url)),
            button=words["delete_button"],
        )


@page_router.post("/mail/account-deletion/{token}")
def account_deletion_confirm(token: str, request: Request) -> HTMLResponse:
    """Deletes the account in one transaction, or says why it did not (§2.9)."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        # Read before the deletion removes the human's settings, the language with them.
        words = _WORDS[_language(conn, request, token)]
    with events.transaction(engine_of(request)) as conn:
        outcome = account_deletion.confirm(conn, hub, token)
    if outcome is None:
        return _dead(words)
    if outcome != "deleted":  # `namespace_owner`, `last_instance_admin`: nothing changed
        return _page(words["delete_title"], words[outcome], status=409)
    return _page(words["delete_title"], words["delete_done"])
