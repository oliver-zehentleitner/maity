"""The reset of a human's second factor without a recovery code (docs/api.md §2.8.3).

The instance admin asks, the human's verified address gets a link, and the reset takes
effect only when the human opens it and presses the button: an admin alone never strips a
human's second factor. The link names the generation of the factor it was issued for, so
once the human recovered with a recovery code, enrolled anew, turned the factor off, or
another reset took effect, it is dead. The operator of the server has the same effect at
once with `maity-hub second-factor reset` (`operator_reset`).

Taking effect is one transaction under the factor's row: the link consumed, the generation
checked and moved, the enrolment and the recovery codes deleted, every session of the human
ended; of two links racing only the first succeeds.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import second_factor, sessions
from maity_hub.config import Settings
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import mailer, preferences, tokens
from maity_hub.ratelimit import Limiter

PURPOSE = "second_factor_reset"
LINK_FOR = timedelta(hours=24)
REASON_MAX = 1024
BY_HUMAN = Limiter(3, 3600)  # requests for one human: an admin cannot fill a mailbox

_WORDS = {
    "en": {
        "subject": "[Maity] Reset your two-factor sign-in?",
        "text": (
            "{admin} asked to reset the two-factor sign-in of your Maity account on {url}, "
            "with this reason:\n\n{reason}\n\n"
            "If you want it reset, open this link and press the button: {link}\n\n"
            "The link is valid for 24 hours and works once. Nothing changes until you press "
            "the button. If you did not expect this, ignore this mail, and confirm the "
            "request with the person who made it by another channel before you use it: "
            "whoever holds this mailbox can reset your sign-in.\n"
        ),
    },
    "de": {
        "subject": "[Maity] Zwei-Faktor-Anmeldung zurücksetzen?",
        "text": (
            "{admin} möchte die Zwei-Faktor-Anmeldung deines Maity-Kontos auf {url} "
            "zurücksetzen, mit dieser Begründung:\n\n{reason}\n\n"
            "Wenn du sie zurücksetzen willst, öffne diesen Link und drücke den Knopf: "
            "{link}\n\n"
            "Der Link gilt 24 Stunden und nur einmal. Bis du den Knopf drückst, ändert sich "
            "nichts. Wenn du das nicht erwartet hast, ignoriere diese Mail und bestätige die "
            "Anfrage über einen anderen Kanal bei der Person, die sie gestellt hat, bevor du "
            "den Link benutzt: wer dieses Postfach hat, kann deine Anmeldung zurücksetzen.\n"
        ),
    },
}


def _nonce_id(nonce: str) -> str:
    """The row's id: the hash of the nonce, so the table holds nothing that opens a link."""
    return hashlib.sha256(nonce.encode()).hexdigest()


def _mail_ready(conn: Connection, hub: Settings) -> bool:
    resolved = mail_settings.resolve(conn, hub.mail, hub.secret_key)
    return bool(resolved.complete and resolved.enabled and hub.mail.signing_key is not None)


def request(conn: Connection, hub: Settings, caller: Any, human_id: str, reason: str) -> datetime:
    """`POST /admin/users/{id}/second-factor/reset`: mail the human a link; nothing else
    changes. Returns when the link expires."""
    if caller.principal_id == human_id:
        raise second_factor.refused("own_account", "use a recovery code, or the operator's command")
    target = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    if target is None:
        raise not_found()
    cleaned = reason.strip()
    if not 1 <= len(cleaned) <= REASON_MAX:
        raise invalid({"reason": "invalid"})
    second_factor.require_step_up(conn, hub, caller)
    if not _mail_ready(conn, hub):
        raise ApiError(409, "mail_not_configured", "the instance cannot send mail")
    settings_row = conn.execute(
        select(t.notification_settings).where(t.notification_settings.c.human_id == human_id)
    ).first()
    if (
        settings_row is None
        or settings_row.address_status != "verified"
        or settings_row.address is None
    ):
        raise ApiError(409, "address_unverified", "the human has no verified address")
    factor = second_factor.factor_of(conn, human_id, lock=True)
    if not second_factor.enrolled(factor):
        raise ApiError(409, "conflict", "no second factor is enrolled")
    wait = BY_HUMAN.hit(human_id)
    if wait:
        raise rate_limited(wait)
    now = clock.now()
    expires = now + LINK_FOR
    key = hub.mail.signing_key
    assert key is not None  # `_mail_ready` held it
    nonce = secrets.token_urlsafe(16)
    conn.execute(
        insert(t.second_factor_reset).values(
            id=_nonce_id(nonce),
            human_id=human_id,
            generation=factor.generation,
            requested_by=caller.principal_id,
            reason=cleaned,
            created_at=now,
            expires_at=expires,
        )
    )
    token = tokens.make(
        key,
        {
            "h": human_id,
            "p": PURPOSE,
            "n": nonce,
            "g": factor.generation,
            "x": int(expires.timestamp()),
        },
    )
    admin_handle = second_factor._handle(conn, caller.principal_id)
    language = str(preferences.preferences(conn, human_id)["email"]["language"])
    words = _WORDS.get(language, _WORDS["en"])
    outbox.enqueue(
        conn,
        kind="security",
        to=settings_row.address,
        subject=words["subject"],
        body=words["text"].format(
            admin=admin_handle,
            url=hub.public_url,
            reason=mailer.quoted(cleaned),
            link=f"{hub.public_url}/mail/second-factor-reset/{token}",
        ),
        human_id=human_id,
    )
    return expires


