"""A human's mail address and its lifecycle (docs/api.md §18.4, §2.6.3).

The address sits in the notification settings row, beside the settings, but it is account
identity: the verified address is a sign-in factor and where the security mail goes. Setting an
address puts it in `pending_address` and mails a link valid for 24 hours; the verified address
keeps receiving until the new one is verified. Once a verified address exists, changing or
removing it needs the human's own confirmation: the password, or for a human without one an
approval from a session in good standing at least 24 hours old. One account per address: the
verified address is claimed under the per-address lock. The old address hears of a change.

The settings themselves (`preferences`) call into this module, never the other way round
(hub/context/notifications.md, "The address lifecycle is a module of its own").
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import admin, catalog, clock
from maity_hub import tables as t
from maity_hub.auth import known_sources, passwords, sessions
from maity_hub.auth.email_links import recipient_over
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.mail import address as addresses
from maity_hub.mail import outbox
from maity_hub.notifications import records, tokens
from maity_hub.ratelimit import Attempt, Limiter
from maity_hub.text_language import text_language

VERIFY_FOR = timedelta(hours=24)
# Verification mails (§18.4): 3 an hour and 10 a day per human, refused beyond; and per
# recipient address, counted in asking accounts: an account's first mail to the address in a
# window takes one of 3 places an hour and 10 a day, its further ones none (they are held by
# its own limit); and at most 9 mails queued in any hour and 100 in any day from all accounts,
# counted at the request, not at delivery, which two accounts at their own limits (6 an hour,
# 20 a day) never reach. Not queued beyond, silently (`email_links.recipient_over`).
VERIFY_BY_HUMAN_HOUR = Limiter(3, 3600, name="notifications.verify.human_hour")
VERIFY_BY_HUMAN_DAY = Limiter(10, 86400, name="notifications.verify.human_day")
VERIFY_BY_RECIPIENT_HOUR = Limiter(3, 3600, name="notifications.verify.recipient_hour")
VERIFY_BY_RECIPIENT_DAY = Limiter(10, 86400, name="notifications.verify.recipient_day")
VERIFY_BY_RECIPIENT_HOUR_ACCOUNTS = Limiter(
    1, 3600, name="notifications.verify.recipient_hour_accounts"
)
VERIFY_BY_RECIPIENT_DAY_ACCOUNTS = Limiter(
    1, 86400, name="notifications.verify.recipient_day_accounts"
)
VERIFY_BY_RECIPIENT_MAILS_HOUR = Limiter(
    9, 3600, name="notifications.verify.recipient_mails_hour", exact=True
)
VERIFY_BY_RECIPIENT_MAILS_DAY = Limiter(
    100, 86400, name="notifications.verify.recipient_mails_day", exact=True
)
APPROVER_AGE = timedelta(hours=24)
HELD_FOR = timedelta(days=7)
# The requesting session's data kept with a pending address, cleared with it.
NO_PENDING_ORIGIN: dict[str, Any] = {
    "pending_browser": None,
    "pending_os": None,
    "pending_ip": None,
}


# --- the settings row ----------------------------------------------------------------


def row_of(conn: Connection, human_id: str, *, lock: bool = False) -> Any:
    """The human's settings row. A read of a human who never changed anything finds none
    and sees the defaults; the row is made by the first write (`lock=True`)."""
    query = select(t.notification_settings).where(t.notification_settings.c.human_id == human_id)
    found = conn.execute(query.with_for_update() if lock else query).first()
    if found is not None:
        return found
    if not lock:
        return _NONE
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.notification_settings).values(
                    human_id=human_id,
                    preferences={},
                    address_status="none",
                    epoch=0,
                    hard_failures=0,
                    updated_at=clock.now(),
                )
            )
    except IntegrityError:  # a first write of the same human committed between our read and insert
        pass
    return conn.execute(query.with_for_update()).one()


def verified_row(conn: Connection, human_id: str) -> Any:
    """The human's settings row when it holds a verified address, else None."""
    row = conn.execute(
        select(t.notification_settings).where(t.notification_settings.c.human_id == human_id)
    ).first()
    if row is None or row.address_status != "verified" or row.address is None:
        return None
    return row


