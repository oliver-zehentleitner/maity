"""Settings, read from the environment once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DEFAULT_DATABASE_URL = "sqlite:///maity-hub.db"
DEFAULT_BIND = "127.0.0.1:8080"

_WILDCARD_HOSTS = {"0.0.0.0", "::"}


class ConfigError(ValueError):
    """A setting is present but unusable. The message never contains a credential."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    host: str
    port: int
    public_url: str
    public_url_guessed: bool
    web_dir: Path | None
    web_dir_required: bool

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ) if env is None else env
        host, port = parse_bind(env.get("MAITY_BIND", DEFAULT_BIND))
        public_url = env.get("MAITY_PUBLIC_URL")
        web_dir_env = env.get("MAITY_WEB_DIR")
        return cls(
            database_url=normalize_database_url(
                env.get("MAITY_DATABASE_URL", DEFAULT_DATABASE_URL)
            ),
            host=host,
            port=port,
            public_url=(public_url or derive_public_url(host, port)).rstrip("/"),
            public_url_guessed=not public_url and host in _WILDCARD_HOSTS,
            web_dir=Path(web_dir_env) if web_dir_env else checkout_web_dir(),
            web_dir_required=bool(web_dir_env),
        )


def parse_bind(bind: str) -> tuple[str, int]:
    """Split `host:port`; `[::1]:8080` for IPv6."""
    host, sep, port = bind.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ConfigError(f"MAITY_BIND must be host:port, got {bind!r}")
    return host.strip("[]"), int(port)


def derive_public_url(host: str, port: int) -> str:
    """The URL the hub is reachable under when MAITY_PUBLIC_URL is not set.

    A wildcard bind says nothing about the name clients use; `localhost` is
    the guess that works on the same machine, and the caller warns about it.
    """
    if host in _WILDCARD_HOSTS:
        host = "localhost"
    elif ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def checkout_web_dir() -> Path | None:
    """`web/` beside `hub/` when running from a checkout, else nothing."""
    package = Path(__file__).resolve().parent
    hub = package.parents[1]
    if package.parent.name == "src" and (hub / "pyproject.toml").is_file():
        return hub.parent / "web"
    return None


_DRIVERS = {
    "postgres": "postgresql+psycopg",
    "postgresql": "postgresql+psycopg",
    "mysql": "mysql+pymysql",
    "mariadb": "mariadb+pymysql",
}


def normalize_database_url(url: str) -> str:
    """Pin the driver the hub ships with when the URL names only the database.

    `postgresql://` would otherwise make SQLAlchemy look for psycopg2 and
    `mysql://` for mysqlclient, neither of which is installed.
    """
    try:
        parsed = make_url(url)
    except ArgumentError:
        raise ConfigError("MAITY_DATABASE_URL is not a database URL") from None
    if parsed.host and "@" in parsed.host:
        # An unencoded `@` in the password splits it: the tail would be taken
        # for the host name and end up in error messages.
        raise ConfigError(
            "MAITY_DATABASE_URL: a password containing '@' must be percent-encoded (%40)"
        )
    parsed = parsed.set(drivername=_DRIVERS.get(parsed.drivername, parsed.drivername))
    return parsed.render_as_string(hide_password=False)


def redact_database_url(url: str) -> str:
    """The URL with its password masked, for messages and logs."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except ArgumentError:
        return "<unparseable MAITY_DATABASE_URL>"
