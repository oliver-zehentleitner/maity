"""Instance settings the instance admin sets (docs/api.md §2.6.6, §16.2), and the sealed
secrets beside them.

`instance_setting` holds one row per name an admin set; no row means the environment's
value or the default. Every name comes from the registry here, filled by the section
that owns it (`mail.*`, `sign_in.*`) when its module is imported: a write of a name
without an entry is a programming error. A rename of a name is a migration of its row, and
every read names the fields it wants, so no row is served by accident. Whether the
environment wins is decided in `effective`, nowhere else.

No secret is ever a setting. A secret an admin may set (today the SMTP password, §16.2)
has an entry in `SECRETS` and lives sealed in `instance_secret`, so nothing that reads
settings can serve one.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, delete, insert, select

from maity_hub import clock
from maity_hub import tables as t

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Setting:
    name: str
    # The value to store, or None when the value does not validate.
    check: Callable[[object], object | None]
    default: object = None


SETTINGS: dict[str, Setting] = {}
SECRETS: set[str] = set()


def register(*settings: Setting) -> None:
    for setting in settings:
        if setting.name in SETTINGS or setting.name in SECRETS:
            raise ValueError(f"instance setting {setting.name} is registered twice")
        SETTINGS[setting.name] = setting


def register_secret(name: str) -> None:
    if name in SETTINGS or name in SECRETS:
        raise ValueError(f"instance secret {name} is registered twice")
    SECRETS.add(name)


def stored(conn: Connection, section: str) -> dict[str, Any]:
    """The admin-set values of one section (`mail`, `sign_in`), by name."""
    prefix = f"{section}."
    found: dict[str, Any] = {}
    for row in conn.execute(select(t.instance_setting)).all():
        if not row.name.startswith(prefix):
            continue
        found[row.name] = row.value
    return found


def effective(name: str, env_value: object, stored_values: dict[str, Any]) -> tuple[Any, str]:
    """(value, source): the environment's value wins, then the admin's, then the
    default (§16.2)."""
    if env_value is not None:
        return env_value, "env"
    if name in stored_values:
        return stored_values[name], "admin"
    return SETTINGS[name].default, "default"


def put(conn: Connection, name: str, value: object, by: str | None) -> None:
    """Store an admin's value, checked against the registry; None removes it."""
    setting = SETTINGS[name]
    conn.execute(delete(t.instance_setting).where(t.instance_setting.c.name == name))
    if value is None:
        return
    checked = setting.check(value)
    if checked is None:
        raise ValueError(f"instance setting {name} does not validate")
    conn.execute(
        insert(t.instance_setting).values(
            name=name, value=checked, updated_at=clock.now(), updated_by=by
        )
    )


def sealed(conn: Connection, name: str) -> bytes | None:
    """A stored secret as `secretbox` sealed it, or None."""
    if name not in SECRETS:
        raise KeyError(name)
    text = conn.execute(
        select(t.instance_secret.c.sealed).where(t.instance_secret.c.name == name)
    ).scalar()
    if text is None:
        return None
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        log.warning("instance secret %s is not base64; treated as not set", name)
        return None


def put_sealed(conn: Connection, name: str, value: bytes | None, by: str | None) -> None:
    """Store a sealed secret; None removes it."""
    if name not in SECRETS:
        raise KeyError(name)
    conn.execute(delete(t.instance_secret).where(t.instance_secret.c.name == name))
    if value is not None:
        conn.execute(
            insert(t.instance_secret).values(
                name=name,
                sealed=base64.b64encode(value).decode(),
                updated_at=clock.now(),
                updated_by=by,
            )
        )


def add_sealed(conn: Connection, name: str, value: bytes) -> None:
    """Store a secret only if none is stored; a concurrent first one raises
    `IntegrityError` and wins (the caller re-reads in a fresh transaction)."""
    if name not in SECRETS:
        raise KeyError(name)
    conn.execute(
        insert(t.instance_secret).values(
            name=name,
            sealed=base64.b64encode(value).decode(),
            updated_at=clock.now(),
            updated_by=None,
        )
    )
