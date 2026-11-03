"""Settings, read from the environment once at startup."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from maity_hub import github_app, secretbox
from maity_hub.github_app import GitHubApp
from maity_hub.mail import environment as mail_environment
from maity_hub.mail.environment import MailEnvironment

DEFAULT_DATABASE_URL = "sqlite:///maity-hub.db"
DEFAULT_BIND = "127.0.0.1:8080"
KTW_SKILL_SOURCE = (
    "https://github.com/oliver-zehentleitner/keep-the-why/tree/latest/skills/keep-the-why"
)
KTW_SKILL_GUIDE = "https://keepthewhy.com/installation/"

_WILDCARD_HOSTS = {"0.0.0.0", "::"}


class ConfigError(ValueError):
    """A setting is present but unusable. The message never contains a credential."""


@dataclass(frozen=True)
class AttachmentS3:
    """`MAITY_ATTACHMENT_S3_*` (§8.7, §16): the bucket of the `s3` store. The credentials
    are never logged and never in a repr; unset, the client finds its own (an instance
    role, a mounted profile)."""

    bucket: str
    endpoint: str | None = None
    prefix: str = ""
    region: str | None = None
    access_key_id: str | None = field(default=None, repr=False)
    secret_access_key: str | None = field(default=None, repr=False)


# The CLI as published on PyPI (§3.2); a fork points MAITY_CLI_INSTALL at its own.
DEFAULT_CLI_INSTALL = "pipx install maity"


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
    # MAITY_FORGE_GITHUB_APP_*: the instance's GitHub App, all five settings or none
    # (§11.4); its key and client secret never in a repr.
    github_app: GitHubApp | None = field(default=None, repr=False)
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
    # MAITY_ATTACHMENT_STORE, MAITY_ATTACHMENT_DIR, MAITY_ATTACHMENT_S3_*,
    # MAITY_ATTACHMENT_QUOTA (§8.7, §16): where an attachment's bytes live and how many a
    # project may store. `local` (the default) with `attachment_dir` unset leaves
    # attachments unconfigured; `s3` is opt-in, for replicas that share the bytes.
    attachment_store: str = "local"
    attachment_dir: Path | None = None
    attachment_s3: AttachmentS3 | None = None
    attachment_quota: int = 1024 * 1024 * 1024
    # MAITY_DB_POOL_SIZE, MAITY_DB_MAX_OVERFLOW: the server database's connection pool
    # (16 + 16; SQLAlchemy's own defaults are 5 + 10, hub/context/persistence.md).
    db_pool_size: int = 16
    db_max_overflow: int = 16
    # MAITY_DB_POOL_RECYCLE: seconds after which a pooled connection is replaced; 0 never.
    db_pool_recycle: int = 1800
    # MAITY_DB_STATEMENT_TIMEOUT, MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT: seconds, set on every
    # PostgreSQL connection of the hub (30 and 60; 0 turns one off, hub/context/persistence.md).
    db_statement_timeout: float = 30.0
    db_idle_in_transaction_timeout: float = 60.0
    # MAITY_DIRECT_DATABASE_URL: PostgreSQL past a pooler, for the one connection per process
    # that listens for other replicas' wake-ups (hub/context/replicas.md 387c2409); unset, the
    # listener uses `database_url`.
    direct_database_url: str | None = None
    # MAITY_SECRET_KEY: the instance key for secrets stored at rest (§16.2, §17.4);
    # never logged, never in a response, never in the database.
    secret_key: bytes | None = field(default=None, repr=False)
    # MAITY_SMTP_*, MAITY_MAIL_*: the mail settings the environment sets (§16.2); the
    # password and the signing key never appear in a repr.
    mail: MailEnvironment = field(default_factory=MailEnvironment)
    # MAITY_SIGN_IN_DEVICE_CODE, MAITY_SIGN_IN_EMAIL_LINK: the sign-in methods when the
    # environment switches them (§2.6.6); None leaves them to the instance admin.
    sign_in_device_code: bool | None = None
    sign_in_email_link: bool | None = None
    # MAITY_ON_RUNNER_REVOKE: what revoking a runner does to its agents where a project
    # says `inherit` (§15.3, §16): keep, stop, or stop_floor (stop, and a project's keep
    # is refused).
    on_runner_revoke: str = "keep"
    # MAITY_KTW_SKILL_SOURCE: where the Keep the Why skill is published, as told to a
    # joining agent (§6.23); an operator who mirrors the skill points it elsewhere.
    ktw_skill_source: str = KTW_SKILL_SOURCE
    # MAITY_KTW_SKILL_GUIDE: the skill's installation guide for every harness, the page an
    # agent names to its human when `install` or `load` does not fit (§6.23).
    ktw_skill_guide: str = KTW_SKILL_GUIDE
    # MAITY_REGISTRATION*, MAITY_TERMS_*: what the environment sets for registration
    # (§16.4); None where it leaves the instance admin to decide.
    registration: Any = None
    # MAITY_SIGN_IN_SECOND_FACTOR: off, optional or required_admins (§2.8.5); None
    # leaves it to the instance admin.
    sign_in_second_factor: str | None = None
    # MAITY_MAX_AGENTS_PER_HUMAN, MAITY_MAX_ORGS_PER_HUMAN (§16.5): a number from 1 to 10000 or
    # `unlimited`; None where the environment leaves the value to the instance admin.
    max_agents_per_human: int | str | None = None
    max_orgs_per_human: int | str | None = None
    # MAITY_PUBLIC_PAGES (`on`/`off`, §16.9): whether the hub serves public pages at all;
    # MAITY_PUBLIC_PAGES_RENDER (`on_change`/`interval`) and MAITY_PUBLIC_PAGES_INTERVAL_HOURS
    # (1–24) say when a page is rendered again.
    public_pages: bool = False
    public_pages_render: str = "on_change"
    public_pages_interval_hours: int = 6
    public_pages_snapshot_minutes: int = 5

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
            direct_database_url=(
                normalize_database_url(
                    env["MAITY_DIRECT_DATABASE_URL"], "MAITY_DIRECT_DATABASE_URL"
                )
                if env.get("MAITY_DIRECT_DATABASE_URL")
                else None
            ),
            host=host,
            port=port,
            public_url=public,
            public_url_guessed=not public_url and host in _WILDCARD_HOSTS,
            web_dir=Path(web_dir_env) if web_dir_env else checkout_web_dir(),
            web_dir_required=bool(web_dir_env),
            trusted_proxies=parse_networks(env.get("MAITY_TRUSTED_PROXIES", "")),
            forge_github_token=env.get("MAITY_FORGE_GITHUB_TOKEN") or None,
            github_app=parse_github_app(env),
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
            attachment_store=parse_attachment_store(env),
            attachment_dir=parse_attachment_dir(env),
            attachment_s3=parse_attachment_s3(env),
            attachment_quota=int(
                parse_number(env, "MAITY_ATTACHMENT_QUOTA", 1024**3, minimum=1024, maximum=2**50)
            ),
            db_pool_size=int(parse_number(env, "MAITY_DB_POOL_SIZE", 16, minimum=1, maximum=500)),
            db_max_overflow=int(
                parse_number(env, "MAITY_DB_MAX_OVERFLOW", 16, minimum=0, maximum=500)
            ),
            db_pool_recycle=int(
                parse_number(env, "MAITY_DB_POOL_RECYCLE", 1800, minimum=0, maximum=86400)
            ),
            db_statement_timeout=parse_number(
                env, "MAITY_DB_STATEMENT_TIMEOUT", 30.0, minimum=0, maximum=3600
            ),
            db_idle_in_transaction_timeout=parse_number(
                env, "MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT", 60.0, minimum=0, maximum=3600
            ),
            secret_key=parse_secret_key(env.get("MAITY_SECRET_KEY", "")),
            mail=parse_mail(env),
            sign_in_device_code=parse_switch(env, "MAITY_SIGN_IN_DEVICE_CODE"),
            sign_in_email_link=parse_switch(env, "MAITY_SIGN_IN_EMAIL_LINK"),
            on_runner_revoke=parse_choice(
                env, "MAITY_ON_RUNNER_REVOKE", ("keep", "stop", "stop_floor"), "keep"
            ),
            ktw_skill_source=parse_skill_source(env.get("MAITY_KTW_SKILL_SOURCE", "")),
            ktw_skill_guide=parse_skill_url(
                "MAITY_KTW_SKILL_GUIDE", env.get("MAITY_KTW_SKILL_GUIDE", ""), KTW_SKILL_GUIDE
            ),
            registration=parse_registration(env),
            sign_in_second_factor=parse_second_factor(env),
            public_pages=parse_choice(env, "MAITY_PUBLIC_PAGES", ("on", "off"), "off") == "on",
            public_pages_render=parse_choice(
                env, "MAITY_PUBLIC_PAGES_RENDER", ("on_change", "interval"), "on_change"
            ),
            public_pages_interval_hours=parse_whole(
                env, "MAITY_PUBLIC_PAGES_INTERVAL_HOURS", 6, 1, 24
            ),
            public_pages_snapshot_minutes=parse_whole(
                env, "MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES", 5, 1, 60
            ),
            max_agents_per_human=parse_limit(env, "MAITY_MAX_AGENTS_PER_HUMAN"),
            max_orgs_per_human=parse_limit(env, "MAITY_MAX_ORGS_PER_HUMAN"),
        )


def parse_skill_source(value: str) -> str:
    """Unset is the skill's published tree; anything but an https URL stops the hub."""
    return parse_skill_url("MAITY_KTW_SKILL_SOURCE", value, KTW_SKILL_SOURCE)


