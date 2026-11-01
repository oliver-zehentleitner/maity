"""Mail as the second factor (docs/api.md §2.8.8).

With `second_factor: email` every human who has not enrolled TOTP gets a second step after
the first factor: the hub mails a link and a six-digit code to the verified address, bound to
the one second-factor session they were sent for, valid while it lives (15 minutes) and single
use. Token and code are stored as HMAC-SHA-256 under `MAITY_MAIL_SIGNING_KEY` on the session,
never in a log or an event. This module sends the mail and checks what comes back; the session's
state and the gate are `second_factor`'s.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import ApiError, rate_limited
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import preferences
from maity_hub.ratelimit import Limiter

LIFETIME = timedelta(minutes=15)  # a mail-factor session's life, and the link's and code's
PER_SESSION = 3  # mails one session may be sent, the first included
# 10 mails per human and hour, the first factor's mail counting (§2.8.8).
BY_HUMAN = Limiter(10, 60 * 60, name="auth.mail_factor.BY_HUMAN")
VIA = "email"
UNAVAILABLE = "email_unavailable"  # the `method` of the account record when no mail can go


def _token_mac(key: bytes, id_hash: str, token: str) -> str:
    return hmac.new(
        key, f"mail-factor-token:{id_hash}:{token}".encode(), hashlib.sha256
    ).hexdigest()


def _code_mac(key: bytes, id_hash: str, code: str) -> str:
    return hmac.new(key, f"mail-factor-code:{id_hash}:{code}".encode(), hashlib.sha256).hexdigest()


def normalise_code(value: str) -> str | None:
    """The six digits, spaces ignored."""
    text = value.replace(" ", "")
    return text if len(text) == 6 and text.isascii() and text.isdigit() else None


def _key(hub: Settings) -> bytes | None:
    return hub.mail.signing_key


def mail_ready(conn: Connection, hub: Settings) -> bool:
    """Whether the mail settings are complete and enabled, and the signing key is there."""
    resolved = mail_settings.resolve(conn, hub.mail, hub.secret_key)
    return bool(resolved.complete and resolved.enabled and _key(hub) is not None)


def address_of(conn: Connection, human_id: str) -> Any:
    """The human's notification row when its address is verified, else None."""
    row = conn.execute(
        select(t.notification_settings).where(t.notification_settings.c.human_id == human_id)
    ).first()
    if row is None or row.address_status != "verified" or row.address is None:
        return None
    return row


def ever_had_address(conn: Connection, human_id: str) -> bool:
    flag = conn.execute(
        select(t.notification_settings.c.address_ever_verified).where(
            t.notification_settings.c.human_id == human_id
        )
    ).scalar()
    return bool(flag)


def _body(
    language: str,
    name: str,
    *,
    link: str | None,
    code: str,
    method: str,
    when: str,
    ip: str | None,
    browser: str | None,
    system: str | None,
) -> str:
    """The mail: the first factor's method, what the hub observed (time, address) and what the
    browser claims, the link (not in a step-up's mail), the code, and what to do if it was not
    the human (§2.8.8)."""
    name = " ".join(name.split())
    spaced = f"{code[:3]} {code[3:]}"
    where = ip or "?"
    claimed = f"{browser or '?'} / {system or '?'}"
    if language == "de":
        how = (
            "Jemand hat sich mit deinem Passwort angemeldet"
            if method == "password"
            else "Eine Anmeldung wurde von einer deiner Sitzungen aus freigegeben"
        )
        advice = (
            "Hast du das nicht getan, hat jemand dein Passwort: ändere es jetzt."
            if method == "password"
            else "Hast du das nicht getan, beende die Sitzungen, die du nicht kennst."
        )
        opening = f"Hallo {name},\n\n{how}. Zum Abschließen brauchst du den zweiten Faktor.\n\n"
        use_link = (
            "Öffne diesen Link in dem Browser, in dem du dich angemeldet hast:\n"
            f"{link}\n\nOder gib "
            if link
            else "Gib "
        )
        return (
            f"{opening}{use_link}diesen Code dort ein: {spaced}\n\n"
            f"Gesehen am {when} von {where}; der Browser gibt an: {claimed}.\n\n"
            f"Gib diesen Code niemals weiter: Maity fragt nie danach.\n{advice}\n"
        )
    how = (
        "Someone signed in with your password"
        if method == "password"
        else "A sign-in was approved from one of your sessions"
    )
    advice = (
        "If this was not you, someone has your password: change it now."
        if method == "password"
        else "If this was not you, end the sessions you do not know."
    )
    use_link = (
        f"Open this link in the browser where you signed in:\n{link}\n\nOr enter "
        if link
        else "Enter "
    )
    return (
        f"Hello {name},\n\n{how}. To finish, the second factor is needed.\n\n"
        f"{use_link}this code there: {spaced}\n\n"
        f"Seen at {when} from {where}; the browser claims: {claimed}.\n\n"
        f"Never give this code to anyone: Maity never asks for it.\n{advice}\n"
    )


