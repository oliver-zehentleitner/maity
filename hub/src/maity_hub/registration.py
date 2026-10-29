"""Registration (docs/api.md §2.7, §16.4): whether a person may get an account on their own,
and the instance admin's settings that decide it.

Each setting comes from the environment, else from the instance admin, else its default,
by `instance_settings.effective`. `allowlist` and `open` need complete and enabled mail
(§16.2): a `PATCH` to either is refused without it, and a mode from the environment then
counts as `closed` (`effective_mode`). A fresh instance is `closed`; nothing but the
admin's setting or the operator's environment opens it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import clock
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.mail import address

MODES = ("closed", "allowlist", "open")
APPROVALS = ("automatic", "operator")
SECTION = "registration"
FIELDS = ("mode", "domains", "addresses", "approval", "terms", "max_new_accounts_per_hour")
DEFAULTS: dict[str, object] = {
    "mode": "closed",
    "domains": [],
    "addresses": [],
    "approval": "operator",
    "terms": None,
    "max_new_accounts_per_hour": 20,
}
BREAKER_DEFAULT = 120  # requests per minute across the instance (§2.7.3)
MAX_NEW_PER_HOUR = 10_000
MAX_URL, MAX_VERSION = 2048, 64
MAX_LIST = 1000
PENDING_FOR = timedelta(hours=24)  # a pending registration's life (§2.7.1)
PENDING_PER_ADDRESS = 5


class RegistrationConfigError(ValueError):
    pass


# --- the entries -----------------------------------------------------------------------


def normalized(value: str) -> str:
    """The form one account per address compares: trimmed and lower-cased (§2.6.3,
    §18.4). The same as `mail.address.normalized` of the notification settings (#280),
    which takes its place once that lands."""
    return value.strip().lower()


def domain_entry(value: object) -> str | None:
    """`@` plus a host name of §18.4, lower case; None when it is not one."""
    if not isinstance(value, str) or not value.startswith("@"):
        return None
    host = value[1:].strip().lower()
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2:
        return None
    if not all(address.LABEL.fullmatch(label) for label in labels):
        return None
    return f"@{host}"


def address_entry(value: object) -> str | None:
    """An exact address of §18.4, compared trimmed and lower-cased (§2.6.3)."""
    if not isinstance(value, str) or not address.valid(value.strip()):
        return None
    return value.strip().lower()


def _entries(value: object, entry: Any) -> list[str] | None:
    if not isinstance(value, list) or len(value) > MAX_LIST:
        return None
    found = [entry(item) for item in value]
    if any(item is None for item in found):
        return None
    return list(dict.fromkeys(found))  # lower case, no duplicates, in order


def bad_index(value: object, entry: Any) -> int | None:
    """The first entry that does not validate, for `details.fields`."""
    if not isinstance(value, list):
        return None
    return next((i for i, item in enumerate(value) if entry(item) is None), None)


def terms_value(value: object) -> dict[str, str] | None:
    """`{url, version}`: an https URL of at most 2048 characters and a version of 1–64
    characters without whitespace; both or neither (§16.4)."""
    if not isinstance(value, dict) or set(value) != {"url", "version"}:
        return None
    url, version = value["url"], value["version"]
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > MAX_URL:
        return None
    if len(url) <= len("https://") or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    if not isinstance(version, str) or not 1 <= len(version) <= MAX_VERSION:
        return None
    if any(c.isspace() for c in version):
        return None
    return {"url": url, "version": version}


def _choice(choices: tuple[str, ...]) -> Any:
    return lambda value: value if value in choices else None


def _count(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if 1 <= value <= MAX_NEW_PER_HOUR else None


store.register(
    store.Setting("registration.mode", _choice(MODES), DEFAULTS["mode"]),
    store.Setting("registration.domains", lambda v: _entries(v, domain_entry), DEFAULTS["domains"]),
    store.Setting(
        "registration.addresses", lambda v: _entries(v, address_entry), DEFAULTS["addresses"]
    ),
    store.Setting("registration.approval", _choice(APPROVALS), DEFAULTS["approval"]),
    store.Setting("registration.terms", terms_value, DEFAULTS["terms"]),
    store.Setting("registration.max_new_accounts_per_hour", _count, 20),
)


# --- the environment -------------------------------------------------------------------


@dataclass(frozen=True)
class RegistrationEnvironment:
    """What `MAITY_REGISTRATION*` and `MAITY_TERMS_*` set; None where unset."""

    values: dict[str, object] = field(default_factory=dict)
    breaker: int = BREAKER_DEFAULT

    def value(self, name: str) -> object:
        return self.values.get(name)


def _list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse(env: dict[str, str]) -> RegistrationEnvironment:
    """Read the environment; a value that does not validate stops the hub."""
    values: dict[str, object] = {}
    mode = env.get("MAITY_REGISTRATION", "").strip()
    if mode:
        if mode not in MODES:
            raise RegistrationConfigError(f"MAITY_REGISTRATION must be one of {MODES}")
        values["mode"] = mode
    for name, key, entry in (
        ("MAITY_REGISTRATION_DOMAINS", "domains", domain_entry),
        ("MAITY_REGISTRATION_ADDRESSES", "addresses", address_entry),
    ):
        raw = env.get(name, "").strip()
        if raw:
            found = _entries(_list(raw), entry)
            if found is None:
                raise RegistrationConfigError(f"{name} has an entry that is not valid")
            values[key] = found
    approval = env.get("MAITY_REGISTRATION_APPROVAL", "").strip()
    if approval:
        if approval not in APPROVALS:
            raise RegistrationConfigError(f"MAITY_REGISTRATION_APPROVAL must be {APPROVALS}")
        values["approval"] = approval
    url = env.get("MAITY_TERMS_URL", "").strip()
    version = env.get("MAITY_TERMS_VERSION", "").strip()
    if url or version:
        terms = terms_value({"url": url, "version": version})
        if terms is None:
            raise RegistrationConfigError(
                "MAITY_TERMS_URL and MAITY_TERMS_VERSION: both or neither, an https URL "
                "and a version without whitespace"
            )
        values["terms"] = terms
    for name, key, minimum, maximum in (
        ("MAITY_REGISTRATION_MAX_NEW_PER_HOUR", "max_new_accounts_per_hour", 1, MAX_NEW_PER_HOUR),
        ("MAITY_REGISTRATION_BREAKER", "breaker", 1, 100_000),
    ):
        raw = env.get(name, "").strip()
        if not raw:
            continue
        if not raw.isdigit() or not minimum <= int(raw) <= maximum:
            raise RegistrationConfigError(f"{name} must be a number from {minimum} to {maximum}")
        values[key] = int(raw)
    breaker = values.pop("breaker", BREAKER_DEFAULT)
    assert isinstance(breaker, int)
    return RegistrationEnvironment(values, breaker)


# --- the settings in effect ------------------------------------------------------------


@dataclass(frozen=True)
class Resolved:
    values: dict[str, tuple[Any, str]]  # name -> (value, source)
    mail_ready: bool  # mail complete and enabled (§16.2)

    def value(self, name: str) -> Any:
        return self.values[name][0]

    @property
    def effective_mode(self) -> str:
        """What the hub does now: without mail, `closed` whatever is set (§16.4)."""
        mode = str(self.value("mode"))
        return mode if mode == "closed" or self.mail_ready else "closed"

    @property
    def missing(self) -> list[str]:
        found = []
        if self.value("mode") != "closed" and not self.mail_ready:
            found.append("mail")
        if self.value("mode") == "allowlist" and not (
            self.value("domains") or self.value("addresses")
        ):
            found.append("allowlist")
        return found

    def allows(self, given: str) -> bool:
        """Whether this address may register under the mode in effect (§2.7)."""
        mode = self.effective_mode
        if mode == "open":
            return True
        if mode != "allowlist":
            return False
        normalized_given = normalized(given)
        domain = "@" + normalized_given.rpartition("@")[2]
        return domain in (self.value("domains") or []) or normalized_given in (
            self.value("addresses") or []
        )


def resolve(
    conn: Connection, env: RegistrationEnvironment, mail_ready: bool, public_url: str
) -> Resolved:
    stored = store.stored(conn, SECTION)
    values = {
        name: store.effective(f"{SECTION}.{name}", env.value(name), stored) for name in FIELDS
    }
    if values["terms"][1] == "default":  # none from the environment, none set by the admin
        current = conn.execute(
            select(t.legal_page.c.current).where(t.legal_page.c.page == "terms")
        ).scalar()
        if current is not None and public_url:
            # The terms page, so that a person accepts exactly the version they could read
            # (§16.7.1): the order is the environment, the admin's value, the legal pages.
            values["terms"] = (
                {"url": f"{public_url.rstrip('/')}/terms", "version": current},
                "legal_pages",
            )
    return Resolved(values, mail_ready)


def mail_ready(conn: Connection, hub: Any) -> bool:
    """Mail complete and enabled (§16.2), as the mail settings resolve now."""
    from maity_hub.mail import settings as mail_settings

    resolved = mail_settings.resolve(conn, hub.mail, hub.secret_key)
    return bool(resolved.complete and resolved.enabled)


def view(conn: Connection, resolved: Resolved) -> dict[str, Any]:
    """The answer of `GET` and `PATCH /admin/settings/registration` (§16.4)."""
    since = clock.now() - timedelta(hours=1)
    answer: dict[str, Any] = {}
    for name in FIELDS:
        value, source = resolved.values[name]
        answer[name] = {"value": value, "source": source}
        if name == "mode":
            answer["effective_mode"] = resolved.effective_mode
    pending = conn.execute(
        select(func.count()).select_from(t.human).where(t.human.c.account_status == "pending")
    ).scalar_one()
    registered = conn.execute(
        select(func.count()).select_from(t.human).where(t.human.c.registered_at >= since)
    ).scalar_one()
    answer.update(
        {
            "missing": resolved.missing,
            "pending": int(pending),
            "registered_last_hour": int(registered),
            "requests_dropped_last_hour": DROPPED.last_hour(),
        }
    )
    return answer


def patch(
    conn: Connection, env: RegistrationEnvironment, ready: bool, body: object, by: str
) -> None:
    """Apply the instance admin `by`'s `PATCH` body, all of it or nothing (§16.4)."""
    if not isinstance(body, dict):
        raise invalid({"body": "not_an_object"})
    errors: dict[str, str] = {}
    changes: dict[str, object] = {}
    for name, value in body.items():
        if name not in FIELDS:
            errors[name] = "extra_forbidden"
        elif env.value(name) is not None:
            errors[name] = "set_by_environment"
        elif value is None:
            changes[name] = None
        else:
            checked = store.SETTINGS[f"{SECTION}.{name}"].check(value)
            if checked is not None:
                changes[name] = checked
            elif name in ("domains", "addresses"):
                entry = domain_entry if name == "domains" else address_entry
                index = bad_index(value, entry)
                errors[name if index is None else f"{name}.{index}"] = "invalid"
            else:
                errors[name] = "invalid"
    if errors:
        raise invalid(errors)
    mode = changes.get("mode")
    if mode in ("allowlist", "open") and not ready:
        raise invalid({"mode": "mail_required"}, "registration needs complete, enabled mail")
    for name, value in changes.items():
        store.put(conn, f"{SECTION}.{name}", value, by)


# --- what the instance counts in memory (one replica, like the other limits) -----------


class Dropped:
    """Requests the background step dropped, for `requests_dropped_last_hour`."""

    def __init__(self) -> None:
        self._at: list[float] = []
        self._lock = threading.Lock()

    def add(self) -> None:
        with self._lock:
            self._at.append(time.monotonic())

    def last_hour(self) -> int:
        cutoff = time.monotonic() - 3600
        with self._lock:
            self._at = [at for at in self._at if at >= cutoff]
            return len(self._at)


class Breaker:
    """More than `limit` requests in a minute across the instance stops every request
    for a minute (§2.7.3); every request counts, refused or not."""

    def __init__(self) -> None:
        self._at: list[float] = []
        self._open_until = 0.0
        self._lock = threading.Lock()

    def hit(self, limit: int) -> int:
        """Seconds to wait when tripped, else 0."""
        now = time.monotonic()
        with self._lock:
            self._at = [at for at in self._at if at > now - 60] + [now]
            if len(self._at) > limit:
                self._open_until = max(self._open_until, now + 60)
            return int(self._open_until - now) + 1 if now < self._open_until else 0


DROPPED = Dropped()
BREAKER = Breaker()
