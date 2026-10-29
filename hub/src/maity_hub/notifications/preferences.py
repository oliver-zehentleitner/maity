"""A human's notification settings (docs/api.md §18.4).

The settings belong to the account and follow it to every device: what the browser
shows, and what is mailed how often (`mode`), with a daily time, quiet hours, a time zone
and the human's language. The stored value is only what the human changed; the defaults
fill the rest when it is read. The address and its verification sit in the same row but
are set here (§18.4): setting an address puts it in `pending_address` and mails a link
valid for 24 hours; the verified address keeps receiving until the new one is verified.
Once a verified address exists, changing or removing it needs the human's own
confirmation: the password, or for a human without one an approval from a session in
good standing at least 24 hours old. The unsubscribe link of a mail (§18.6) switches
one kind's `mode` off.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import passwords, sessions
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.mail import address as addresses
from maity_hub.mail import outbox
from maity_hub.notifications import records, tokens

KINDS = ("inbox", "chat", "mention", "security")
# Kinds removed on 2026-10-26 (§18.1): settings stored for them are dropped when read and
# deleted with the account's next PATCH; a PATCH naming one is `removed_kind`.
REMOVED_KINDS = ("card", "agent", "keep_the_why", "ticker", "jour_fixe", "system", "registration")
MODES = ("immediate", "hourly", "daily", "off")
CONTENT_KINDS = ("chat", "mention")
VERIFY_FOR = timedelta(hours=24)
APPROVER_AGE = timedelta(hours=24)
HELD_FOR = timedelta(days=7)
READ_ONLY = (
    "address_status",
    "verified_at",
    "pending_address",
    "hard_failures",
    "disabled_at",
    "mail_available",
    "address_change",
)
_HHMM = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")

DEFAULTS: dict[str, Any] = {
    "browser": {
        "enabled": False,
        "kinds": {"inbox": True, "chat": True, "mention": True, "security": True},
        "content": {"chat": False, "mention": False},
    },
    "email": {
        "language": "en",
        "timezone": "UTC",
        "kinds": {
            "inbox": {"mode": "immediate"},
            "chat": {"mode": "hourly", "content": False},
            "mention": {"mode": "immediate", "content": False},
            "security": {"mode": "immediate"},
        },
        "sign_in_link": True,
        "daily_at": "08:00",
        "quiet_hours": None,
    },
}


def _merged(stored: dict[str, Any] | None) -> dict[str, Any]:
    """The stored preferences over the defaults, key by key, without the removed kinds."""
    result: dict[str, Any] = {
        "browser": {**DEFAULTS["browser"], "kinds": dict(DEFAULTS["browser"]["kinds"])},
        "email": {
            **DEFAULTS["email"],
            "kinds": {k: dict(v) for k, v in DEFAULTS["email"]["kinds"].items()},
        },
    }
    result["browser"]["content"] = dict(DEFAULTS["browser"]["content"])
    for side in ("browser", "email"):
        given = (stored or {}).get(side) or {}
        for key, value in given.items():
            if key == "kinds" and isinstance(value, dict):
                for kind, setting in value.items():
                    if kind not in KINDS:
                        continue
                    if side == "email" and isinstance(setting, dict):
                        result[side]["kinds"][kind].update(setting)
                    else:
                        result[side]["kinds"][kind] = setting
            elif key == "content" and isinstance(value, dict):
                result[side]["content"].update(
                    {k: v for k, v in value.items() if k in CONTENT_KINDS}
                )
            else:
                result[side][key] = value
    return result


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


def preferences(conn: Connection, human_id: str) -> dict[str, Any]:
    return _merged(row_of(conn, human_id).preferences)


def view(conn: Connection, human_id: str, mail_available: bool) -> dict[str, Any]:
    row = row_of(conn, human_id)
    held = _held(row)
    merged = _merged(row.preferences)
    email = {
        "address": row.address,
        "address_status": row.address_status,
        "verified_at": clock.rfc3339(row.verified_at) if row.verified_at else None,
        "pending_address": row.pending_address,
        **merged["email"],
        "hard_failures": row.hard_failures,
        "disabled_at": clock.rfc3339(row.disabled_at) if row.disabled_at else None,
    }
    if held is not None:
        email["address_change"] = held
    return {
        "kinds": list(KINDS),
        "browser": merged["browser"],
        "email": email,
        "mail_available": mail_available,
    }


def _held(row: Any) -> dict[str, Any] | None:
    change = row.address_change
    if not change:
        return None
    requested = datetime.fromisoformat(change["requested_at"].replace("Z", "+00:00"))
    if clock.now() - requested >= HELD_FOR:
        return None  # a held change lapses after 7 days
    return dict(change)


# --- validation ----------------------------------------------------------------------


def _kind_error(name: str, kind: str, errors: dict[str, str]) -> None:
    errors[f"{name}.{kind}"] = "removed_kind" if kind in REMOVED_KINDS else "unknown"


def _check_browser(given: Any, errors: dict[str, str]) -> dict[str, Any]:
    if not isinstance(given, dict):
        errors["browser"] = "invalid"
        return {}
    out: dict[str, Any] = {}
    for key, value in given.items():
        if key == "enabled" and isinstance(value, bool):
            out[key] = value
        elif key == "kinds" and isinstance(value, dict):
            for kind in value:
                if kind not in KINDS:
                    _kind_error("browser.kinds", kind, errors)
            if set(value) <= set(KINDS):
                if all(isinstance(v, bool) for v in value.values()):
                    out[key] = value
                else:
                    for kind, setting in value.items():
                        if not isinstance(setting, bool):
                            errors[f"browser.kinds.{kind}"] = "invalid"
        elif key == "content" and isinstance(value, dict) and set(value) <= set(CONTENT_KINDS):
            if all(isinstance(v, bool) for v in value.values()):
                out[key] = value
            else:
                errors["browser.content"] = "invalid"
        else:
            errors[f"browser.{key}"] = "invalid"
    return out


def _check_email(given: Any, errors: dict[str, str]) -> dict[str, Any]:
    if not isinstance(given, dict):
        errors["email"] = "invalid"
        return {}
    out: dict[str, Any] = {}
    for key, value in given.items():
        name = f"email.{key}"
        if key in READ_ONLY:
            errors[name] = "read_only"
        elif key == "address":
            if value is not None and not addresses.valid(value):
                errors[name] = "invalid"
            else:
                out[key] = value
        elif key == "language":
            if value in ("en", "de"):
                out[key] = value
            else:
                errors[name] = "invalid"
        elif key == "timezone":
            if _zone(value):
                out[key] = value
            else:
                errors[name] = "invalid"
        elif key == "kinds":
            kinds = _check_modes(value, errors)
            if kinds is not None:
                out[key] = kinds
        elif key == "daily_at":
            if isinstance(value, str) and _HHMM.fullmatch(value):
                out[key] = value
            else:
                errors[name] = "invalid"
        elif key == "quiet_hours":
            ok = value is None or (
                isinstance(value, dict)
                and set(value) == {"from", "to"}
                and all(isinstance(v, str) and _HHMM.fullmatch(v) for v in value.values())
            )
            if ok:
                out[key] = value
            else:
                errors[name] = "invalid"
        elif key == "sign_in_link" and isinstance(value, bool):
            out[key] = value
        else:
            errors[name] = "invalid" if key == "sign_in_link" else "extra_forbidden"
    return out


def _check_modes(value: Any, errors: dict[str, str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors["email.kinds"] = "invalid"
        return None
    unknown = [kind for kind in value if kind not in KINDS]
    for kind in unknown:
        _kind_error("email.kinds", kind, errors)
    if unknown:
        return None
    for kind, setting in value.items():
        if not isinstance(setting, dict) or not set(setting) <= {"mode", "content"}:
            errors[f"email.kinds.{kind}"] = "invalid"
            return None
        # A missing `mode` is a partial change; one that is present must be a mode, `null`
        # included (§18.4).
        if "mode" in setting and setting["mode"] not in (
            ("immediate", "off") if kind == "security" else MODES
        ):
            errors[f"email.kinds.{kind}"] = "invalid"  # a delayed alert is no alert (§18.4)
            return None
        if "content" in setting and (
            kind not in CONTENT_KINDS or not isinstance(setting["content"], bool)
        ):
            errors[f"email.kinds.{kind}"] = "invalid"
            return None
    return value


def _zone(value: Any) -> bool:
    if not isinstance(value, str) or (value != "UTC" and value not in available_timezones()):
        return False
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


# --- PATCH ---------------------------------------------------------------------------


def patch(
    conn: Connection,
    *,
    human: Any,
    session: Any,
    body: dict[str, Any],
    signing_key: bytes | None,
    public_url: str,
    mail_ready: bool,
    wrong_password: Any,
    password_blocked: Any,
    step_up: Callable[[], None],
) -> int:
    """Apply a `PATCH`; returns 200, or 202 when an address change is held for approval.
    `wrong_password` counts a mismatched `current_password` against the login limits,
    `password_blocked` gives the seconds to wait while they are exhausted, and `step_up`
    raises when the caller's session owes the second factor the change of a verified
    address needs (§2.8.4)."""
    errors: dict[str, str] = {}
    for key in body:
        if key == "kinds" or key in READ_ONLY:
            errors[key] = "read_only"
        elif key not in ("browser", "email", "current_password"):
            errors[key] = "extra_forbidden"
    browser = _check_browser(body["browser"], errors) if "browser" in body else {}
    email = _check_email(body["email"], errors) if "email" in body else {}
    if errors:
        raise invalid(errors)
    row = row_of(conn, human.id, lock=True)
    status = 200
    if "address" in email:
        status = _change_address(
            conn,
            row=row,
            human=human,
            session=session,
            wanted=email.pop("address"),
            given_password=body.get("current_password"),
            signing_key=signing_key,
            public_url=public_url,
            mail_ready=mail_ready,
            wrong_password=wrong_password,
            password_blocked=password_blocked,
            step_up=step_up,
        )
        row = row_of(conn, human.id, lock=True)
    # What was stored for a removed kind goes with this write (§18.4).
    stored = _without_removed(dict(row.preferences or {}))
    for side, given in (("browser", browser), ("email", email)):
        if given:
            merged = dict(stored.get(side) or {})
            for key, value in given.items():
                if key in ("kinds", "content") and isinstance(value, dict):
                    inner = dict(merged.get(key) or {})
                    for kind, setting in value.items():
                        if isinstance(setting, dict):
                            inner[kind] = {**(inner.get(kind) or {}), **setting}
                        else:
                            inner[kind] = setting
                    merged[key] = inner
                else:
                    merged[key] = value
            stored[side] = merged
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == human.id)
        .values(preferences=stored, updated_at=clock.now())
    )
    if email.get("sign_in_link") is False:
        from maity_hub.auth import email_links

        email_links.void_human(conn, human.id)
    return status


def _without_removed(stored: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for side, given in stored.items():
        if not isinstance(given, dict):
            out[side] = given
            continue
        kept = dict(given)
        for key in ("kinds", "content"):
            if isinstance(kept.get(key), dict):
                kept[key] = {k: v for k, v in kept[key].items() if k in KINDS}
        out[side] = kept
    return out


# --- the unsubscribe link (§18.6) ----------------------------------------------------


def unsubscribe(conn: Connection, token: str, signing_key: bytes | None) -> str | None:
    """Switch the token's kind off; the kind, or None for a link that does not work: a
    token this hub did not sign, one for another purpose, for a kind removed on
    2026-10-26, or from before the address changed (the `epoch` moved)."""
    payload = tokens.read(signing_key, token)
    if payload is None or payload.get("p") != "unsubscribe" or payload.get("k") not in KINDS:
        return None
    owner = str(payload.get("h"))
    row = conn.execute(
        select(t.notification_settings)
        .where(t.notification_settings.c.human_id == owner)
        .with_for_update()
    ).first()
    if row is None or payload.get("e") != row.epoch:
        return None
    kind = str(payload["k"])
    stored = _without_removed(dict(row.preferences or {}))
    email = dict(stored.get("email") or {})
    kinds = dict(email.get("kinds") or {})
    kinds[kind] = {**(kinds.get(kind) or {}), "mode": "off"}
    email["kinds"] = kinds
    stored["email"] = email
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == owner)
        .values(preferences=stored, updated_at=clock.now())
    )
    return kind


def unsubscribe_token(signing_key: bytes, human_id: str, kind: str, epoch: int) -> str:
    """The token in a mail's unsubscribe link. The hub stores none: it stays valid until
    the human's `epoch` moves, which an address change or removal does."""
    return tokens.make(signing_key, {"h": human_id, "p": "unsubscribe", "k": kind, "e": epoch})