_NONE = SimpleNamespace(
    preferences={},
    address=None,
    address_status="none",
    verified_at=None,
    pending_address=None,
    hard_failures=0,
    disabled_at=None,
    address_change=None,
)


def held(row: Any) -> dict[str, Any] | None:
    """The address change held for approval, while it has not lapsed."""
    change = row.address_change
    if not change:
        return None
    requested = datetime.fromisoformat(change["requested_at"].replace("Z", "+00:00"))
    if clock.now() - requested >= HELD_FOR:
        return None  # a held change lapses after 7 days
    return dict(change)


# --- the address (§18.4) -------------------------------------------------------------


def change_address(
    conn: Connection,
    *,
    row: Any,
    human: Any,
    session: Any,
    wanted: str | None,
    given_password: Any,
    signing_key: bytes | None,
    public_url: str,
    mail_ready: bool,
    password_attempt: Callable[[], Attempt],
    step_up: Callable[[], None],
    keeps_factor: Callable[[], None],
) -> int:
    """The address part of a settings `PATCH`: 200 when it was applied, 202 when the change is
    held for approval."""
    if wanted is not None and not mail_ready:
        raise ApiError(409, "mail_not_configured", "the instance cannot send mail")
    verified = row.address_status in ("verified", "disabled") and row.address is not None
    moves = verified and wanted != row.address
    if moves and wanted is None:
        _keeps_admin_address(conn, human.id)
    if moves:
        step_up()  # changing or removing the verified address is a sensitive call (§2.8.4)
        if wanted is None and row.address_status == "verified":
            keeps_factor()  # under `email` it may be the account's second factor (§2.8.8)
        if human.password_hash is not None:
            if not isinstance(given_password, str) or not given_password:
                raise invalid({"current_password": "required"})
            # Wrong passwords count here too, in a bucket of their own, before the compare (§2.1).
            with password_attempt() as attempt:
                if not passwords.verify_password(given_password, human.password_hash):
                    attempt.wrong()
                    raise invalid({"current_password": "mismatch"})
        else:
            pending = held(row)
            standing = sessions.good_standing(session)
            if not standing and pending is not None:
                raise _session_forbidden("not_in_good_standing")
            if not standing or clock.now() - session.created_at < APPROVER_AGE:
                change = {
                    "id": f"adc-{secrets.token_hex(6)}",
                    "address": wanted,
                    "requested_at": clock.rfc3339(clock.now()),
                    "session_id": session.public_id,
                }
                conn.execute(
                    update(t.notification_settings)
                    .where(t.notification_settings.c.human_id == human.id)
                    .values(address_change=change, updated_at=clock.now())
                )
                return 202
    apply_address(
        conn, row=row, human_id=human.id, wanted=wanted, signing_key=signing_key,
        public_url=public_url, session=session,
    )  # fmt: skip
    return 200


