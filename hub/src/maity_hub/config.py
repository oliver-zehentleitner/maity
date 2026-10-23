"""Settings, read from the environment once at startup."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DEFAULT_DATABASE_URL = "sqlite:///maity-hub.db"
DEFAULT_BIND = "127.0.0.1:8080"

_WILDCARD_HOSTS = {"0.0.0.0", "::"}


class ConfigError(ValueError):
    """A setting is present but unusable. The message never contains a credential."""


# Until the package is on PyPI; from then on `pipx install maity` (§3.2).
DEFAULT_CLI_INSTALL = (
    'pipx install "git+https://github.com/oliver-zehentleitner/maity#subdirectory=cli"'
)


@dataclass(frozen=True)
class Settings:
    database_url: str
    host: str
    port: int
    public_url: str
    public_url_guessed: bool
    web_dir: Path | None
    web_dir_required: bool
    trusted_proxies: tuple[IPNetwork, ...] = field(default=())
    allow_plain_http: bool = False
    # Never logged, never in a response; only whether it is set is shown (§11).
    forge_github_token: str | None = field(default=None, repr=False)
    # MAITY_JOIN_URL: a second hostname that serves the agent join only (§1.1).
    join_url: str | None = None
    # MAITY_CLI_INSTALL: the one line that installs the CLI, wherever the hub tells an
    # agent how to get it (§3.2).
    cli_install: str = DEFAULT_CLI_INSTALL
    # The avatar decoder's budgets (§6.10): seconds and MiB per decode, and how many
    # decodes run at once.
    avatar_decode_seconds: float = 5.0
    avatar_decode_memory_mb: int = 512
    avatar_decodes: int = 2

    @property
    def join_host(self) -> str | None:
        """The join URL's hostname, lower case and without a trailing dot, or None."""
        if self.join_url is None:
            return None
        return (urlsplit(self.join_url).hostname or "").lower().rstrip(".")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ) if env is None else env
        host, port = parse_bind(env.get("MAITY_BIND", DEFAULT_BIND))
        public_url = env.get("MAITY_PUBLIC_URL")
        web_dir_env = env.get("MAITY_WEB_DIR")
        public = (public_url or derive_public_url(host, port)).rstrip("/")
        return cls(
            database_url=normalize_database_url(
                env.get("MAITY_DATABASE_URL", DEFAULT_DATABASE_URL)
            ),
            host=host,
            port=port,
            public_url=public,
            public_url_guessed=not public_url and host in _WILDCARD_HOSTS,
            web_dir=Path(web_dir_env) if web_dir_env else checkout_web_dir(),
            web_dir_required=bool(web_dir_env),
            trusted_proxies=parse_networks(env.get("MAITY_TRUSTED_PROXIES", "")),
            forge_github_token=env.get("MAITY_FORGE_GITHUB_TOKEN") or None,
            allow_plain_http=parse_flag(
                env.get("MAITY_ALLOW_PLAIN_HTTP", ""), "MAITY_ALLOW_PLAIN_HTTP"
            ),
            join_url=parse_join_url(env.get("MAITY_JOIN_URL", ""), public),
            cli_install=parse_cli_install(env.get("MAITY_CLI_INSTALL", "")),
            avatar_decode_seconds=parse_number(
                env, "MAITY_AVATAR_DECODE_SECONDS", 5.0, minimum=0.5, maximum=120
            ),
            avatar_decode_memory_mb=int(
                parse_number(env, "MAITY_AVATAR_DECODE_MEMORY_MB", 512, minimum=128, maximum=8192)
            ),
            avatar_decodes=int(parse_number(env, "MAITY_AVATAR_DECODES", 2, minimum=1, maximum=64)),
        )


def parse_number(
    env: dict[str, str], name: str, default: float, *, minimum: float, maximum: float
) -> float:
    """A numeric setting within its range; unset is the default, anything else stops
    the hub."""
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        number = float(value)
    except ValueError:
        raise ConfigError(f"{name} is not a number: {value!r}") from None
    if not minimum <= number <= maximum:
        raise ConfigError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def parse_cli_install(value: str) -> str:
    """`MAITY_CLI_INSTALL`: one line, shown as it is in a code span; a line break stops
    the hub."""
    value = value.strip()
    if any(c in value for c in "\r\n\x00"):
        raise ConfigError("MAITY_CLI_INSTALL must be a single line")
    return value or DEFAULT_CLI_INSTALL


def parse_join_url(value: str, public_url: str) -> str | None:
    """`MAITY_JOIN_URL`: https, a host and nothing else, and not the public URL's host
    (§1.1). Anything else stops the hub."""
    value = value.strip()
    if not value:
        return None
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018  a malformed port raises here
    except ValueError:
        raise ConfigError(f"MAITY_JOIN_URL is not a URL: {value!r}") from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ConfigError(f"MAITY_JOIN_URL must be https://<host> with no path, got {value!r}")
    if parts.hostname.lower().rstrip(".") == (urlsplit(public_url).hostname or "").lower().rstrip(
        "."
    ):
        raise ConfigError("MAITY_JOIN_URL must name another host than MAITY_PUBLIC_URL")
    return value.rstrip("/")


IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(value: str) -> tuple[IPNetwork, ...]:
    """`MAITY_TRUSTED_PROXIES`: a comma-separated CIDR list; a bare address is a /32 or /128."""
    networks = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ConfigError(
                f"MAITY_TRUSTED_PROXIES: {part!r} is not an address or CIDR"
            ) from None
    return tuple(networks)


def parse_flag(value: str, name: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("", "0", "false", "no"):
        return False
    if lowered in ("1", "true", "yes"):
        return True
    raise ConfigError(f"{name} must be 1 or 0, got {value!r}")


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
    scheme, _, rest = url.partition("://")
    if not scheme.startswith("sqlite") and rest.count("@") > 1:
        # A second unencoded `@` (in the user, the password, the database or the
        # query) splits the URL: a password's tail would be taken for the host,
        # the port or the database name and end up in messages.
        raise ConfigError(
            "MAITY_DATABASE_URL has an '@' that is not the one before the host: "
            "an '@' in any part of the URL must be percent-encoded (%40)"
        )
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        # Never the parser's message: it quotes the text it failed on.
        raise ConfigError("MAITY_DATABASE_URL is not a valid database URL") from None
    parsed = parsed.set(drivername=_DRIVERS.get(parsed.drivername, parsed.drivername))
    return parsed.render_as_string(hide_password=False)


def redact_database_url(url: str) -> str:
    """The URL with its password masked, for messages and logs."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return "<unparseable MAITY_DATABASE_URL>"