# --- the address (§18.4) -------------------------------------------------------------


def _change_address(
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
    wrong_password: Any,
    password_blocked: Any,
    step_up: Callable[[], None],
) -> int:
    if wanted is not None and not mail_ready:
        raise ApiError(409, "mail_not_configured", "the instance cannot send mail")
    verified = row.address_status in ("verified", "disabled") and row.address is not None
    moves = verified and wanted != row.address
    if moves:
        step_up()  # changing or removing the verified address is a sensitive call (§2.8.4)
        if human.password_hash is not None:
            if not isinstance(given_password, str) or not given_password:
                raise invalid({"current_password": "required"})
            # The login limits hold here as at the login: no guessing past them (§2.1).
            wait = password_blocked()
            if wait:
                raise rate_limited(wait)
            if not passwords.verify_password(given_password, human.password_hash):
                wrong_password()
                raise invalid({"current_password": "mismatch"})
        else:
            held = _held(row)
            confirmed = sessions.confirmed_sessions(conn, human.id)
            standing = sessions.good_standing(session, confirmed)
            if not standing and held is not None:
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
    withdraws a pending deletion request (§2.9): its link went to that address."""
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
                epoch=row.epoch + 1,
                address_change=None,
                updated_at=now,
            )
        )
        if row.address is not None and row.address_status in ("verified", "disabled"):
            _tell_old_address(conn, human_id, row.address, None, session, public_url)
        return
    nonce = secrets.token_hex(8)
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == human_id)
        .values(
            pending_address=wanted,
            pending_nonce=nonce,
            pending_expires_at=now + VERIFY_FOR,
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
    # Never the handle, the name or projects: nobody confirmed this address yet (§18.4).
    outbox.enqueue(
        conn,
        kind="security",
        human_id=human_id,
        to=wanted,
        extra_headers={"_purpose": "verify"},
        subject="[Maity] Confirm your address",
        body=(
            f"Someone asked to send Maity mail from {public_url} to {wanted}.\n\n"
            f"Confirm the address: {link}\n\n"
            "The link is valid for 24 hours. If you did not ask for this, ignore this mail.\n"
        ),
    )


def verify(
    conn: Connection,
    token: str,
    signing_key: bytes | None,
    public_url: str,
    *,
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
    addresses.lock(conn, claimed)
    taken = conn.execute(
        select(t.notification_settings.c.human_id).where(
            t.notification_settings.c.address_normalized == claimed,
            t.notification_settings.c.human_id != owner,
        )
    ).first()
    if taken is not None:
        return False
    previous = row.address if row.address_status in ("verified", "disabled") else None
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == owner)
        .values(
            address_normalized=claimed,
            address=row.pending_address,
            address_status="verified",
            verified_at=now,
            pending_address=None,
            pending_nonce=None,
            pending_expires_at=None,
            hard_failures=0,
            disabled_at=None,
            epoch=row.epoch + (1 if previous and previous != row.pending_address else 0),
            updated_at=now,
        )
    )
    if previous is not None and previous != row.pending_address:
        from maity_hub import account_deletion

        account_deletion.withdraw(conn, owner, "address")  # §2.9
        _tell_old_address(conn, owner, previous, row.pending_address, None, public_url)
    return True


def claim_verified(conn: Connection, normalized: str, human_id: str) -> bool:
    """Write `normalized` as the human's verified address, as a registration's completion
    does (§2.7.1, §18.4), under the per-address lock: False when another account holds
    it. The human has no settings yet; the defaults apply."""
    addresses.lock(conn, normalized)
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
) -> None:
    """Approve or reject a held address change (§18.4); approving is a sensitive call, so
    `step_up` raises when the session owes the second factor (§2.8.4)."""
    row = row_of(conn, human.id, lock=True)
    held = _held(row)
    confirmed = sessions.confirmed_sessions(conn, human.id)
    if not sessions.good_standing(session, confirmed):
        raise _session_forbidden("not_in_good_standing")
    if held is None or held["id"] != change_id or held["address"] != address:
        raise ApiError(409, "conflict", "no held change with that id and address")
    if not approve:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == human.id)
            .values(address_change=None, updated_at=clock.now())
        )
        return
    step_up()
    if clock.now() - session.created_at < APPROVER_AGE:
        raise _session_forbidden("session_too_new")
    apply_address(
        conn, row=row, human_id=human.id, wanted=held["address"], signing_key=signing_key,
        public_url=public_url, session=session,
    )  # fmt: skip


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
    security mode says, and the account records it (§18.4)."""
    masked = None
    if new is not None:
        local, _, domain = new.partition("@")
        masked = f"{local[:1]}…@{domain}"
    records.write(
        conn, human_id, "email_address_changed", {"masked": masked, "removed": new is None}
    )
    where = ""
    if session is not None:
        browser = session.browser or "a browser"
        system = session.os or "an unknown system"
        where = f"\nFrom: {browser} on {system}, {session.ip or 'an unknown address'}"
    change = f"was changed to {masked}" if masked else "was removed"
    outbox.enqueue(
        conn,
        kind="security",
        human_id=human_id,
        to=old,
        subject="[Maity] Your sign-in address was changed",
        body=(
            f"The Maity address of your account at {public_url} {change} "
            f"on {clock.rfc3339(clock.now())}.{where}\n\n"
            "If this was not you, sign in and check your sessions: "
            f"{public_url}/#/account/sessions\n"
        ),
    )
