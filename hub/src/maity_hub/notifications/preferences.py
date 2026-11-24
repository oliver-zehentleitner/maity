"""A human's notification settings (docs/api.md §18.4).

The settings belong to the account and follow it to every device: what the browser
shows, and what is mailed how often (`mode`), with a daily time, quiet hours, a time zone
and the human's language. The stored value is only what the human changed; the defaults
fill the rest when it is read. The address and its verification sit in the same row; a
`PATCH` that names the address hands it to `notifications.address`, which keeps the
address's lifecycle. The unsubscribe link of a mail (§18.6) switches one kind's `mode` off.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from sqlalchemy import Connection, select, update

from maity_hub import clock, languages
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.mail import address as addresses
from maity_hub.notifications import tokens
from maity_hub.notifications.address import change_address, held, row_of
from maity_hub.ratelimit import Attempt

KINDS = ("inbox", "chat", "mention", "security", "invitation")
MODES = ("immediate", "hourly", "daily", "weekly", "off")
DIGESTS = ("hourly", "daily", "weekly")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CONTENT_KINDS = ("chat", "mention")
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
        "kinds": dict.fromkeys(KINDS, True),
    },
    "email": {
        "language": "en",
        # The account's time zone, `null` until the human sets one (§18.4): the dashboard then
        # shows the browser's, and the mails use UTC (`mail_zone`).
        "timezone": None,
        "kinds": {
            "inbox": {"mode": "immediate"},
            # A digest by default against filled mailboxes; the inbox and security at once
            # (context/notifications.md da12f2b5). Only what the human set is stored, so a
            # kind nobody chose follows these as they are now.
            "chat": {"mode": "daily", "content": False},
            "mention": {"mode": "daily", "content": False},
            "security": {"mode": "immediate"},
            # An invitation by handle at once, like the inbox (tsk-8xsrzjv7f0yr, part 4);
            # `daily` mails it with the daily digest, `off` keeps it on the platform only.
            "invitation": {"mode": "immediate"},
        },
        "sign_in_link": True,
        # A forgotten password reset by mail to this address (§2.10); apart from
        # `sign_in_link`, because the reset is the stronger way in.
        "password_reset": True,
        # No mail of an immediate item while the human is present in the web app (§18.5).
        "hold_while_online": True,
        "daily_at": "08:00",
        "weekly_on": "mon",
        "quiet_hours": None,
    },
    # How the human hears of their agent instances that are not listening (§5.3, §18.4);
    # `minutes` is the personal default a project's own setting may override (§6.2).
    "not_listening": {"mode": "inbox", "minutes": 60},
}
NOT_LISTENING_MODES = ("inbox", "bell", "off")
NOT_LISTENING_MINUTES = (10, 1440)


def _merged(stored: dict[str, Any] | None) -> dict[str, Any]:
    """The stored preferences over the defaults, key by key."""
    result: dict[str, Any] = {
        "browser": {**DEFAULTS["browser"], "kinds": dict(DEFAULTS["browser"]["kinds"])},
        "email": {
            **DEFAULTS["email"],
            "kinds": {k: dict(v) for k, v in DEFAULTS["email"]["kinds"].items()},
        },
    }
    result["not_listening"] = {
        **DEFAULTS["not_listening"],
        **{
            k: v
            for k, v in ((stored or {}).get("not_listening") or {}).items()
            if k in DEFAULTS["not_listening"]
        },
    }
    for side in ("browser", "email"):
        given = (stored or {}).get(side) or {}
        for key, value in given.items():
            if key == "kinds" and isinstance(value, dict):
                for kind, setting in value.items():
                    if kind not in KINDS:
                        continue  # a key this hub does not know is not read, not an error
                    if side == "email" and isinstance(setting, dict):
                        result[side]["kinds"][kind].update(setting)
                    else:
                        result[side]["kinds"][kind] = setting
            elif side == "browser" and key not in DEFAULTS["browser"]:
                continue  # a key this hub does not know is not read, not an error
            else:
                result[side][key] = value
    return result


def preferences(conn: Connection, human_id: str) -> dict[str, Any]:
    return _merged(row_of(conn, human_id).preferences)


def set_language(conn: Connection, human_id: str, language: str) -> None:
    """What agents write in, chosen at registration (§2.7.1): no account has projects yet, so
    this tells nobody."""
    stored = dict(row_of(conn, human_id, lock=True).preferences or {})
    stored["email"] = {**(stored.get("email") or {}), "language": language}
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == human_id)
        .values(preferences=stored, updated_at=clock.now())
    )


def view(conn: Connection, human_id: str, mail_available: bool) -> dict[str, Any]:
    row = row_of(conn, human_id)
    pending = held(row)
    merged = _merged(row.preferences)
    email = {
        "address": row.address,
        "address_status": row.address_status,
        "verified_at": clock.rfc3339_or_none(row.verified_at),
        "pending_address": row.pending_address,
        **merged["email"],
        "hard_failures": row.hard_failures,
        "disabled_at": clock.rfc3339_or_none(row.disabled_at),
    }
    if pending is not None:
        email["address_change"] = pending
    return {
        "kinds": list(KINDS),
        "browser": merged["browser"],
        "email": email,
        "not_listening": merged["not_listening"],
        "mail_available": mail_available,
    }


# --- validation ----------------------------------------------------------------------


def _kind_error(name: str, kind: str, errors: dict[str, str]) -> None:
    errors[f"{name}.{kind}"] = "unknown"


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
        else:
            errors[f"browser.{key}"] = "invalid"
    return out


# The mail settings' on/off keys (§18.4).
SWITCHES = ("sign_in_link", "password_reset", "hold_while_online")


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
            if languages.known(value):
                out[key] = value
            else:
                errors[name] = "invalid"
        elif key == "timezone":
            if value is None or _zone(value):
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
        elif key == "weekly_on":
            if value in WEEKDAYS:
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
        elif key in SWITCHES and isinstance(value, bool):
            out[key] = value
        else:
            switch = key in SWITCHES
            errors[name] = "invalid" if switch else "extra_forbidden"
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
        if "mode" in setting and setting["mode"] not in MODES:
            errors[f"email.kinds.{kind}"] = "invalid"  # every kind takes every mode (§18.4)
            return None
        if "content" in setting and (
            kind not in CONTENT_KINDS or not isinstance(setting["content"], bool)
        ):
            errors[f"email.kinds.{kind}"] = "invalid"
            return None
    return value


def minutes_valid(value: Any) -> bool:
    """`not_listening.minutes`: a whole number of minutes in its range (§6.2, §18.4)."""
    low, high = NOT_LISTENING_MINUTES
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _check_not_listening(given: Any, errors: dict[str, str]) -> dict[str, Any]:
    if not isinstance(given, dict) or not set(given) <= {"mode", "minutes"}:
        errors["not_listening"] = "invalid"
        return {}
    if "mode" in given and given["mode"] not in NOT_LISTENING_MODES:
        errors["not_listening.mode"] = "invalid"
    if "minutes" in given and not minutes_valid(given["minutes"]):
        errors["not_listening.minutes"] = "invalid"
    return dict(given)


def mail_zone(email: dict[str, Any]) -> ZoneInfo:
    """The zone the mails use: the account's, or UTC while the human has set none (§18.4)."""
    return ZoneInfo(email.get("timezone") or "UTC")


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
    password_attempt: Callable[[], Attempt],
    step_up: Callable[[], None],
    keeps_factor: Callable[[], None],
) -> int:
    """Apply a `PATCH`; returns 200, or 202 when an address change is held for approval.
    `password_attempt` takes a `current_password` its place in the address change's own count
    of wrong passwords before it is compared (§2.1), and `step_up`
    raises when the caller's session owes the second factor the change of a verified
    address needs (§2.8.4)."""
    errors: dict[str, str] = {}
    for key in body:
        if key == "kinds" or key in READ_ONLY:
            errors[key] = "read_only"
        elif key not in ("browser", "email", "not_listening", "current_password"):
            errors[key] = "extra_forbidden"
    browser = _check_browser(body["browser"], errors) if "browser" in body else {}
    email = _check_email(body["email"], errors) if "email" in body else {}
    not_listening = (
        _check_not_listening(body["not_listening"], errors) if "not_listening" in body else {}
    )
    if errors:
        raise invalid(errors)
    row = row_of(conn, human.id, lock=True)
    status = 200
    if "address" in email:
        status = change_address(
            conn,
            row=row,
            human=human,
            session=session,
            wanted=email.pop("address"),
            given_password=body.get("current_password"),
            signing_key=signing_key,
            public_url=public_url,
            mail_ready=mail_ready,
            password_attempt=password_attempt,
            step_up=step_up,
            keeps_factor=keeps_factor,
        )
        row = row_of(conn, human.id, lock=True)
    stored = dict(row.preferences or {})
    for side, given in (("browser", browser), ("email", email)):
        if given:
            merged = dict(stored.get(side) or {})
            for key, value in given.items():
                if key == "kinds" and isinstance(value, dict):
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
    if not_listening:
        old_mode = _merged(stored)["not_listening"]["mode"]
        stored["not_listening"] = {**(stored.get("not_listening") or {}), **not_listening}
        new_mode = _merged(stored)["not_listening"]["mode"]
        if new_mode != old_mode:  # takes effect at the PATCH (§5.3)
            from maity_hub import not_listening_digest

            not_listening_digest.mode_changed(conn, human.id, old_mode, new_mode)
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == human.id)
        .values(preferences=stored, updated_at=clock.now())
    )
    if email.get("sign_in_link") is False:
        from maity_hub.auth import email_links

        email_links.void_human(conn, human.id)
    if email.get("password_reset") is False:
        # Turning it off voids an open reset link (§2.10).
        from maity_hub.auth import password_resets

        password_resets.void_human(conn, human.id)
    return status


# --- the unsubscribe link (§18.6) ----------------------------------------------------


def unsubscribe(conn: Connection, token: str, signing_key: bytes | None) -> str | None:
    """Switch the token's kind off; the kind, or None for a link that does not work: a
    token this hub did not sign, one for another purpose, for a kind that does not exist,
    or from before the address changed (the `epoch` moved)."""
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
    stored = dict(row.preferences or {})
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
