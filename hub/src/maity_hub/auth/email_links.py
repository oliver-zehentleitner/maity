"""Single-use state shared by a mailed link and its browser-bound code (§2.6.3).

Callers check current account, address and method eligibility in the same transaction
before consuming a flow. A human row lock serialises issuance, guesses and use on all
three engines; a conditional update remains the final single-use check.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.ratelimit import Limiter

LIFETIME = timedelta(minutes=15)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def code_mac(key: bytes, nonce_hash: str, code: str) -> str:
    return hmac.new(key, f"sign-in-code:{nonce_hash}:{code}".encode(), hashlib.sha256).hexdigest()


def normalise_code(value: str) -> str | None:
    value = value.replace(" ", "")
    return value if len(value) == 6 and value.isascii() and value.isdigit() else None


def lock_human(conn: Connection, human_id: str) -> None:
    conn.execute(select(t.human.c.id).where(t.human.c.id == human_id).with_for_update()).one()


def _daily(conn: Connection, human_id: str) -> Any:
    day = clock.now().date().isoformat()
    row = conn.execute(
        select(t.email_sign_in_day).where(
            t.email_sign_in_day.c.human_id == human_id, t.email_sign_in_day.c.day == day
        )
    ).first()
    if row is None:
        conn.execute(insert(t.email_sign_in_day).values(human_id=human_id, day=day, wrong_codes=0))
        row = conn.execute(
            select(t.email_sign_in_day).where(
                t.email_sign_in_day.c.human_id == human_id, t.email_sign_in_day.c.day == day
            )
        ).one()
    return row


@dataclass(frozen=True)
class Issued:
    nonce: str
    code: str | None
    expires_at: datetime


def issue(
    conn: Connection,
    *,
    human_id: str,
    address_epoch: int,
    pending: str,
    source: str,
    next_path: str,
    signing_key: bytes,
    requested_at: datetime | None = None,
) -> Issued | None:
    """Issue only after lookup. Unknown addresses never get a row or an account lookup
    on the response path. The pending value was already generated for every request."""
    lock_human(conn, human_id)
    now = clock.now()
    requested_at = requested_at or now
    newer = conn.execute(
        select(t.email_sign_in.c.nonce_hash)
        .where(
            t.email_sign_in.c.human_id == human_id,
            t.email_sign_in.c.source == source,
            t.email_sign_in.c.created_at > requested_at,
        )
        .limit(1)
    ).first()
    if newer is not None or requested_at + LIFETIME <= now:
        return None
    conn.execute(
        update(t.email_sign_in)
        .where(
            t.email_sign_in.c.human_id == human_id,
            t.email_sign_in.c.source == source,
            t.email_sign_in.c.used_at.is_(None),
        )
        .values(used_at=now, code_mac=None)
    )
    nonce = secrets.token_urlsafe(32)
    hashed = digest(nonce)
    code = (
        f"{secrets.randbelow(1_000_000):06d}" if _daily(conn, human_id).wrong_codes < 20 else None
    )
    expires = requested_at + LIFETIME
    conn.execute(
        insert(t.email_sign_in).values(
            nonce_hash=hashed,
            pending_hash=digest(pending),
            human_id=human_id,
            address_epoch=address_epoch,
            source=source,
            next_path=next_path,
            code_mac=code_mac(signing_key, hashed, code) if code is not None else None,
            wrong_codes=0,
            created_at=requested_at,
            expires_at=expires,
        )
    )
    return Issued(nonce, code, expires)


def live(conn: Connection, *, nonce_hash: str | None = None, pending: str | None = None) -> Any:
    """Read state; this does not consume a link (mail scanners only read)."""
    if nonce_hash is None and pending is None:
        return None
    key = (
        t.email_sign_in.c.nonce_hash == nonce_hash
        if nonce_hash is not None
        else t.email_sign_in.c.pending_hash == digest(pending or "")
    )
    return conn.execute(
        select(t.email_sign_in).where(
            key, t.email_sign_in.c.used_at.is_(None), t.email_sign_in.c.expires_at > clock.now()
        )
    ).first()


def use(conn: Connection, row: Any) -> bool:
    result = conn.execute(
        update(t.email_sign_in)
        .where(
            t.email_sign_in.c.nonce_hash == row.nonce_hash,
            t.email_sign_in.c.used_at.is_(None),
            t.email_sign_in.c.expires_at > clock.now(),
        )
        .values(used_at=clock.now(), code_mac=None)
    )
    return result.rowcount == 1


def try_code(conn: Connection, row: Any, value: str, signing_key: bytes) -> bool:
    """Under the human lock: a wrong guess commits even though the route answers an
    error. Five guesses kill this code; twenty kill all codes, never their links."""
    lock_human(conn, row.human_id)
    row = live(conn, nonce_hash=row.nonce_hash)
    if row is None:
        return False
    daily = _daily(conn, row.human_id)
    if row.code_mac is None or row.wrong_codes >= 5 or daily.wrong_codes >= 20:
        return False
    code = normalise_code(value)
    if code is not None and hmac.compare_digest(
        row.code_mac, code_mac(signing_key, row.nonce_hash, code)
    ):
        return use(conn, row)
    wrong = row.wrong_codes + 1
    conn.execute(
        update(t.email_sign_in)
        .where(t.email_sign_in.c.nonce_hash == row.nonce_hash)
        .values(wrong_codes=wrong, code_mac=None if wrong >= 5 else row.code_mac)
    )
    conn.execute(
        update(t.email_sign_in_day)
        .where(
            t.email_sign_in_day.c.human_id == row.human_id,
            t.email_sign_in_day.c.day == daily.day,
        )
        .values(wrong_codes=daily.wrong_codes + 1)
    )
    if daily.wrong_codes + 1 >= 20:
        conn.execute(
            update(t.email_sign_in)
            .where(t.email_sign_in.c.human_id == row.human_id)
            .values(code_mac=None)
        )
    return False


def void_human(conn: Connection, human_id: str) -> None:
    conn.execute(
        update(t.email_sign_in)
        .where(t.email_sign_in.c.human_id == human_id, t.email_sign_in.c.used_at.is_(None))
        .values(used_at=clock.now(), code_mac=None)
    )


def void_open(conn: Connection) -> None:
    """Invalidate existing grants when the instance disables mail sign-in."""
    conn.execute(
        update(t.email_sign_in)
        .where(t.email_sign_in.c.used_at.is_(None))
        .values(used_at=clock.now(), code_mac=None)
    )


def mail_body(
    *,
    language: str,
    display_name: str,
    link: str,
    code: str | None,
    requested_at: str,
    browser: str | None,
    system: str | None,
    address: str,
) -> str:
    """A requested sign-in mail, without notification/unsubscribe content (§2.6.3).
    The only URL is the signed link; the saved dashboard destination stays in state."""
    name = " ".join(display_name.split())
    browser, system = browser or "?", system or "?"
    spaced = f"{code[:3]} {code[3:]}" if code else None
    if language == "de":
        alternative = (
            "Oder gib diesen Code in dem Browser ein, "
            f"in dem du den Link angefordert hast: {spaced}\n\n"
            if spaced
            else ""
        )
        return (
            f"Hallo {name},\n\nMit diesem Link meldest du dich bei Maity an (15 Minuten gültig):\n"
            f"{link}\n\n{alternative}Angefordert am {requested_at}, mit {browser} auf {system}, "
            f"von {address}.\n\nWenn du das nicht angefordert hast, ignoriere diese Mail. "
            "Ohne den Link oder den Code passiert nichts.\n"
        )
    alternative = (
        f"Or enter this code in the browser where you asked for it: {spaced}\n\n" if spaced else ""
    )
    return (
        f"Hello {name},\n\nUse this link to sign in to Maity (valid for 15 minutes):\n"
        f"{link}\n\n{alternative}Requested at {requested_at}, from {browser} on {system}, "
        f"{address}.\n\nIf you did not ask for this, ignore this mail; nothing happens "
        "without the link or the code.\n"
    )


class RequestLimits:
    """Only the source limit is observable; pair limits silently suppress delivery.
    Keys contain hashes, and existing and unknown addresses take the same path."""

    def __init__(self) -> None:
        self.by_source = Limiter(10, 3600)
        self.pair_quarter = Limiter(3, 900)
        self.pair_day = Limiter(10, 86400)

    def take(self, address: str, source: str) -> tuple[int, bool]:
        wait = self.by_source.hit(source)
        if wait:
            return wait, False
        normalised = address.strip().casefold()
        key = digest(f"{source}\0{normalised}")
        quarter = self.pair_quarter.hit(key)
        day = self.pair_day.hit(key)
        return 0, not (quarter or day)
