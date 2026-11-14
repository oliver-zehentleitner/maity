"""The pages the links in mails open (docs/api.md §18.6), outside the API, on the public
host only.

They are unauthenticated, the token is the authority, and they set and read no cookie.
A `GET` never changes anything, since mail scanners open links before the human does;
the change is the `POST`, the page's button or the RFC 8058 one-click request alike. A
link that does not work is one page, `not_found`, never saying why. Each stands in the
frame of the pages without a session under the mail link pages' one policy (§16.7.5,
`link_frame`), with the frame's footer and no product line.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import Connection, select

from maity_hub import account_deletion, catalog, clock, events, link_frame
from maity_hub import tables as t
from maity_hub.auth import second_factor, second_factor_reset
from maity_hub.db import retrying
from maity_hub.deps import engine_of, settings_of
from maity_hub.mail import address as addresses
from maity_hub.notifications import preferences, tokens
from maity_hub.notifications.preferences import KINDS

page_router = APIRouter()


def _page(
    conn: Connection,
    request: Request,
    title: str,
    text: str,
    *,
    button: str | None = None,
    status: int = 200,
    more: tuple[str, ...] = (),
    link: tuple[str, str] | None = None,
    quote: str | None = None,
    language: str = "en",
) -> HTMLResponse:
    """The page in the frame of the mail link pages (§16.7.5), its words as before: the title,
    the text, the quote, the one button that posts. The frame's footer ends it, and its policy
    is the frame's (`link_frame.HEADERS`)."""
    form = (
        f'<form method="post"><button type="submit" class="btn btn-primary">{escape(button)}'
        "</button></form>"
        if button
        else ""
    )
    paragraphs = "".join(f"<p>{escape(p)}</p>" for p in (text, *more))
    if link is not None:  # only a link the hub builds from its public URL
        paragraphs += f'<p><a href="{escape(link[1])}">{escape(link[0])}</a></p>'
    quoted = f"<blockquote>{escape(quote)}</blockquote>" if quote else ""
    content = f'<div class="link-page"><h1>{escape(title)}</h1>{paragraphs}{quoted}{form}</div>'
    return link_frame.page(conn, request, language, title, content, status)


def _language(conn: Connection, request: Request, token: str) -> str:
    """The human's language when the token is ours, else English: a page for a forged
    token says nothing about who it names."""
    payload = tokens.read(settings_of(request).mail.signing_key, token)
    if payload is None:
        return "en"
    return preferences.text_language(conn, str(payload.get("h")))


def _dead(conn: Connection, request: Request, words: dict[str, str], language: str) -> HTMLResponse:
    """Invalid, expired or used: one page, `not_found`, never which (§18.6)."""
    return _page(conn, request, words["dead"], words["dead"], status=404, language=language)


@page_router.get("/mail/verify/{token}")
def verify_page(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)
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
            return _dead(conn, request, words, language)
        text = words["verify_text"].format(address=payload.get("a"))
        return _page(
            conn,
            request,
            words["verify_title"],
            text,
            button=words["verify_button"],
            language=language,
        )


@page_router.post("/mail/verify/{token}")
def verify_confirm(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    addresses.prepare(engine_of(request), hub.secret_key)  # before the lock's transaction
    with engine_of(request).begin() as conn:
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)
        if not preferences.verify(
            conn, token, hub.mail.signing_key, hub.public_url, secret_key=hub.secret_key
        ):
            return _dead(conn, request, words, language)
        return _page(conn, request, words["verify_title"], words["verify_done"], language=language)


@page_router.get("/mail/unsubscribe/{token}")
def unsubscribe_page(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)
        payload = tokens.read(hub.mail.signing_key, token)
        if payload is None or payload.get("p") != "unsubscribe":
            return _dead(conn, request, words, language)
        # The row itself, not the defaults a read falls back to: a human with no stored
        # settings has no link that works, and a `GET` writes nothing.
        row = conn.execute(
            select(t.notification_settings).where(
                t.notification_settings.c.human_id == str(payload.get("h"))
            )
        ).first()
        if row is None or payload.get("e") != row.epoch or payload.get("k") not in KINDS:
            return _dead(conn, request, words, language)
        text = words["unsub_text"].format(kind=payload["k"])
        return _page(
            conn,
            request,
            words["unsub_title"],
            text,
            button=words["unsub_button"],
            language=language,
        )


