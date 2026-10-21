"""Settings, read from the environment once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_URL = "sqlite:///maity-hub.db"
DEFAULT_BIND = "127.0.0.1:8080"

# In a checkout the dashboard sits next to the hub: <repo>/web beside <repo>/hub/src/maity_hub.
_CHECKOUT_WEB_DIR = Path(__file__).resolve().parents[3] / "web"


class ConfigError(ValueError):
    """A setting is present but unusable."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    host: str
    port: int
    public_url: str
    web_dir: Path | None
    web_dir_required: bool

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ) if env is None else env
        host, port = parse_bind(env.get("MAITY_BIND", DEFAULT_BIND))
        public_url = env.get("MAITY_PUBLIC_URL") or f"http://{host}:{port}"
        web_dir_env = env.get("MAITY_WEB_DIR")
        return cls(
            database_url=normalize_database_url(
                env.get("MAITY_DATABASE_URL", DEFAULT_DATABASE_URL)
            ),
            host=host,
            port=port,
            public_url=public_url.rstrip("/"),
            web_dir=Path(web_dir_env) if web_dir_env else _CHECKOUT_WEB_DIR,
            web_dir_required=bool(web_dir_env),
        )


def parse_bind(bind: str) -> tuple[str, int]:
    """Split `host:port`; `[::1]:8080` for IPv6."""
    host, sep, port = bind.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ConfigError(f"MAITY_BIND must be host:port, got {bind!r}")
    return host.strip("[]"), int(port)


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
    scheme, sep, rest = url.partition("://")
    if not sep:
        raise ConfigError(f"MAITY_DATABASE_URL is not a URL: {url!r}")
    return f"{_DRIVERS.get(scheme, scheme)}://{rest}"