def parse_skill_url(name: str, value: str, default: str) -> str:
    """Unset is `default`; anything but an https URL stops the hub. The value ends up in
    an agent's instructions, so a `file:` or `javascript:` URL is refused."""
    value = value.strip()
    if not value:
        return default
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or any(c.isspace() for c in value):
        raise ConfigError(f"{name} must be an https URL")
    return value


def parse_github_app(env: dict[str, str]) -> GitHubApp | None:
    """All five App settings or none: a partial set stops the hub (§11.4)."""
    try:
        return github_app.parse(env)
    except github_app.AppConfigError as error:
        raise ConfigError(str(error)) from None


def parse_attachment_store(env: dict[str, str]) -> str:
    """`local` (the default) or `s3` (§8.7); anything else stops the hub."""
    value = env.get("MAITY_ATTACHMENT_STORE", "").strip() or "local"
    if value not in ("local", "s3"):
        raise ConfigError(f"MAITY_ATTACHMENT_STORE must be local or s3: {value!r}")
    return value


def parse_attachment_s3(env: dict[str, str]) -> AttachmentS3 | None:
    """The `s3` store's settings, read only when `MAITY_ATTACHMENT_STORE` is `s3`: the
    bucket is required, the endpoint is https unless `MAITY_ATTACHMENT_S3_ALLOW_HTTP=1`
    and its host is a loopback or cluster-internal one, and the credentials come as a
    pair or not at all. No message names a credential's value."""
    if parse_attachment_store(env) != "s3":
        return None
    bucket = env.get("MAITY_ATTACHMENT_S3_BUCKET", "").strip()
    if not bucket:
        raise ConfigError("MAITY_ATTACHMENT_STORE=s3 needs MAITY_ATTACHMENT_S3_BUCKET")
    if any(c.isspace() or c == "/" for c in bucket):
        raise ConfigError("MAITY_ATTACHMENT_S3_BUCKET must be a bucket name")
    allow_http = parse_flag(
        env.get("MAITY_ATTACHMENT_S3_ALLOW_HTTP", ""), "MAITY_ATTACHMENT_S3_ALLOW_HTTP"
    )
    endpoint = parse_s3_endpoint(env.get("MAITY_ATTACHMENT_S3_ENDPOINT", ""), allow_http)
    prefix = env.get("MAITY_ATTACHMENT_S3_PREFIX", "").strip().strip("/")
    if any(c.isspace() for c in prefix) or {".", ".."} & set(prefix.split("/")):
        raise ConfigError(
            "MAITY_ATTACHMENT_S3_PREFIX must be a key prefix such as maity/attachments"
        )
    key_id = env.get("MAITY_ATTACHMENT_S3_ACCESS_KEY_ID", "").strip() or None
    secret = env.get("MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY", "").strip() or None
    if (key_id is None) != (secret is None):
        raise ConfigError(
            "MAITY_ATTACHMENT_S3_ACCESS_KEY_ID and MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY "
            "are set together or not at all"
        )
    return AttachmentS3(
        bucket=bucket,
        endpoint=endpoint,
        prefix=prefix,
        region=env.get("MAITY_ATTACHMENT_S3_REGION", "").strip() or None,
        access_key_id=key_id,
        secret_access_key=secret,
    )