@page_router.post("/mail/unsubscribe/{token}")
def unsubscribe_confirm(token: str, request: Request) -> HTMLResponse:
    """The page's button and the RFC 8058 one-click `POST` (`List-Unsubscribe=One-Click`)
    alike; the body is not read."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)
        kind = preferences.unsubscribe(conn, token, hub.mail.signing_key)
        if kind is None:
            return _dead(conn, request, words, language)
        return _page(
            conn,
            request,
            words["unsub_title"],
            words["unsub_done"].format(kind=kind),
            language=language,
        )


@page_router.get("/mail/second-factor-reset/{token}")
def reset_page(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        shown = second_factor_reset.page(conn, hub, token)
        if shown is None:
            language = _language(conn, request, token)
            return _dead(conn, request, catalog.section("mail_links", language), language)
        language = shown["language"]
        words = catalog.section("mail_links", language)
        text = words["reset_text"].format(
            admin=shown["admin"], name=shown["display_name"], handle=shown["handle"]
        )
        return _page(
            conn,
            request,
            words["reset_title"],
            f"{text} {words['reset_reason']}",
            button=words["reset_button"],
            quote=shown["reason"],
            language=language,
        )


@page_router.post("/mail/second-factor-reset/{token}")
def reset_confirm(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)
        if not second_factor_reset.take_effect(conn, hub, token):
            return _dead(conn, request, words, language)
        return _page(conn, request, words["reset_title"], words["reset_done"], language=language)


@page_router.get("/mail/second-factor-unlock/{token}")
def unlock_page(token: str, request: Request) -> HTMLResponse:
    """Asks before the day's cap of wrong second-factor codes is lifted (§2.8.6); writes
    nothing."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        language = second_factor.unlock_page(conn, hub, token)
        if language is None:
            language = _language(conn, request, token)
            return _dead(conn, request, catalog.section("mail_links", language), language)
        words = catalog.section("mail_links", language)
        return _page(
            conn,
            request,
            words["unlock_title"],
            words["unlock_text"],
            button=words["unlock_button"],
            language=language,
        )


@page_router.post("/mail/second-factor-unlock/{token}")
def unlock_confirm(token: str, request: Request) -> HTMLResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)
        if not second_factor.unlock(conn, hub, token):
            return _dead(conn, request, words, language)
        return _page(conn, request, words["unlock_title"], words["unlock_done"], language=language)


@page_router.get("/mail/account-deletion/{token}")
def account_deletion_page(token: str, request: Request) -> HTMLResponse:
    """Asks once more (§2.9): the account, what deletion removes and keeps, the export
    on the dashboard's account page, and the button. Writes nothing."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)
        human = account_deletion.page(conn, hub.mail.signing_key, token)
        if human is None:
            return _dead(conn, request, words, language)
        return _page(
            conn,
            request,
            words["delete_title"],
            words["delete_text"].format(handle=human.handle),
            more=(words["delete_removes"], words["delete_keeps"]),
            link=(words["delete_export"], account_deletion.export_url(hub.public_url)),
            button=words["delete_button"],
            language=language,
        )


@page_router.post("/mail/account-deletion/{token}")
def account_deletion_confirm(token: str, request: Request) -> HTMLResponse:
    """Deletes the account in one transaction, or says why it did not (§2.9)."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        # Read before the deletion removes the human's settings, the language with them.
        language = _language(conn, request, token)
        words = catalog.section("mail_links", language)

    def run() -> str | None:
        with events.transaction(engine_of(request)) as conn:
            return account_deletion.confirm(conn, hub, token)

    # A deadlock or serialisation failure rolls the whole deletion back; it runs again
    # (`db.retrying`), so it is never left half done or failed by a transient conflict.
    outcome = retrying(run)
    # The page after the deletion's own transaction: the frame reads the landing setting.
    with engine_of(request).begin() as conn:
        if outcome is None:
            return _dead(conn, request, words, language)
        if (
            outcome != "deleted"
        ):  # `namespace_owner`, `org_last_owner`, `last_instance_admin`: nothing changed
            return _page(
                conn,
                request,
                words["delete_title"],
                words[outcome],
                status=409,
                language=language,
            )
        return _page(conn, request, words["delete_title"], words["delete_done"], language=language)
