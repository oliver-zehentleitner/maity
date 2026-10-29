"""The instance's sign-in methods (docs/api.md §2.6.6): device codes and sign-in links by
mail, each switched by the environment or the instance admin, the environment winning,
and the second factor's policy (§2.8.5). The password cannot be switched off."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from maity_hub import instance_settings as store
from maity_hub.auth import device_codes, email_links
from maity_hub.config import SECOND_FACTOR_POLICIES, Settings
from maity_hub.errors import invalid
from maity_hub.mail import settings as mail

SWITCHES = ("device_code", "email_link")
SEEN = "sign_in.second_factor_seen"
FIELDS = (*SWITCHES, "second_factor")

store.register(
    *(
        store.Setting(f"sign_in.{name}", lambda v: v if isinstance(v, bool) else None, True)
        for name in SWITCHES
    ),
    store.Setting(
        "sign_in.second_factor",
        lambda v: v if v in SECOND_FACTOR_POLICIES else None,
        "optional",
    ),
    # `off` once the hub has told the switch to it, so it is told once, whether the
    # admin made it or the environment did (§2.8.5); no row otherwise.
    store.Setting(SEEN, lambda v: v if v in SECOND_FACTOR_POLICIES else None, None),
)


def _environment(hub: Settings, name: str) -> bool | str | None:
    return {
        "device_code": hub.sign_in_device_code,
        "email_link": hub.sign_in_email_link,
        "second_factor": hub.sign_in_second_factor,
    }[name]


def resolve(conn: Connection, hub: Settings) -> dict[str, tuple[Any, str]]:
    stored = store.stored(conn, "sign_in")
    return {
        name: store.effective(f"sign_in.{name}", _environment(hub, name), stored) for name in FIELDS
    }


def view(conn: Connection, hub: Settings) -> dict[str, Any]:
    values = resolve(conn, hub)
    link_missing = []
    if not values["email_link"][0]:
        link_missing.append("switched_off")
    resolved = mail.resolve(conn, hub.mail, hub.secret_key)
    if not (resolved.complete and resolved.enabled):
        link_missing.append("mail")
    if not hub.mail.signing_key:
        link_missing.append("signing_key")
    # The second factor seals its secrets with the instance key (§2.8.1).
    missing = [*link_missing, *([] if hub.secret_key else ["secret_key"])]
    return {
        "password": {"value": True, "source": "fixed"},
        **{name: {"value": value, "source": source} for name, (value, source) in values.items()},
        "email_link_available": not link_missing,
        "missing": missing,
    }


def patch(conn: Connection, hub: Settings, body: dict[str, Any], by: str) -> None:
    """All of the body or nothing; `invalid` names each refused field."""
    errors: dict[str, str] = {}
    for name, value in body.items():
        if name == "password":
            errors[name] = "fixed"
        elif name not in FIELDS:
            errors[name] = "extra_forbidden"
        elif _environment(hub, name) is not None:
            errors[name] = "set_by_environment"
        elif name == "second_factor":
            if value is not None and value not in SECOND_FACTOR_POLICIES:
                errors[name] = "invalid"
            elif value == "required_admins" and hub.secret_key is None:
                errors[name] = "secret_key_missing"
        elif value is not None and not isinstance(value, bool):
            errors[name] = "invalid"
    if errors:
        raise invalid(errors)
    for name, value in body.items():
        store.put(conn, f"sign_in.{name}", value, by)
    if not resolve(conn, hub)["device_code"][0]:
        # A method switched off voids its open codes at once (§2.6.5).
        device_codes.void_open(conn)
    if not resolve(conn, hub)["email_link"][0]:
        email_links.void_open(conn)
    note_second_factor(conn, hub, by)


def note_second_factor(conn: Connection, hub: Settings, by: str) -> None:
    """Tell every enrolled human once when the policy has become `off` since the hub
    last looked: after an admin's `PATCH` (`by` the admin) and at startup (`by`
    `environment` when the environment set it)."""
    current = second_factor_policy(conn, hub)
    seen = store.stored(conn, "sign_in").get(SEEN)
    if current == "off" and seen != "off":
        from maity_hub.auth import second_factor  # it imports this module

        second_factor.told_instance_off(conn, by)
    # Only `off` is remembered, so an instance that never switched it off keeps no row.
    if current == "off" and seen != "off":
        store.put(conn, SEEN, "off", None)
    elif current != "off" and seen == "off":
        store.put(conn, SEEN, None, None)


def device_code_enabled(conn: Connection, hub: Settings) -> bool:
    return bool(resolve(conn, hub)["device_code"][0])


def second_factor_policy(conn: Connection, hub: Settings) -> str:
    return str(resolve(conn, hub)["second_factor"][0])


def email_link_enabled(conn: Connection, hub: Settings) -> bool:
    return bool(resolve(conn, hub)["email_link"][0])
