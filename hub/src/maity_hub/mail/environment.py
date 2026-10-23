"""The mail settings the operator puts in the environment (docs/api.md §16.2). A value set
here wins over the instance admin's and cannot be changed through the API; a value that
is set but unusable stops the hub at startup. The password and the signing key never
appear in a repr, a log line or a message. The instance key `MAITY_SECRET_KEY` is the
hub's (`Settings.secret_key`, `maity_hub.secretbox`), not mail's own."""

from __future__ import annotations

import base64
import binascii
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

from maity_hub.mail import address, headers

TLS_MODES = ("starttls", "implicit", "none")
DEFAULT_PORTS = {"starttls": 587, "implicit": 465, "none": 25}
MAX_HOST = 253
MAX_USERNAME = 254
MAX_PASSWORD = 1024
MAX_PER_HOUR = 1_000_000
SIGNING_KEY_MIN_BYTES = 32


class MailConfigError(ValueError):
    """A mail setting in the environment is unusable. Never quotes a secret."""


@dataclass(frozen=True)
class Sender:
    address: str
    name: str | None = None

    def view(self) -> dict[str, str]:
        return {"address": self.address, **({"name": self.name} if self.name else {})}


@dataclass(frozen=True)
class MailEnvironment:
    """What the environment sets; `None` is not set."""

    host: str | None = None
    port: int | None = None
    tls: str | None = None
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    sender: Sender | None = None
    reply_to: str | None = None
    max_per_hour: int | None = None
    security_max_per_hour: int | None = None
    sign_in_max_per_hour: int | None = None
    signing_key: bytes | None = field(default=None, repr=False)
    # MAITY_SMTP_ALLOW_PLAINTEXT: insecure, for a test bench only (§16.2).
    allow_plaintext: bool = False
    ca_file: Path | None = None
    # KUBERNETES_SERVICE_HOST is set: a password from the database is flagged.
    in_kubernetes: bool = False

    def value(self, name: str) -> object:
        """The environment's value of an API field, `None` when not set."""
        return self.sender if name == "from" else getattr(self, name)


def is_loopback(host: str) -> bool:
    """`localhost` or a loopback address: the only hosts `tls: none` may name."""
    name = host.lower().rstrip(".")
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name.strip("[]")).is_loopback
    except ValueError:
        return False


def valid_host(value: object) -> bool:
    """A host name or an IP address, nothing else: no port, no scheme, no space."""
    if not isinstance(value, str) or not value or len(value) > MAX_HOST or not value.isascii():
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    labels = value.rstrip(".").split(".")
    return all(address.LABEL.fullmatch(label) for label in labels)


def parse_sender(value: str) -> Sender | None:
    """`maity@example.org` or `Maity <maity@example.org>`; None when neither."""
    value = value.strip()
    name: str | None = None
    if value.endswith(">") and "<" in value:
        name, _, value = value[:-1].rpartition("<")
        name = name.strip() or None
    if not address.valid(value) or (name is not None and not headers.valid_name(name)):
        return None
    return Sender(value, name)