def apply_address(
    conn: Connection,
    *,
    row: Any,
    human_id: str,
    wanted: str | None,
    signing_key: bytes | None,
    public_url: str,
    session: Any,
) -> None:
    """Set the address to verify, or remove it. Setting it again, also the same one,
    sends a new link and voids the old one. A change or removal of the verified address
    withdraws a pending deletion request (§2.9): its link went to that address. The
    session's browser, system and IP address are kept with the pending address until it is
    verified, replaced, voided or expired, for the notice to the old address."""
    from maity_hub import account_deletion

    now = clock.now()
    verified = row.address is not None and row.address_status in ("verified", "disabled")
    if verified and wanted != row.address:
        account_deletion.withdraw(conn, human_id, "address")
    if wanted is None:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human_id)
            .values(
                address=None,
                address_normalized=None,
                address_status="none",
                verified_at=None,
                pending_address=None,
                pending_nonce=None,
                pending_expires_at=None,
                **NO_PENDING_ORIGIN,
                epoch=row.epoch + 1,
                address_change=None,
                updated_at=now,
            )
        )
        _epoch_moved(conn, human_id)
        if row.address is not None and row.address_status in ("verified", "disabled"):
            _tell_old_address(conn, human_id, row.address, None, session, public_url)
        return
    # The human's own limits are told (`rate_limited`); nothing is changed then.
    wait = VERIFY_BY_HUMAN_HOUR.blocked(human_id) or VERIFY_BY_HUMAN_DAY.blocked(human_id)
    if wait:
        raise rate_limited(wait)
    VERIFY_BY_HUMAN_HOUR.hit(human_id)
    VERIFY_BY_HUMAN_DAY.hit(human_id)
    nonce = secrets.token_hex(8)
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == human_id)
        .values(
            pending_address=wanted,
            pending_nonce=nonce,
            pending_expires_at=now + VERIFY_FOR,
            # Where the change was asked from, for the notice to the old address at its
            # verification (§2.6.3, §18.4); a new request replaces it with its own.
            pending_browser=session.browser,
            pending_os=session.os,
            pending_ip=session.ip,
            address_status=row.address_status if row.address else "pending",
            address=row.address,
            address_change=None,
            updated_at=now,
        )
    )
    assert signing_key is not None  # mail_ready includes the signing key
    token = tokens.make(
        signing_key,
        {
            "h": human_id,
            "p": "verify",
            "a": wanted,
            "n": nonce,
            "x": int((now + VERIFY_FOR).timestamp()),
        },
    )
    link = f"{public_url}/mail/verify/{token}"
    if _recipient_over(known_sources.address_key(conn, addresses.normalized(wanted)), human_id):
        return  # the address had its share: the link stays pending, no mail is sent
    # Never the handle, the name or projects: nobody confirmed this address yet (§18.4).
    # The language is the human's own (§6.2); it names nobody.
    words = catalog.section("mail", text_language(conn, human_id))
    outbox.enqueue(
        conn,
        kind="verification",  # a budget of its own: security mail never waits behind it
        human_id=human_id,
        to=wanted,
        extra_headers={"_purpose": "verify"},
        subject=f"[Maity] {words['verify_subject']}",
        body=words["verify_body"].format(url=public_url, address=wanted, link=link),
    )


def _recipient_over(address_key: str, human_id: str) -> bool:
    """Count one verification mail to the address of `address_key` (its
    `known_sources.address_key`), asked by `human_id`, against the address's hour and day in
    asking accounts; True when the address has no place left for it."""
    limiters = (
        VERIFY_BY_RECIPIENT_HOUR,
        VERIFY_BY_RECIPIENT_DAY,
        VERIFY_BY_RECIPIENT_HOUR_ACCOUNTS,
        VERIFY_BY_RECIPIENT_DAY_ACCOUNTS,
        VERIFY_BY_RECIPIENT_MAILS_HOUR,
        VERIFY_BY_RECIPIENT_MAILS_DAY,
    )
    return recipient_over(limiters, address_key, human_id)


