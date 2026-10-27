"""A human's notification settings (docs/api.md §18.4).

The settings belong to the account and follow it to every device: what the browser
shows, and what is mailed how often (`mode`), with a daily time, quiet hours, a time zone
and the human's language. The stored value is only what the human changed; the defaults
fill the rest when it is read. The address and its verification sit in the same row but
are not set here yet (§18.4, the address part follows).
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.errors import invalid

KINDS = ("inbox", "chat", "mention", "security")
# Kinds removed on 2026-10-26 (§18.1): settings stored for them are dropped when read and
# deleted with the account's next PATCH; a PATCH naming one is `removed_kind`.
REMOVED_KINDS = ("card", "agent", "keep_the_why", "ticker", "jour_fixe", "system", "registration")
MODES = ("immediate", "hourly", "daily", "off")
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
                result[side]["content"].update({k: v for k, v in value.items() if k in KINDS})
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
    return conn.execute(query.with_for_update()).one()


_NONE = SimpleNamespace(
    preferences={},
    address=None,
    address_status="none",
    verified_at=None,
    pending_address=None,
    hard_failures=0,
    disabled_at=None,
)


def preferences(conn: Connection, human_id: str) -> dict[str, Any]:
    return _merged(row_of(conn, human_id).preferences)


def view(conn: Connection, human_id: str, mail_available: bool) -> dict[str, Any]:
    row = row_of(conn, human_id)
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
    return {
        "kinds": list(KINDS),
        "browser": merged["browser"],
        "email": email,
        "mail_available": mail_available,
    }


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
                    errors["browser.kinds"] = "invalid"
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
            out[key] = value  # checked and applied where the address is set
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
            errors["email.kinds"] = "invalid"
            return None
        mode = setting.get("mode")
        if mode is not None and mode not in (("immediate", "off") if kind == "security" else MODES):
            errors["email.kinds"] = "invalid"  # a delayed alert is no alert (§18.4)
            return None
        if "content" in setting and (
            kind not in CONTENT_KINDS or not isinstance(setting["content"], bool)
        ):
            errors["email.kinds"] = "invalid"
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


def patch(conn: Connection, *, human_id: str, body: dict[str, Any]) -> None:
    """Apply a `PATCH` of the preferences; an `address` is refused until it can be set."""
    errors: dict[str, str] = {}
    for key in body:
        if key == "kinds" or key in READ_ONLY:
            errors[key] = "read_only"
        elif key not in ("browser", "email"):
            errors[key] = "extra_forbidden"
    browser = _check_browser(body["browser"], errors) if "browser" in body else {}
    email = _check_email(body["email"], errors) if "email" in body else {}
    if "address" in email:
        errors["email.address"] = "not_available"  # the address part follows
    if errors:
        raise invalid(errors)
    row = row_of(conn, human_id, lock=True)
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
        .where(t.notification_settings.c.human_id == human_id)
        .values(preferences=stored, updated_at=clock.now())
    )


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
