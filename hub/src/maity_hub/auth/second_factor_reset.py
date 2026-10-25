"""Resetting a human's second factor (docs/api.md §2.8.3): an instance admin asks, the
human confirms through a mailed link, so neither alone strips the factor; and the
operator's command on the server as the last way in.

A link names the factor's generation it was issued for. Recovery with a recovery code,
a new enrolment, turning the factor off or another reset moves the generation, and every
link issued before is dead from then on.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import second_factor, sessions
from maity_hub.config import Settings
from maity_hub.errors import ApiError, not_found, rate_limited
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import preferences, tokens
from maity_hub.notifications.mailer import quoted
from maity_hub.ratelimit import Limiter

LINK_LIFETIME = timedelta(hours=24)
PURPOSE = "second_factor_reset"
REQUESTS_BY_TARGET = Limiter(3, 24 * 60 * 60)  # 3 per day per human reset (§2.8.6)

_MAIL = {
    "en": {
        "subject": "[Maity] Reset your two-factor sign-in?",
        "body": (
            "{admin}, the administrator of {url}, asked to reset the two-factor sign-in of "
            "your account {handle}. Their reason: {reason}\n\n"
            "Nothing happens unless you confirm here: {link}\n\n"
            "Resetting ends every session of your account; your next sign-in sets up the "
            "second factor again. The link is valid for 24 hours. If you did not ask your "
            "administrator for this, do not confirm, and tell them.\n"
        ),
    },
    "de": {
        "subject": "[Maity] Zwei-Faktor-Anmeldung zurücksetzen?",
        "body": (
            "{admin}, Administrator von {url}, möchte die Zwei-Faktor-Anmeldung deines "
            "Kontos {handle} zurücksetzen. Begründung: {reason}\n\n"
            "Es passiert nichts, solange du hier nicht bestätigst: {link}\n\n"
            "Das Zurücksetzen beendet alle Sitzungen deines Kontos; bei der nächsten "
            "Anmeldung richtest du den zweiten Faktor neu ein. Der Link gilt 24 Stunden. "
            "Hast du das nicht erbeten, bestätige nicht und sag es deinem Administrator.\n"
        ),
    },
}


def _handle(conn: Connection, human_id: str) -> str:
    return str(conn.execute(select(t.human.c.handle).where(t.human.c.id == human_id)).scalar_one())


def request_reset(
    conn: Connection, hub: Settings, admin_id: str, target_id: str, reason: str
) -> str:
    """`POST /admin/users/{id}/second-factor/reset`: mails the human the link; returns
    when it expires. The caller has checked `instance:admin` and step-up."""
    if target_id == admin_id:
        raise ApiError(403, "forbidden", "not your own factor", {"reason": "own_account"})
    target = conn.execute(select(t.human).where(t.human.c.id == target_id)).first()
    if target is None:
        raise not_found()
    factor = second_factor.factor_of(conn, target_id, lock=True)
    if not second_factor.enrolled(factor):
        raise ApiError(409, "conflict", "this human has no second factor to reset")
    resolved = mail_settings.resolve(conn, hub.mail, hub.secret_key)
    if not (resolved.complete and resolved.enabled) or hub.mail.signing_key is None:
        raise ApiError(409, "mail_not_configured", "the instance has no working mail")
    address = conn.execute(
        select(t.notification_settings.c.address).where(
            t.notification_settings.c.human_id == target_id,
            t.notification_settings.c.address_status == "verified",
        )
    ).scalar()
    if address is None:
        raise ApiError(409, "address_unverified", "the reset mail cannot reach this human")
    wait = REQUESTS_BY_TARGET.hit(target_id)
    if wait:
        raise rate_limited(wait)
    now = clock.now()
    expires = now + LINK_LIFETIME
    nonce = secrets.token_urlsafe(24)
    conn.execute(
        insert(t.second_factor_reset).values(
            id=hashlib.sha256(nonce.encode()).hexdigest(),
            human_id=target_id,
            generation=factor.generation,
            requested_by=admin_id,
            reason=reason,
            created_at=now,
            expires_at=expires,
        )
    )
    token = tokens.make(
        hub.mail.signing_key,
        {
            "h": target_id,
            "p": PURPOSE,
            "n": nonce,
            "g": factor.generation,
            "x": int(expires.timestamp()),
        },
    )
    language = preferences.preferences(conn, target_id)["email"]["language"]
    words = _MAIL[language]
    outbox.enqueue(
        conn,
        kind="security",
        human_id=target_id,
        to=address,
        subject=words["subject"],
        body=words["body"].format(
            admin=_handle(conn, admin_id),
            url=hub.public_url,
            handle=target.handle,
            reason=quoted(reason),
            link=f"{hub.public_url}/mail/second-factor-reset/{token}",
        ),
    )
    return clock.rfc3339(expires)


def _live_request(conn: Connection, signing_key: bytes | None, token: str) -> Any:
    """The request a token names, while it may still take effect, else None — never
    which reason: invalid, expired, used, or of a superseded generation (§18.6)."""
    payload = tokens.read(signing_key, token)
    if payload is None or payload.get("p") != PURPOSE:
        return None
    nonce = payload.get("n")
    if not isinstance(nonce, str):
        return None
    row = conn.execute(
        select(t.second_factor_reset).where(
            t.second_factor_reset.c.id == hashlib.sha256(nonce.encode()).hexdigest()
        )
    ).first()
    if (
        row is None
        or row.human_id != payload.get("h")
        or row.generation != payload.get("g")
        or row.used_at is not None
        or row.expires_at <= clock.now()
    ):
        return None
    factor = second_factor.factor_of(conn, row.human_id)
    if factor is None or factor.generation != row.generation or not second_factor.enrolled(factor):
        return None
    return row


def page(conn: Connection, signing_key: bytes | None, token: str) -> dict[str, str] | None:
    """What the confirmation page shows: whose account, who asked, why."""
    row = _live_request(conn, signing_key, token)
    if row is None:
        return None
    return {
        "handle": _handle(conn, row.human_id),
        "admin": _handle(conn, row.requested_by),
        "reason": row.reason,
        "human_id": row.human_id,
    }


def confirm(conn: Connection, signing_key: bytes | None, token: str) -> bool:
    """The human's button: one transaction — the link consumed, the generation checked
    and moved, the factor and the recovery codes gone, every session ended. Of two
    links racing, the first wins; the second finds the generation moved."""
    row = _live_request(conn, signing_key, token)
    if row is None:
        return False
    factor = second_factor.factor_of(conn, row.human_id, lock=True)
    if factor is None or factor.generation != row.generation:
        return False
    used = conn.execute(
        update(t.second_factor_reset)
        .where(t.second_factor_reset.c.id == row.id, t.second_factor_reset.c.used_at.is_(None))
        .values(used_at=clock.now())
    )
    if used.rowcount != 1:
        return False
    apply(conn, row.human_id, by=_handle(conn, row.requested_by))
    return True


def apply(conn: Connection, human_id: str, *, by: str) -> None:
    """The reset itself: the next sign-in enrols first, whatever the policy (§2.8.3)."""
    second_factor.remove(conn, human_id, reset=True)
    sessions.end_where(conn, t.human_session.c.human_id == human_id, "second_factor_reset")
    second_factor.changed(conn, human_id, "reset", by)


def operator_reset(conn: Connection, handle: str) -> str | None:
    """`maity-hub second-factor reset --handle`: at once, no mail, no key needed."""
    human_id = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
    if human_id is None:
        return None
    second_factor.factor_of(conn, human_id, lock=True)
    apply(conn, human_id, by="operator")
    return str(human_id)