def verify(
    conn: Connection,
    token: str,
    signing_key: bytes | None,
    public_url: str,
    *,
    secret_key: bytes | None,
    human_id: str | None = None,
) -> bool:
    """Confirm an address from its link; False for every link that does not work, never
    which reason. With `human_id`, only that human's token counts."""
    payload = tokens.read(signing_key, token)
    if payload is None or payload.get("p") != "verify":
        return False
    owner = str(payload.get("h"))
    if human_id is not None and owner != human_id:
        return False
    from maity_hub import write_guard

    # The account's lock first, in the order a deletion takes it (§2.9, `write_guard`):
    # this link's change withdraws a pending deletion.
    write_guard.share(conn, owner)
    row = conn.execute(
        select(t.notification_settings)
        .where(t.notification_settings.c.human_id == owner)
        .with_for_update()
    ).first()
    now = clock.now()
    if (
        row is None
        or row.pending_nonce is None
        or payload.get("n") != row.pending_nonce
        or payload.get("a") != row.pending_address
        or row.pending_expires_at is None
        or now >= row.pending_expires_at
    ):
        return False
    # One account per address: the claim, under the per-address lock (§18.4). A link for
    # an address another account verified meanwhile is a dead link, never why.
    claimed = addresses.normalized(row.pending_address)
    addresses.lock(conn, secret_key, claimed)
    taken = conn.execute(
        select(t.notification_settings.c.human_id).where(
            t.notification_settings.c.address_normalized == claimed,
            t.notification_settings.c.human_id != owner,
        )
    ).first()
    if taken is not None:
        return False
    previous = row.address if row.address_status in ("verified", "disabled") else None
    # Where the change was asked from; none for a request older than the hub's keeping it
    # (migration 20261115000000_address_where), whose notice leaves the line out.
    kept = (row.pending_browser, row.pending_os, row.pending_ip)
    origin = None
    if any(value is not None for value in kept):
        origin = SimpleNamespace(browser=kept[0], os=kept[1], ip=kept[2])
    try:
        with conn.begin_nested():
            conn.execute(
                update(t.notification_settings)
                .where(t.notification_settings.c.human_id == owner)
                .values(
                    address_normalized=claimed,
                    address=row.pending_address,
                    address_status="verified",
                    verified_at=now,
                    address_ever_verified=True,
                    pending_address=None,
                    pending_nonce=None,
                    pending_expires_at=None,
                    **NO_PENDING_ORIGIN,
                    hard_failures=0,
                    disabled_at=None,
                    epoch=row.epoch + (1 if previous and previous != row.pending_address else 0),
                    updated_at=now,
                )
            )
    except IntegrityError:  # the unique constraint caught what the lock did not
        return False
    if previous is not None and previous != row.pending_address:
        _epoch_moved(conn, owner)
        from maity_hub import account_deletion

        account_deletion.withdraw(conn, owner, "address")  # §2.9
        _tell_old_address(conn, owner, previous, row.pending_address, origin, public_url)
    return True


def claim_verified(
    conn: Connection, normalized: str, human_id: str, *, secret_key: bytes | None
) -> bool:
    """Write `normalized` as the human's verified address, as a registration's completion
    does (§2.7.1, §18.4), under the per-address lock: False when another account holds
    it. The human has no settings yet; the defaults apply."""
    addresses.lock(conn, secret_key, normalized)
    taken = conn.execute(
        select(t.notification_settings.c.human_id).where(
            t.notification_settings.c.address_normalized == normalized
        )
    ).first()
    if taken is not None:
        return False
    now = clock.now()
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.notification_settings).values(
                    human_id=human_id,
                    preferences={},
                    address=normalized,
                    address_normalized=normalized,
                    address_status="verified",
                    verified_at=now,
                    address_ever_verified=True,
                    epoch=0,
                    hard_failures=0,
                    updated_at=now,
                )
            )
    except IntegrityError:  # the unique constraint caught what the lock did not
        return False
    return True


def has_verified_address(conn: Connection, normalized: str) -> bool:
    """Whether an account holds `normalized` as its verified address (§18.4)."""
    return (
        conn.execute(
            select(t.notification_settings.c.human_id).where(
                t.notification_settings.c.address_normalized == normalized
            )
        ).first()
        is not None
    )