def send(
    conn: Connection,
    hub: Settings,
    row: Any,
    *,
    with_link: bool = True,
) -> str:
    """Mail a new link and code to the session `row` (a second-factor session, or a full one for
    a step-up, which gets a code only). Returns `sent`; `rate_limited`, `mail_not_configured`
    and `address_unverified` are refused (§2.8.8). The session's three count for a
    second-factor session only: a full session that steps up often is held by the hour's ten
    alone. A new mail voids the earlier link and code."""
    key = _key(hub)
    if key is None or not mail_ready(conn, hub):
        raise ApiError(409, "mail_not_configured", "the instance's mail settings are not complete")
    address = address_of(conn, row.human_id)
    if address is None:
        raise ApiError(409, "address_unverified", "the account has no verified address")
    now = clock.now()
    if row.state == "second_factor" and row.mail_sent >= PER_SESSION:
        # the session's three: it will not send again, so the wait is the session's life left
        left = row.created_at + LIFETIME - now
        raise rate_limited(max(int(left.total_seconds()), 1))
    wait = BY_HUMAN.hit(row.human_id)  # the human's ten an hour; a step-up counts here only
    if wait:
        raise rate_limited(wait)
    token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    conn.execute(
        update(t.human_session)
        .where(t.human_session.c.id_hash == row.id_hash)
        .values(
            mail_token_mac=_token_mac(key, row.id_hash, token) if with_link else None,
            mail_code_mac=_code_mac(key, row.id_hash, code),
            mail_sent=t.human_session.c.mail_sent + 1,
            mail_sent_at=now,
        )
    )
    human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).one()
    language = preferences.preferences(conn, row.human_id)["email"]["language"]
    link = (
        f"{hub.public_url.rstrip('/')}/sign-in/second-factor/email#{token}" if with_link else None
    )
    body = _body(
        language,
        human.display_name,
        link=link,
        code=code,
        method="password" if row.method == "password" else row.method,
        when=clock.rfc3339(clock.now()),
        ip=row.ip,
        browser=row.browser,
        system=row.os,
    )
    outbox.enqueue(
        conn,
        kind="sign_in",  # a late code is useless: over its budget it is dropped, not held
        to=address.address,
        human_id=row.human_id,
        subject="[Maity] Zweiter Faktor" if language == "de" else "[Maity] Second factor",
        body=body,
    )
    return "sent"


def check(
    conn: Connection, hub: Settings, row: Any, *, code: str | None, token: str | None
) -> bool:
    """Whether the code or the token is the one mailed to this session and still unused. It is
    used up by the one conditional update, so of two concurrent checks one wins; a wrong or used
    value is the caller's to count (§2.8.6)."""
    key = _key(hub)
    if key is None:
        return False
    # A mail lives 15 minutes, in a session that lives for days too (a step-up's code, §2.8.8).
    if row.mail_sent_at is None or clock.now() - row.mail_sent_at >= LIFETIME:
        return False
    column = t.human_session.c
    if code is not None:
        text = normalise_code(code)
        if text is None:
            return False
        match = column.mail_code_mac == _code_mac(key, row.id_hash, text)
    elif token is not None:
        match = column.mail_token_mac == _token_mac(key, row.id_hash, token)
    else:
        return False
    used = conn.execute(
        update(t.human_session)
        .where(column.id_hash == row.id_hash, column.ended_at.is_(None), match)
        .values(mail_token_mac=None, mail_code_mac=None)
    )
    return used.rowcount == 1


def state_of(row: Any) -> dict[str, Any]:
    """What `GET /auth/session` says of the mail of a second-factor session: `sent`,
    `rate_limited` with `retry_after` (the session's three, or the human's ten an hour), or
    `unavailable` (no mail could be sent: §2.8.8)."""
    if row.mail_code_mac is not None:
        return {"mail": "sent"}
    wait = BY_HUMAN.blocked(row.human_id)
    if row.mail_sent >= PER_SESSION:
        left = row.created_at + LIFETIME - clock.now()
        return {"mail": "rate_limited", "retry_after": max(int(left.total_seconds()), 1)}
    if wait:
        return {"mail": "rate_limited", "retry_after": max(int(wait), 1)}
    return {"mail": "unavailable"}