def parse_s3_endpoint(value: str, allow_http: bool) -> str | None:
    """Unset leaves the endpoint to the client (AWS for the region). Otherwise an https
    URL; `http` only with the switch and only to a host that does not leave the machine
    or the cluster (`cluster_internal`)."""
    value = value.strip()
    if not value:
        return None
    name = "MAITY_ATTACHMENT_S3_ENDPOINT"
    try:
        parts = urlsplit(value)
        _ = parts.port  # a port that is not a number raises here
    except ValueError:
        raise ConfigError(f"{name} must be an https URL") from None
    if (
        not parts.hostname
        or any(c.isspace() for c in value)
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise ConfigError(f"{name} must be an https URL without a path, such as https://s3.example")
    if parts.scheme == "https":
        return value.rstrip("/")
    if parts.scheme != "http":
        raise ConfigError(f"{name} must be an https URL")
    if not allow_http:
        raise ConfigError(
            f"{name} is plain http: set MAITY_ATTACHMENT_S3_ALLOW_HTTP=1, or use https"
        )
    if not cluster_internal(parts.hostname):
        raise ConfigError(
            f"{name} is plain http to {parts.hostname}: http is only for a loopback or "
            "cluster-internal host"
        )
    return value.rstrip("/")


_CLUSTER_SUFFIXES = (".svc", ".svc.cluster.local", ".cluster.local")
# The private ranges a cluster or a compose network hands out (RFC 1918, the shared space of
# RFC 6598, unique local IPv6). Not `is_private`, which also counts the documentation ranges.
_CLUSTER_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
)


