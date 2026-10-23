"""The instance's sign-in methods (docs/api.md §2.6.6): device codes and sign-in links by
mail, each switched by the environment or the instance admin, the environment winning.
The password cannot be switched off."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from maity_hub import instance_settings as store
from maity_hub.config import Settings
from maity_hub.errors import invalid
from maity_hub.mail import settings as mail

FIELDS = ("device_code", "email_link")

store.register(
    *(
        store.Setting(f"sign_in.{name}", lambda v: v if isinstance(v, bool) else None, True)
        for name in FIELDS
    )
)


def _environment(hub: Settings, name: str) -> bool | None:
    return hub.sign_in_device_code if name == "device_code" else hub.sign_in_email_link


def resolve(conn: Connection, hub: Settings) -> dict[str, tuple[Any, str]]:
    stored = store.stored(conn, "sign_in")
    return {
        name: store.effective(f"sign_in.{name}", _environment(hub, name), stored) for name in FIELDS
    }


def view(conn: Connection, hub: Settings) -> dict[str, Any]:
    values = resolve(conn, hub)
    missing = []
    if not values["email_link"][0]:
        missing.append("switched_off")
    resolved = mail.resolve(conn, hub.mail, hub.secret_key)
    if not (resolved.complete and resolved.enabled):
        missing.append("mail")
    # The sign-in link itself (§2.6.3) is a card of its own; until it is built, the
    # login page has nothing to offer.
    missing.append("not_implemented")
    return {
        "password": {"value": True, "source": "fixed"},
        **{name: {"value": value, "source": source} for name, (value, source) in values.items()},
        "email_link_available": not missing,
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
        elif value is not None and not isinstance(value, bool):
            errors[name] = "invalid"
    if errors:
        raise invalid(errors)
    for name, value in body.items():
        store.put(conn, f"sign_in.{name}", value, by)
