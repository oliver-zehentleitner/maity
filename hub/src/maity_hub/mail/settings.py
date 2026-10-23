"""The instance's mail settings (docs/api.md §16.2): each value from the environment, else
as the instance admin set it, else the default; and the admin's view of them.

The password is write-only whichever its source: the view says whether one is set and
where it came from, never a value, a length, a hash or a hint. A stored password the
current instance key cannot decrypt counts as not set.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, delete, func, insert, select

from maity_hub import clock, secretbox
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.mail import address, headers
from maity_hub.mail.environment import (
    DEFAULT_PORTS,
    MAX_PASSWORD,
    MAX_PER_HOUR,
    MAX_USERNAME,
    TLS_MODES,
    MailEnvironment,
    Sender,
    is_loopback,
    valid_host,
)

# The fields of the answer that carry `{value, source}`, in the contract's order.
VALUE_FIELDS = (
    "host",
    "port",
    "tls",
    "username",
    "from",
    "reply_to",
    "max_per_hour",
    "security_max_per_hour",
    "sign_in_max_per_hour",
)
DEFAULTS: dict[str, object] = {
    "enabled": True,
    "host": None,
    "port": None,  # follows `tls` (DEFAULT_PORTS)
    "tls": "starttls",
    "username": None,
    "from": None,
    "reply_to": None,
    "max_per_hour": 500,
    "security_max_per_hour": 100,
    "sign_in_max_per_hour": 60,
}
WRITABLE = (*DEFAULTS, "password")
ENVIRONMENT_ONLY = ("signing_key", "secret_key")
# A change of one of these makes the last test say nothing about the settings (§16.2).
CONNECTION_FIELDS = ("host", "port", "tls", "username", "password", "from")
LAST_TEST = "last_test"
# The associated data of the sealed SMTP password (`maity_hub.secretbox`).
PASSWORD_FIELD = "mail.smtp_password"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resolved:
    """The settings in effect. `password` is the plaintext, for the SMTP conversation
    only; it is never in a view, a repr or a log line."""

    env: MailEnvironment
    secret_key_set: bool
    values: dict[str, tuple[Any, str]]
    password: str | None = field(repr=False)
    password_source: str | None
    last_test: dict[str, Any] | None

    def value(self, name: str) -> Any:
        return self.values[name][0]

    @property
    def enabled(self) -> bool:
        return bool(self.value("enabled"))

    @property
    def sender(self) -> Sender | None:
        found = self.value("from")
        return Sender(found["address"], found.get("name")) if found else None

    @property
    def missing(self) -> list[str]:
        missing = []
        if not self.value("host"):
            missing.append("host")
        if self.value("username") and self.password is None:
            missing.append("password")
        if not self.value("from"):
            missing.append("from")
        if self.env.signing_key is None:
            missing.append("signing_key")
        return missing

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def warnings(self) -> list[str]:
        found = []
        if self.env.in_kubernetes and self.password_source == "admin":
            found.append("smtp_password_in_database")
        if self.env.allow_plaintext:
            found.append("smtp_plaintext_allowed")
        return found


def resolve(conn: Connection, env: MailEnvironment, secret_key: bytes | None) -> Resolved:
    stored = {row.field: row.value for row in conn.execute(select(t.mail_setting)).all()}
    values: dict[str, tuple[Any, str]] = {}
    for name, default in DEFAULTS.items():
        from_env = env.value(name) if name != "enabled" else None
        if from_env is not None:
            values[name] = (from_env.view() if isinstance(from_env, Sender) else from_env, "env")
        elif name in stored:
            values[name] = (stored[name], "admin")
        else:
            values[name] = (default, "default")
    if values["port"][0] is None:
        values["port"] = (DEFAULT_PORTS[values["tls"][0]], "default")
    password: str | None
    source: str | None
    if env.password is not None:
        password, source = env.password, "env"
    else:
        password = _unseal(secret_key, stored.get("password"))
        source = "admin" if password is not None else None
    return Resolved(env, secret_key is not None, values, password, source, stored.get(LAST_TEST))


def view(conn: Connection, resolved: Resolved) -> dict[str, Any]:
    """The answer of `GET` and `PATCH /admin/settings/mail`."""
    answer: dict[str, Any] = {
        "enabled": resolved.enabled,
        "complete": resolved.complete,
        "missing": resolved.missing,
    }
    for name in VALUE_FIELDS:
        value, source = resolved.values[name]
        answer[name] = {"value": value, "source": source}
        if name == "username":
            answer["password"] = {
                "set": resolved.password is not None,
                "source": resolved.password_source,
            }
    answer["signing_key"] = {"set": resolved.env.signing_key is not None}
    answer["secret_key"] = {"set": resolved.secret_key_set}
    answer["warnings"] = resolved.warnings
    answer["last_test"] = resolved.last_test
    answer.update(counters(conn))
    return answer


def counters(conn: Connection) -> dict[str, int]:
    """The mail of the last hour by budget kind and outcome (§16.2). `security_queued`
    is what waits now, however old."""
    since = clock.now() - timedelta(hours=1)
    rows = conn.execute(
        select(t.mail_delivery.c.kind, t.mail_delivery.c.outcome, func.count())
        .where(t.mail_delivery.c.at >= since)
        .group_by(t.mail_delivery.c.kind, t.mail_delivery.c.outcome)
    ).all()
    recent = {(kind, outcome): int(count) for kind, outcome, count in rows}
    queued = conn.execute(
        select(func.count())
        .select_from(t.mail_delivery)
        .where(t.mail_delivery.c.kind == "security", t.mail_delivery.c.outcome == "queued")
    ).scalar_one()
    return {
        "sent_last_hour": recent.get(("notification", "sent"), 0),
        "security_sent_last_hour": recent.get(("security", "sent"), 0),
        "security_queued": int(queued),
        "sign_in_sent_last_hour": recent.get(("sign_in", "sent"), 0),
        "sign_in_dropped_last_hour": recent.get(("sign_in", "dropped"), 0),
        "failed_last_hour": sum(n for (_, outcome), n in recent.items() if outcome == "failed"),
    }


def patch(conn: Connection, env: MailEnvironment, secret_key: bytes | None, body: object) -> None:
    """Apply a `PATCH` body, all of it or nothing; `invalid` names each refused field.
    A value is never echoed in an error."""
    if not isinstance(body, dict):
        raise invalid({"body": "not_an_object"})
    errors: dict[str, str] = {}
    changes: dict[str, object] = {}
    for name, value in body.items():
        if name in ENVIRONMENT_ONLY:
            errors[name] = "environment_only"
        elif name not in WRITABLE:
            errors[name] = "extra_forbidden"
        elif name != "enabled" and env.value(name) is not None:
            errors[name] = "set_by_environment"
        elif value is None:
            changes[name] = None
        elif name == "password":
            if secret_key is None:
                errors[name] = "secret_key_missing"
            elif not headers.printable(value, MAX_PASSWORD):
                errors[name] = "invalid"
            else:
                changes[name] = value
        else:
            checked = _check(name, value)
            if checked is None:
                errors[name] = "invalid"
            else:
                changes[name] = checked
    if errors:
        raise invalid(errors)
    before = resolve(conn, env, secret_key)
    host = changes["host"] if "host" in changes else before.value("host")
    tls = changes["tls"] if "tls" in changes else before.value("tls")
    if (tls or DEFAULTS["tls"]) == "none" and host is not None and not is_loopback(str(host)):
        raise invalid({"tls" if "tls" in changes else "host": "loopback_host_only"})
    now = clock.now()
    for name, value in changes.items():
        conn.execute(delete(t.mail_setting).where(t.mail_setting.c.field == name))
        if value is None:
            continue
        if name == "password":
            assert secret_key is not None  # checked above: secret_key_missing
            value = _seal(secret_key, str(value))
        conn.execute(insert(t.mail_setting).values(field=name, value=value, updated_at=now))
    after = resolve(conn, env, secret_key)
    changed = any(
        (
            (before.password != after.password)
            if name == "password"
            else before.value(name) != after.value(name)
        )
        for name in CONNECTION_FIELDS
        if name in changes
    )
    if changed:
        conn.execute(delete(t.mail_setting).where(t.mail_setting.c.field == LAST_TEST))


def record_test(conn: Connection, outcome: dict[str, Any]) -> None:
    conn.execute(delete(t.mail_setting).where(t.mail_setting.c.field == LAST_TEST))
    conn.execute(
        insert(t.mail_setting).values(
            field=LAST_TEST,
            value={key: outcome[key] for key in ("at", "ok", "stage", "smtp_code")},
            updated_at=clock.now(),
        )
    )


def _check(name: str, value: object) -> object | None:
    """The value to store, or None when it does not validate."""
    if name == "enabled":
        return value if isinstance(value, bool) else None
    if name == "host":
        return value if valid_host(value) else None
    if name == "port":
        return value if _whole(value, 1, 65535) else None
    if name == "tls":
        return value if value in TLS_MODES else None
    if name == "username":
        return value if headers.printable(value, MAX_USERNAME) else None
    if name == "from":
        if not isinstance(value, dict) or not set(value) <= {"address", "name"}:
            return None
        name_value = value.get("name")
        if not address.valid(value.get("address")):
            return None
        if name_value is not None and not headers.valid_name(name_value):
            return None
        return {"address": value["address"], **({"name": name_value} if name_value else {})}
    if name == "reply_to":
        return value if address.valid(value) else None
    return value if _whole(value, 1, MAX_PER_HOUR) else None  # the three budgets


def _whole(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


_WARNINGS = {
    "smtp_password_in_database": (
        "mail: the SMTP password is stored in the database although the hub runs in "
        "Kubernetes; put it in a Secret (mail.smtp.existingSecret)"
    ),
    "smtp_plaintext_allowed": (
        "mail: MAITY_SMTP_ALLOW_PLAINTEXT is set; a server without STARTTLS gets every "
        "mail in clear, sign-in links included (insecure, for a test bench only)"
    ),
}


def log_warnings(conn: Connection, env: MailEnvironment, secret_key: bytes | None) -> None:
    """At startup: the warnings the admin view carries, in the log as well (§16.2)."""
    for warning in resolve(conn, env, secret_key).warnings:
        log.warning(_WARNINGS[warning])


def _seal(key: bytes, password: str) -> dict[str, str]:
    """The stored form: the sealed bytes, base64, in the JSON column."""
    sealed = secretbox.seal(key, PASSWORD_FIELD, password.encode())
    return {"sealed": base64.b64encode(sealed).decode()}


def _unseal(key: bytes | None, stored: object) -> str | None:
    """The password, or None when there is none, no key, or the key cannot open it (the
    key was changed or lost): such a password counts as not set (§16.2)."""
    if key is None or not isinstance(stored, dict) or not isinstance(stored.get("sealed"), str):
        return None
    try:
        sealed = base64.b64decode(stored["sealed"], validate=True)
        return secretbox.open_sealed(key, PASSWORD_FIELD, sealed).decode()
    except (secretbox.SealedError, ValueError):
        return None