def decide_held(
    conn: Connection,
    *,
    human: Any,
    session: Any,
    change_id: Any,
    address: Any,
    approve: bool,
    signing_key: bytes | None,
    public_url: str,
    step_up: Callable[[], None],
    keeps_factor: Callable[[], None],
) -> None:
    """Approve or reject a held address change (§18.4); approving is a sensitive call, so
    `step_up` raises when the session owes the second factor (§2.8.4)."""
    row = row_of(conn, human.id, lock=True)
    pending = held(row)
    if not sessions.good_standing(session):
        raise _session_forbidden("not_in_good_standing")
    if pending is None or pending["id"] != change_id or pending["address"] != address:
        raise ApiError(409, "conflict", "no held change with that id and address")
    if not approve:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human.id)
            .values(address_change=None, updated_at=clock.now())
        )
        return
    if pending["address"] is None:
        _keeps_admin_address(conn, human.id)  # the account may have become the admin since
    step_up()
    if pending["address"] is None and row.address_status == "verified":
        keeps_factor()  # the policy may have come to `email` since it was held (§2.8.8)
    if clock.now() - session.created_at < APPROVER_AGE:
        raise _session_forbidden("session_too_new")
    apply_address(
        conn, row=row, human_id=human.id, wanted=pending["address"], signing_key=signing_key,
        public_url=public_url, session=session,
    )  # fmt: skip


def _keeps_admin_address(conn: Connection, human_id: str) -> None:
    """The instance admin's verified address is replaced, never removed: their password
    signs in by it (§2.1, §18.4)."""
    if admin.is_instance_admin(conn, human_id):
        raise ApiError(
            409,
            "admin_address_required",
            "the instance admin's address can be replaced, not removed",
        )


def _session_forbidden(reason: str) -> ApiError:
    return ApiError(403, "forbidden", "this session may not decide that", {"reason": reason})


def _tell_old_address(
    conn: Connection,
    human_id: str,
    old: str,
    new: str | None,
    session: Any,
    public_url: str,
) -> None:
    """The old address hears once that the address was changed or removed, whatever the
    security mode says, and the account records it (§18.4). `session` is where the change
    was asked from: the session itself for a removal, the browser, system and IP address
    kept with the pending address for a verified change; None leaves the line out."""
    masked = None
    if new is not None:
        local, _, domain = new.partition("@")
        masked = f"{local[:1]}…@{domain}"
    records.write(
        conn, human_id, "email_address_changed", {"masked": masked, "removed": new is None}
    )
    language = text_language(conn, human_id)
    words, unknown = catalog.section("mail", language), catalog.section("notify", language)
    where = ""
    if session is not None:
        where = "\n" + words["address_from"].format(
            browser=session.browser or unknown["a_browser"],
            os=session.os or unknown["unknown_os"],
            ip=session.ip or words["unknown_ip"],
        )
    body = words["address_changed_body" if masked else "address_removed_body"].format(
        url=public_url,
        masked=masked,
        time=clock.rfc3339(clock.now()),
        where=where,
        sessions=f"{public_url}/account/sessions",
    )
    outbox.enqueue(
        conn,
        kind="security",
        human_id=human_id,
        to=old,
        subject=f"[Maity] {words['address_subject']}",
        body=body,
    )


def _epoch_moved(conn: Connection, human_id: str) -> None:
    """The address was removed or changed: every open reset link dies with it (§2.10), and
    does not come back if the address returns."""
    from maity_hub.auth import password_resets

    password_resets.void_human(conn, human_id)


def void_pending_address(conn: Connection, human_id: str) -> None:
    """A new password, by `POST /auth/password` or a reset (§2.10): an unconfirmed new address
    and its verification link are voided. Whoever held the old password may have asked for it,
    and the password is the proof of the change. The verified address stays."""
    conn.execute(
        update(t.notification_settings)
        .where(
            t.notification_settings.c.human_id == human_id,
            t.notification_settings.c.pending_address.is_not(None),
        )
        .values(
            pending_address=None,
            pending_nonce=None,
            pending_expires_at=None,
            **NO_PENDING_ORIGIN,
            updated_at=clock.now(),
        )
    )