def parse(env: dict[str, str]) -> MailEnvironment:
    def get(name: str) -> str:
        return env.get(name, "").strip()

    host = get("MAITY_SMTP_HOST") or None
    if host is not None and not valid_host(host):
        raise MailConfigError("MAITY_SMTP_HOST must be a host name or an IP address")
    tls = get("MAITY_SMTP_TLS") or None
    if tls is not None and tls not in TLS_MODES:
        raise MailConfigError("MAITY_SMTP_TLS must be starttls, implicit or none")
    if tls == "none" and host is not None and not is_loopback(host):
        raise MailConfigError(
            "MAITY_SMTP_TLS=none is only allowed for a loopback MAITY_SMTP_HOST "
            "(localhost or a loopback address)"
        )
    username = get("MAITY_SMTP_USERNAME") or None
    if username is not None and not headers.printable(username, MAX_USERNAME):
        raise MailConfigError("MAITY_SMTP_USERNAME must be printable, at most 254 characters")
    sender = None
    if get("MAITY_SMTP_FROM"):
        sender = parse_sender(get("MAITY_SMTP_FROM"))
        if sender is None:
            raise MailConfigError(
                "MAITY_SMTP_FROM must be one address, optionally as 'Name <address>'"
            )
    reply_to = get("MAITY_SMTP_REPLY_TO") or None
    if reply_to is not None and not address.valid(reply_to):
        raise MailConfigError("MAITY_SMTP_REPLY_TO must be one address")
    ca_file = Path(get("MAITY_SMTP_CA_FILE")) if get("MAITY_SMTP_CA_FILE") else None
    if ca_file is not None and not ca_file.is_file():
        raise MailConfigError("MAITY_SMTP_CA_FILE does not name a readable file")
    return MailEnvironment(
        host=host,
        port=_number(env, "MAITY_SMTP_PORT", 1, 65535),
        tls=tls,
        username=username,
        password=_password(env),
        sender=sender,
        reply_to=reply_to,
        max_per_hour=_number(env, "MAITY_MAIL_MAX_PER_HOUR", 1, MAX_PER_HOUR),
        security_max_per_hour=_number(env, "MAITY_MAIL_SECURITY_MAX_PER_HOUR", 1, MAX_PER_HOUR),
        sign_in_max_per_hour=_number(env, "MAITY_MAIL_SIGN_IN_MAX_PER_HOUR", 1, MAX_PER_HOUR),
        signing_key=_signing_key(env),
        allow_plaintext=_flag(env, "MAITY_SMTP_ALLOW_PLAINTEXT"),
        ca_file=ca_file,
        in_kubernetes=bool(get("KUBERNETES_SERVICE_HOST")),
    )


def _number(env: dict[str, str], name: str, minimum: int, maximum: int) -> int | None:
    value = env.get(name, "").strip()
    if not value:
        return None
    if not value.isascii() or not value.isdigit() or not minimum <= int(value) <= maximum:
        raise MailConfigError(f"{name} must be a whole number from {minimum} to {maximum}")
    return int(value)


def _flag(env: dict[str, str], name: str) -> bool:
    lowered = env.get(name, "").strip().lower()
    if lowered in ("", "0", "false", "no"):
        return False
    if lowered in ("1", "true", "yes"):
        return True
    raise MailConfigError(f"{name} must be true or false")


def _password(env: dict[str, str]) -> str | None:
    inline = env.get("MAITY_SMTP_PASSWORD", "")
    path = env.get("MAITY_SMTP_PASSWORD_FILE", "").strip()
    if inline and path:
        raise MailConfigError("set MAITY_SMTP_PASSWORD or MAITY_SMTP_PASSWORD_FILE, not both")
    if path:
        try:
            # A mounted Secret ends with a newline more often than not.
            inline = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeDecodeError):
            raise MailConfigError("MAITY_SMTP_PASSWORD_FILE cannot be read as UTF-8") from None
    if not inline:
        return None
    if not headers.printable(inline, MAX_PASSWORD):
        # Never the value, nor where it went wrong.
        raise MailConfigError("the SMTP password must be printable, at most 1024 characters")
    return inline


def _signing_key(env: dict[str, str]) -> bytes | None:
    """`MAITY_MAIL_SIGNING_KEY`: 32 bytes or more, base64; never quoted in a message."""
    value = env.get("MAITY_MAIL_SIGNING_KEY", "").strip()
    if not value:
        return None
    try:
        key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise MailConfigError("MAITY_MAIL_SIGNING_KEY is not base64") from None
    if len(key) < SIGNING_KEY_MIN_BYTES:
        raise MailConfigError(
            f"MAITY_MAIL_SIGNING_KEY must be at least {SIGNING_KEY_MIN_BYTES} bytes, base64"
        )
    return key
