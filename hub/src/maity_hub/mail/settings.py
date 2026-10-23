"""The instance's mail settings (docs/api.md §16.2): each value from the environment, else
as the instance admin set it, else the default; and the admin's view of them.

The password is write-only whichever its source: the view says whether one is set and
where it came from, never a value, a length, a hash or a hint. A stored password the
current instance key cannot decrypt counts as not set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import clock, secretbox
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.mail import address, headers
from maity_hub.mail.environment import (
    DEFAULT_PORTS,
    MAX_PASSWORD,
    MAX_PER_HOUR,
    MAX_USERNAME,
    TLS_MODES,
    MailConfigError,
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
# The SMTP password's name in `instance_secret`, and the associated data it is sealed
# with (`maity_hub.secretbox`).
PASSWORD_SECRET = "mail.smtp_password"
LAST_TEST = "mail.last_test"

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
    # A password is stored but cannot be opened: no instance key, or another one.
    password_unreadable: bool = False

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
        if self.password_unreadable:
            found.append("smtp_password_unreadable")
        return found


def resolve(conn: Connection, env: MailEnvironment, secret_key: bytes | None) -> Resolved:
    stored = store.stored(conn, "mail")
    values: dict[str, tuple[Any, str]] = {}
    for name in DEFAULTS:
        from_env = env.value(name) if name != "enabled" else None
        if isinstance(from_env, Sender):
            from_env = from_env.view()
        values[name] = store.effective(f"mail.{name}", from_env, stored)
    if values["port"][0] is None:
        values["port"] = (DEFAULT_PORTS[values["tls"][0]], "default")
    password: str | None
    source: str | None
    sealed = store.sealed(conn, PASSWORD_SECRET)
    if env.password is not None:
        password, source = env.password, "env"
    else:
        password = _unseal(secret_key, sealed)
        source = "admin" if password is not None else None
    return Resolved(
        env,
        secret_key is not None,
        values,
        password,
        source,
        stored.get(LAST_TEST),
        # Loud, never a quiet "not set": the admin sets it again (re-key) or removes it.
        password_unreadable=sealed is not None and _unseal(secret_key, sealed) is None,
    )


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


def patch(
    conn: Connection, env: MailEnvironment, secret_key: bytes | None, body: object, by: str
) -> None:
    """Apply the instance admin `by`'s `PATCH` body, all of it or nothing; `invalid`
    names each refused field. A value is never echoed in an error."""
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
            elif not _ascii(value, MAX_PASSWORD):
                errors[name] = "invalid"
            else:
                changes[name] = value
        else:
            checked = store.SETTINGS[f"mail.{name}"].check(value)
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
    for name, value in changes.items():
        if name != "password":
            store.put(conn, f"mail.{name}", value, by)
        elif value is None:
            store.put_sealed(conn, PASSWORD_SECRET, None, by)
        else:
            assert secret_key is not None  # checked above: secret_key_missing
            sealed = secretbox.seal(secret_key, PASSWORD_SECRET, str(value).encode())
            store.put_sealed(conn, PASSWORD_SECRET, sealed, by)
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
        store.put(conn, LAST_TEST, None, by)


def record_test(conn: Connection, outcome: dict[str, Any], by: str) -> None:
    kept = {key: outcome[key] for key in ("at", "ok", "stage", "smtp_code")}
    store.put(conn, LAST_TEST, kept, by)


def tls_refusal(resolved: Resolved) -> str | None:
    """`loopback_host_only` when the settings in effect pair `tls: none` with a host that
    is not loopback, wherever each value came from (§16.2)."""
    host, tls = resolved.value("host"), resolved.value("tls")
    if tls == "none" and host is not None and not is_loopback(str(host)):
        return "loopback_host_only"
    return None


def _ascii(value: object, maximum: int) -> bool:
    """SMTP `AUTH` takes the username and the password as ASCII only."""
    return headers.printable(value, maximum) and isinstance(value, str) and value.isascii()


def _sender(value: object) -> object | None:
    if not isinstance(value, dict) or not set(value) <= {"address", "name"}:
        return None
    name = value.get("name")
    if not address.valid(value.get("address")):
        return None
    if name is not None and not headers.valid_name(name):
        return None
    return {"address": value["address"], **({"name": name} if name else {})}


def _whole(minimum: int, maximum: int) -> Any:
    return lambda value: value if type(value) is int and minimum <= value <= maximum else None


def _when(test: Any) -> Any:
    return lambda value: value if test(value) else None


store.register(
    store.Setting("mail.enabled", _when(lambda v: isinstance(v, bool)), DEFAULTS["enabled"]),
    store.Setting("mail.host", _when(valid_host)),
    store.Setting("mail.port", _whole(1, 65535)),
    store.Setting("mail.tls", _when(lambda v: v in TLS_MODES), DEFAULTS["tls"]),
    store.Setting("mail.username", _when(lambda v: _ascii(v, MAX_USERNAME))),
    store.Setting("mail.from", _sender),
    store.Setting("mail.reply_to", _when(address.valid)),
    store.Setting("mail.max_per_hour", _whole(1, MAX_PER_HOUR), DEFAULTS["max_per_hour"]),
    store.Setting(
        "mail.security_max_per_hour",
        _whole(1, MAX_PER_HOUR),
        DEFAULTS["security_max_per_hour"],
    ),
    store.Setting(
        "mail.sign_in_max_per_hour", _whole(1, MAX_PER_HOUR), DEFAULTS["sign_in_max_per_hour"]
    ),
    # Written by the test send only, never by a PATCH (§16.3).
    store.Setting(LAST_TEST, _when(lambda v: isinstance(v, dict))),
)
store.register_secret(PASSWORD_SECRET)


_WARNINGS = {
    "smtp_password_in_database": (
        "mail: the SMTP password is stored in the database although the hub runs in "
        "Kubernetes; put it in a Secret (mail.smtp.existingSecret)"
    ),
    "smtp_plaintext_allowed": (
        "mail: MAITY_SMTP_ALLOW_PLAINTEXT is set; a server without STARTTLS gets every "
        "mail in clear, sign-in links included (insecure, for a test bench only)"
    ),
    "smtp_password_unreadable": (
        "mail: a stored SMTP password does not open with the current MAITY_SECRET_KEY "
        "(or none is set); set the password again or remove it"
    ),
}


def check_at_startup(conn: Connection, env: MailEnvironment, secret_key: bytes | None) -> None:
    """Stops the hub on `tls: none` with a host that is not loopback, also when one of
    the two came from the environment and the other from the admin (§16.2); logs the
    warnings the admin view carries."""
    resolved = resolve(conn, env, secret_key)
    if tls_refusal(resolved):
        raise MailConfigError(
            "MAITY_SMTP_TLS=none (or the admin's tls: none) is only allowed for a loopback "
            "SMTP host, and the host in effect is not one"
        )
    for warning in resolved.warnings:
        log.warning(_WARNINGS[warning])


def _unseal(key: bytes | None, sealed: bytes | None) -> str | None:
    """The password, or None when there is none, no key, or the key cannot open it (the
    key was changed or lost): such a password counts as not set (§16.2)."""
    if key is None or sealed is None:
        return None
    try:
        return secretbox.open_sealed(key, PASSWORD_SECRET, sealed).decode()
    except (secretbox.SealedError, UnicodeError):
        return None