def cluster_internal(host: str) -> bool:
    """A host whose traffic stays on the machine or inside the cluster: a loopback or
    private address, `localhost`, a name of one label (a service in the same namespace
    or a compose network) or a Kubernetes service name. Anything that resolves through
    public DNS is not."""
    host = host.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(_CLUSTER_SUFFIXES)
    return address.is_loopback or any(address in net for net in _CLUSTER_NETWORKS)


def parse_attachment_dir(env: dict[str, str]) -> Path | None:
    """The directory of the local store: absolute, existing and writable when set (§8.7);
    unset leaves attachments unconfigured."""
    value = env.get("MAITY_ATTACHMENT_DIR", "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise ConfigError("MAITY_ATTACHMENT_DIR must be an absolute path")
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise ConfigError("MAITY_ATTACHMENT_DIR is not a writable directory")
    return path


def parse_secret_key(value: str) -> bytes | None:
    """Unset is None; anything but 32 base64 bytes stops the hub."""
    try:
        return secretbox.parse_key(value)
    except ValueError as error:
        raise ConfigError(str(error)) from None


def parse_registration(env: dict[str, str]) -> Any:
    """`registration.RegistrationEnvironment`, imported here so that loading the settings
    does not load the tables."""
    from maity_hub import registration

    try:
        return registration.parse(env)
    except registration.RegistrationConfigError as error:
        raise ConfigError(str(error)) from None


def parse_mail(env: dict[str, str]) -> MailEnvironment:
    try:
        return mail_environment.parse(env)
    except mail_environment.MailConfigError as error:
        raise ConfigError(str(error)) from None


def parse_choice(env: dict[str, str], name: str, choices: tuple[str, ...], default: str) -> str:
    """One of `choices`; unset is the default, anything else stops the hub."""
    value = env.get(name, "").strip()
    if not value:
        return default
    if value not in choices:
        raise ConfigError(f"{name} must be one of {', '.join(choices)}: {value!r}")
    return value


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


def parse_whole(env: dict[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    """A whole number within its range; unset is the default, anything else stops the hub."""
    value = env.get(name, "").strip()
    if not value:
        return default
    if not value.isdigit() or not minimum <= int(value) <= maximum:
        raise ConfigError(f"{name} must be a whole number from {minimum} to {maximum}")
    return int(value)


def parse_limit(env: dict[str, str], name: str) -> int | str | None:
    """A cap (§16.5): a whole number from 1 to 10000, or `unlimited`; an unset or empty
    variable is None, the instance admin's to decide, anything else stops the hub."""
    value = env.get(name, "").strip()
    if not value:
        return None
    if value == "unlimited":
        return value
    if not value.isdigit() or not 1 <= int(value) <= 10000:
        raise ConfigError(f"{name} must be a number from 1 to 10000, or unlimited")
    return int(value)


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


SECOND_FACTOR_POLICIES = ("off", "optional", "required_admins", "email")


def parse_second_factor(env: dict[str, str]) -> str | None:
    """Unset is None. `required_admins` without a usable instance key would hold every
    admin at an enrolment session that can do nothing, so the hub refuses to start
    (§2.8.1)."""
    value = env.get("MAITY_SIGN_IN_SECOND_FACTOR", "").strip()
    if not value:
        return None
    if value not in SECOND_FACTOR_POLICIES:
        raise ConfigError(
            "MAITY_SIGN_IN_SECOND_FACTOR must be off, optional, required_admins or email, "
            f"got {value!r}"
        )
    if value == "required_admins" and parse_secret_key(env.get("MAITY_SECRET_KEY", "")) is None:
        raise ConfigError("MAITY_SIGN_IN_SECOND_FACTOR=required_admins needs MAITY_SECRET_KEY")
    return value


def parse_switch(env: dict[str, str], name: str) -> bool | None:
    """A switch the environment may leave unset (None) for the instance admin."""
    value = env.get(name, "")
    return parse_flag(value, name) if value.strip() else None


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
    """`web/` beside `hub/` when running from a checkout, else the dashboard an installed
    package carries (`maity_hub/web`, built in by `pyproject.toml`), else nothing."""
    package = Path(__file__).resolve().parent
    hub = package.parents[1]
    if package.parent.name == "src" and (hub / "pyproject.toml").is_file():
        return hub.parent / "web"
    packaged = package / "web"
    return packaged if (packaged / "index.html").is_file() else None


_DRIVERS = {
    "postgres": "postgresql+psycopg",
    "postgresql": "postgresql+psycopg",
    "mysql": "mysql+pymysql",
    "mariadb": "mariadb+pymysql",
}


def normalize_database_url(url: str, name: str = "MAITY_DATABASE_URL") -> str:
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
            f"{name} has an '@' that is not the one before the host: "
            "an '@' in any part of the URL must be percent-encoded (%40)"
        )
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        # Never the parser's message: it quotes the text it failed on.
        raise ConfigError(f"{name} is not a valid database URL") from None
    parsed = parsed.set(drivername=_DRIVERS.get(parsed.drivername, parsed.drivername))
    return parsed.render_as_string(hide_password=False)


def redact_database_url(url: str) -> str:
    """The URL with its password masked, for messages and logs."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return "<unparseable MAITY_DATABASE_URL>"