def _alive(conn: Connection, hub: Settings, token: str, *, lock: bool) -> Any | None:
    """The reset row the link names while the link still works, else None: signed by the
    hub, not expired, not used, and its factor generation still the human's."""
    payload = tokens.read(hub.mail.signing_key, token)
    if payload is None or payload.get("p") != PURPOSE:
        return None
    nonce, human_id = payload.get("n"), payload.get("h")
    if not isinstance(nonce, str) or not isinstance(human_id, str):
        return None
    factor = second_factor.factor_of(conn, human_id, lock=lock)
    query = select(t.second_factor_reset).where(
        t.second_factor_reset.c.id == _nonce_id(nonce),
        t.second_factor_reset.c.human_id == human_id,
    )
    row = conn.execute(query.with_for_update() if lock else query).first()
    if (
        row is None
        or factor is None
        or row.used_at is not None
        or row.expires_at <= clock.now()
        or payload.get("x") != int(row.expires_at.timestamp())
        or not isinstance(payload.get("g"), int)
        or not hmac.compare_digest(str(payload["g"]).encode(), str(row.generation).encode())
        or factor.generation != row.generation
        or not second_factor.enrolled(factor)
    ):
        return None
    return row


def page(conn: Connection, hub: Settings, token: str) -> dict[str, str] | None:
    """What the link's page shows while the link works: the account, the admin who asked
    and the reason as written; changes nothing."""
    row = _alive(conn, hub, token, lock=False)
    if row is None:
        return None
    human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).one()
    return {
        "handle": human.handle,
        "display_name": human.display_name,
        "admin": second_factor._handle(conn, row.requested_by),
        "reason": row.reason,
        "language": str(preferences.preferences(conn, row.human_id)["email"]["language"]),
    }


def take_effect(conn: Connection, hub: Settings, token: str) -> bool:
    """The human pressed the button: the reset, in the order and under the lock §2.8.3
    names. False when the link no longer works (never saying why)."""
    row = _alive(conn, hub, token, lock=True)
    if row is None:
        return False
    claimed = conn.execute(
        update(t.second_factor_reset)
        .where(t.second_factor_reset.c.id == row.id, t.second_factor_reset.c.used_at.is_(None))
        .values(used_at=clock.now())
    ).rowcount
    if claimed != 1:
        return False
    _reset(conn, row.human_id, second_factor._handle(conn, row.requested_by))
    return True


def operator_reset(conn: Connection, handle: str) -> bool:
    """`maity-hub second-factor reset --handle`: at once, by the operator of the server
    (§2.8.3). False when the human is not enrolled; None-handle humans do not exist."""
    human_id = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
    if human_id is None:
        raise not_found()
    if not second_factor.enrolled(second_factor.factor_of(conn, human_id, lock=True)):
        return False
    _reset(conn, human_id, "operator")
    return True


def _reset(conn: Connection, human_id: str, by: str) -> None:
    """The effect: the enrolment and the recovery codes go, the generation moves, the next
    sign-in must enrol, every session ends, and the human is told (§2.8.3)."""
    second_factor.remove(conn, human_id, reset=True)
    sessions.end_where(conn, t.human_session.c.human_id == human_id, "second_factor_reset")
    second_factor.changed(conn, human_id, "reset", by)
