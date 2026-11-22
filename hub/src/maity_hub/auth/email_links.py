"""Single-use state shared by a mailed link and its browser-bound code (§2.6.3).

Callers check current account, address and method eligibility in the same transaction
before consuming a flow. A human row lock serialises issuance, guesses and use on all
three engines; a conditional update remains the final single-use check.

The single-use rows themselves, the human row lock and the request limits are implemented
once, for this table and `password_reset` alike, in auth/single_use.py; the names here
(`issue`, `use`, `void_human`, `void_open`, `RequestLimits`, `lock_human`, `digest`,
`recipient_over` and the recipient's limits) are thin wrappers over it or re-exports of it.
This module holds what only the sign-in link has: the code, its MAC, the per-day count of
wrong codes, the reading of a row by nonce or browser (`live`) and the mail.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import catalog, clock
from maity_hub import tables as t
from maity_hub.auth import single_use, totp
from maity_hub.auth.single_use import RECIPIENT_MAILS_PER_DAY as RECIPIENT_MAILS_PER_DAY
from maity_hub.auth.single_use import RECIPIENT_MAILS_PER_HOUR as RECIPIENT_MAILS_PER_HOUR
from maity_hub.auth.single_use import RECIPIENT_PER_DAY as RECIPIENT_PER_DAY
from maity_hub.auth.single_use import RECIPIENT_PER_HOUR as RECIPIENT_PER_HOUR
from maity_hub.auth.single_use import Recipient as Recipient
from maity_hub.auth.single_use import digest as digest
from maity_hub.auth.single_use import lock_human as lock_human
from maity_hub.auth.single_use import recipient_over as recipient_over

LIFETIME = timedelta(minutes=15)
# A spent row's code dies with it.
KIND = single_use.Kind(t.email_sign_in, LIFETIME, cleared=("code_mac",))


def code_mac(key: bytes, nonce_hash: str, code: str) -> str:
    return hmac.new(key, f"sign-in-code:{nonce_hash}:{code}".encode(), hashlib.sha256).hexdigest()


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
    on the response path. The pending value was already generated for every request.
    The shared steps are `single_use.start` and `single_use.add`; the code is drawn between
    them, after the earlier row is voided and before the new one is written."""
    at = single_use.start(conn, KIND, human_id=human_id, source=source, requested_at=requested_at)
    if at is None:
        return None
    nonce = secrets.token_urlsafe(32)
    hashed = digest(nonce)
    code = totp.new_six() if _daily(conn, human_id).wrong_codes < 20 else None
    expires = single_use.add(
        conn,
        KIND,
        nonce_hash=hashed,
        human_id=human_id,
        source=source,
        requested_at=at,
        pending_hash=digest(pending),
        address_epoch=address_epoch,
        next_path=next_path,
        code_mac=code_mac(signing_key, hashed, code) if code is not None else None,
        wrong_codes=0,
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
    return single_use.use(conn, KIND, row)


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
    code = totp.normalise_six(value)
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
    single_use.void_human(conn, KIND, human_id)


def void_open(conn: Connection) -> None:
    """Invalidate existing grants when the instance disables mail sign-in."""
    single_use.void_open(conn, KIND)


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
    words = catalog.section("sign_in", language)
    alternative = words["mail_alternative"].format(code=code) if code else ""
    return words["mail"].format(
        name=name,
        link=link,
        alternative=alternative,
        requested_at=requested_at,
        browser=browser,
        system=system,
        address=address,
    )


PREFIX = "auth.email_links"  # the limiters' names: keys of the shared counts, never renamed


class RequestLimits(single_use.RequestLimits):
    """`POST /auth/email-link` (§2.6.4), in buckets named under `auth.email_links`: only the
    source limit is observable; the pair limits and the recipient's silently suppress
    delivery (auth/single_use.py)."""

    def __init__(self) -> None:
        super().__init__(PREFIX)
