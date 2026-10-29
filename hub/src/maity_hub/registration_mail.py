"""The mail registration sends (docs/api.md §2.7.1): the link to confirm an address, and
the note to an address that has an account already.

Both go through the mail outbox in the caller's transaction, so they leave only if it
commits, and on the registration budget (§16.2): over it nothing is sent, as for
sign-in mail. A reply to a request: plain text in the language the request's
`Accept-Language` names, the headers of §18.5 and no unsubscribe part. The link names
no handle, no project and no other link; the hub keeps of it only the hash of its nonce
with the pending registration.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import sessions
from maity_hub.mail import outbox
from maity_hub.notifications import tokens

KINDS = ("register_link", "already_registered")

_WORDS = {
    "en": {
        "confirm_subject": "[Maity] Confirm your address",
        "confirm": (
            "Someone asked to create a Maity account with this address on {url}.\n\n"
            "Confirm your address and choose your name: {link}\n\n"
            "The link is valid for 24 hours.\n\n"
            "Requested: {time}, from {browser} on {os}, address {ip}.\n\n"
            "If you did not ask for this, ignore this mail; no account is created without "
            "the link and the password chosen with it.\n"
        ),
        "known_subject": "[Maity] About your address",
        "known": (
            "Someone asked to create a Maity account with this address on {url}. "
            "You have one already: sign in at {login}. If this was not you, ignore this "
            "mail.\n"
        ),
    },
    "de": {
        "confirm_subject": "[Maity] Adresse bestätigen",
        "confirm": (
            "Jemand wollte mit dieser Adresse ein Maity-Konto auf {url} anlegen.\n\n"
            "Bestätige deine Adresse und wähle deinen Namen: {link}\n\n"
            "Der Link gilt 24 Stunden.\n\n"
            "Angefragt: {time}, von {browser} auf {os}, Adresse {ip}.\n\n"
            "Wenn du das nicht warst, ignoriere diese Mail; ohne den Link und das dabei "
            "gewählte Passwort entsteht kein Konto.\n"
        ),
        "known_subject": "[Maity] Zu deiner Adresse",
        "known": (
            "Jemand wollte mit dieser Adresse ein Maity-Konto auf {url} anlegen. "
            "Du hast schon eins: melde dich an unter {login}. Wenn du das nicht warst, "
            "ignoriere diese Mail.\n"
        ),
    },
}
_LANGUAGE = re.compile(r"^\s*([A-Za-z]{2,3})(?:-[A-Za-z0-9-]+)?\s*(?:;|,|$)")


def language_of(accept_language: str | None) -> str:
    """The first language of an `Accept-Language` the hub has, else English (§2.7.1)."""
    for part in (accept_language or "").split(","):
        found = _LANGUAGE.match(part)
        if found and found.group(1).lower() in _WORDS:
            return found.group(1).lower()
    return "en"


def send(
    conn: Connection,
    *,
    kind: str,
    to: str,
    pending_id: str | None = None,
    language: str | None = None,
    hub: Any = None,
) -> None:
    """Send one registration mail in the caller's transaction (it goes out only if that
    commits). `language` is the request's `Accept-Language`, for the note to an address with
    an account (a confirmation link takes it from its pending registration). Without the
    hub's settings, or without a signing key, nothing is sent."""
    if kind not in KINDS:
        raise ValueError(f"unknown registration mail {kind}")
    if hub is None or hub.mail.signing_key is None:
        return
    if kind == "already_registered":
        words = _WORDS[language_of(language)]
        body = words["known"].format(url=hub.public_url, login=f"{hub.public_url}/#/login")
        subject = words["known_subject"]
    else:
        subject, body = _confirm(conn, hub, pending_id)
    outbox.enqueue(conn, kind="registration", to=to, subject=subject, body=body)


def _confirm(conn: Connection, hub: Any, pending_id: str | None) -> tuple[str, str]:
    pending = conn.execute(
        select(t.pending_registration).where(t.pending_registration.c.id == pending_id)
    ).one()
    nonce = secrets.token_urlsafe(16)
    conn.execute(
        update(t.pending_registration)
        .where(t.pending_registration.c.id == pending.id)
        .values(nonce_hash=hashlib.sha256(nonce.encode()).hexdigest())
    )
    token = tokens.make(
        hub.mail.signing_key,
        {"i": pending.id, "p": "register", "n": nonce, "x": int(pending.expires_at.timestamp())},
    )
    words = _WORDS[language_of(pending.language)]
    browser, system = sessions.describe(pending.user_agent)
    body = words["confirm"].format(
        url=hub.public_url,
        link=f"{hub.public_url}/mail/register/{token}",
        time=clock.rfc3339(pending.created_at),
        browser=browser or "?",
        os=system or "?",
        ip=pending.source_ip,
    )
    return words["confirm_subject"], body
