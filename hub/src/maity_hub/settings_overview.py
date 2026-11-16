"""The instance admin's read-only overview of the hub's settings (docs/api.md §16.14): every
`MAITY_*` setting the hub reads, with the value in effect and where it came from, a secret only
as set or not set. The values are the environment this process read at its start
(`Settings.environment`); the hub reads it nowhere else, so this is what runs now.

`ENTRIES` names every setting once. A test reads every `"MAITY_…"` name in the hub's code and
fails on one that is neither here nor in `NOT_LISTED`, so a new setting cannot be left out."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from maity_hub import limits, registration
from maity_hub.config import (
    DEFAULT_BIND,
    DEFAULT_CLI_INSTALL,
    KTW_SKILL_GUIDE,
    KTW_SKILL_SOURCE,
    Settings,
)
from maity_hub.mail import settings as mail_settings
from maity_hub.mail.environment import DEFAULT_PORTS

# The groups in the order of the answer (§16.14).
GROUPS = (
    "address",
    "database",
    "processes",
    "security",
    "sign_in",
    "registration",
    "mail",
    "agents",
    "limits",
    "attachments",
    "public_pages",
    "forge",
)

# The dashboard sections where the instance admin sets the same value (§16.14 `admin`).
SIGN_IN, MAIL, REGISTRATION, LIMITS = "2.6.6", "16.2", "16.4", "16.5"

# The page that describes every setting, a path in the repository.
DOCS = "hub/README.md#configuration"

Default = str | None | Callable[[Settings, Mapping[str, str]], str | None]


@dataclass(frozen=True)
class Entry:
    name: str
    group: str
    # The hub's default in the environment's notation, a function for a derived one, None
    # when unset means off or empty. Never read for a secret.
    default: Default = None
    secret: bool = False
    admin: str | None = None


# Names the hub reads that are not settings of the overview, each with its reason. Empty today:
# every `MAITY_*` name in the hub's code is a setting an admin should see.
NOT_LISTED: dict[str, str] = {}


def _public_url(settings: Settings, _env: Mapping[str, str]) -> str:
    return settings.public_url


def _web_dir(settings: Settings, _env: Mapping[str, str]) -> str | None:
    return str(settings.web_dir) if settings.web_dir is not None else None


def _async_pool(settings: Settings, _env: Mapping[str, str]) -> str:
    # serving.pool_shares: unset, DEFAULT_ASYNC_POOL but at most half the pool.
    from maity_hub.serving import DEFAULT_ASYNC_POOL

    return str(max(min(DEFAULT_ASYNC_POOL, settings.db_pool_size // 2), 1))


def _smtp_port(_settings: Settings, env: Mapping[str, str]) -> str:
    tls = env.get("MAITY_SMTP_TLS") or str(mail_settings.DEFAULTS["tls"])
    return str(DEFAULT_PORTS.get(tls, DEFAULT_PORTS["starttls"]))


def _mail(field: str) -> str:
    return str(mail_settings.DEFAULTS[field])


def _limit(field: str) -> str:
    return str(limits.DEFAULTS[field])


ENTRIES: tuple[Entry, ...] = (
    # address
    Entry("MAITY_BIND", "address", DEFAULT_BIND),
    Entry("MAITY_PUBLIC_URL", "address", _public_url),
    Entry("MAITY_JOIN_URL", "address"),
    Entry("MAITY_TRUSTED_PROXIES", "address"),
    Entry("MAITY_ALLOW_PLAIN_HTTP", "address", "0"),
    Entry("MAITY_HSTS_MAX_AGE", "address", "31536000"),
    Entry("MAITY_WEB_DIR", "address", _web_dir),
    Entry("MAITY_CLI_INSTALL", "address", DEFAULT_CLI_INSTALL),
    # database: both URLs can carry a password
    Entry("MAITY_DATABASE_URL", "database", secret=True),
    Entry("MAITY_DIRECT_DATABASE_URL", "database", secret=True),
    Entry("MAITY_DB_POOL_SIZE", "database", "16"),
    Entry("MAITY_DB_MAX_OVERFLOW", "database", "16"),
    Entry("MAITY_DB_ASYNC_POOL_SIZE", "database", _async_pool),
    Entry("MAITY_DB_POOL_RECYCLE", "database", "1800"),
    Entry("MAITY_DB_STATEMENT_TIMEOUT", "database", "30"),
    Entry("MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT", "database", "60"),
    # processes
    Entry("MAITY_WORKERS", "processes", "1"),
    Entry("MAITY_REPLICAS", "processes", "1"),
    # security
    Entry("MAITY_SECRET_KEY", "security", secret=True),
    Entry("MAITY_SEAL_VERIFIERS", "security", "0"),
    Entry("MAITY_SECOND_FACTOR_WRONG_PER_DAY", "security", "50"),
    # sign_in: unset, the admin's choice or the hub's default (§2.6.6)
    Entry("MAITY_SIGN_IN_DEVICE_CODE", "sign_in", "1", admin=SIGN_IN),
    Entry("MAITY_SIGN_IN_EMAIL_LINK", "sign_in", "1", admin=SIGN_IN),
    Entry("MAITY_SIGN_IN_PASSWORD_RESET", "sign_in", "1", admin=SIGN_IN),
    Entry("MAITY_SIGN_IN_SECOND_FACTOR", "sign_in", "optional", admin=SIGN_IN),
    # registration
    Entry("MAITY_REGISTRATION", "registration", "closed", admin=REGISTRATION),
    Entry("MAITY_REGISTRATION_DOMAINS", "registration", admin=REGISTRATION),
    Entry("MAITY_REGISTRATION_ADDRESSES", "registration", admin=REGISTRATION),
    Entry(
        "MAITY_REGISTRATION_APPROVAL",
        "registration",
        str(registration.DEFAULTS["approval"]),
        admin=REGISTRATION,
    ),
    Entry(
        "MAITY_REGISTRATION_MAX_NEW_PER_HOUR",
        "registration",
        str(registration.DEFAULTS["max_new_accounts_per_hour"]),
        admin=REGISTRATION,
    ),
    Entry("MAITY_REGISTRATION_BREAKER", "registration", str(registration.BREAKER_DEFAULT)),
    Entry("MAITY_TERMS_URL", "registration", admin=REGISTRATION),
    Entry("MAITY_TERMS_VERSION", "registration", admin=REGISTRATION),
    # mail: the user name and the password (and the file holding it) are secret
    Entry("MAITY_SMTP_HOST", "mail", admin=MAIL),
    Entry("MAITY_SMTP_PORT", "mail", _smtp_port, admin=MAIL),
    Entry("MAITY_SMTP_TLS", "mail", _mail("tls"), admin=MAIL),
    Entry("MAITY_SMTP_ALLOW_PLAINTEXT", "mail", "0"),
    Entry("MAITY_SMTP_CA_FILE", "mail"),
    Entry("MAITY_SMTP_USERNAME", "mail", secret=True, admin=MAIL),
    Entry("MAITY_SMTP_PASSWORD", "mail", secret=True, admin=MAIL),
    Entry("MAITY_SMTP_PASSWORD_FILE", "mail", secret=True, admin=MAIL),
    Entry("MAITY_SMTP_FROM", "mail", admin=MAIL),
    Entry("MAITY_SMTP_REPLY_TO", "mail", admin=MAIL),
    Entry("MAITY_MAIL_MAX_PER_HOUR", "mail", _mail("max_per_hour"), admin=MAIL),
    Entry("MAITY_MAIL_SECURITY_MAX_PER_HOUR", "mail", _mail("security_max_per_hour"), admin=MAIL),
    Entry("MAITY_MAIL_SIGN_IN_MAX_PER_HOUR", "mail", _mail("sign_in_max_per_hour"), admin=MAIL),
    Entry(
        "MAITY_MAIL_PASSWORD_RESET_MAX_PER_HOUR",
        "mail",
        _mail("password_reset_max_per_hour"),
        admin=MAIL,
    ),
    Entry(
        "MAITY_MAIL_REGISTRATION_MAX_PER_HOUR",
        "mail",
        _mail("registration_max_per_hour"),
        admin=MAIL,
    ),
    Entry("MAITY_MAIL_ONLINE_GRACE_MINUTES", "mail", _mail("online_grace_minutes"), admin=MAIL),
    Entry("MAITY_MAIL_SIGNING_KEY", "mail", secret=True),
    # agents
    Entry("MAITY_AGENT_FIREWALL", "agents", "off"),
    Entry("MAITY_ON_RUNNER_REVOKE", "agents", "keep"),
    Entry("MAITY_KTW_SKILL_SOURCE", "agents", KTW_SKILL_SOURCE),
    Entry("MAITY_KTW_SKILL_GUIDE", "agents", KTW_SKILL_GUIDE),
    # limits
    Entry("MAITY_MAX_AGENTS_PER_HUMAN", "limits", _limit("max_agents_per_human"), admin=LIMITS),
    Entry("MAITY_MAX_ORGS_PER_HUMAN", "limits", _limit("max_orgs_per_human"), admin=LIMITS),
    Entry("MAITY_MAX_PROJECTS_PER_OWNER", "limits", _limit("max_projects_per_owner"), admin=LIMITS),
    Entry("MAITY_MAX_ALIASES", "limits", _limit(limits.ALIASES), admin=LIMITS),
    Entry(
        "MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT",
        "limits",
        _limit(limits.PROJECT_STORAGE),
        admin=LIMITS,
    ),
    Entry("MAITY_MAX_ATTACHMENT_STORAGE", "limits", _limit(limits.STORAGE), admin=LIMITS),
    Entry("MAITY_ROUTE_LIMITS", "limits"),
    Entry("MAITY_PUBLIC_PAGE_LIMIT", "limits", "60/60"),
    Entry("MAITY_BADGE_LIMIT", "limits", "60/60"),
    Entry("MAITY_AVATAR_DECODE_SECONDS", "limits", "5"),
    Entry("MAITY_AVATAR_DECODE_MEMORY_MB", "limits", "512"),
    Entry("MAITY_AVATAR_DECODES", "limits", "2"),
    # attachments: the endpoint can carry credentials, the keys are credentials
    Entry("MAITY_ATTACHMENT_STORE", "attachments", "local"),
    Entry("MAITY_ATTACHMENT_DIR", "attachments"),
    Entry("MAITY_ATTACHMENT_S3_BUCKET", "attachments"),
    Entry("MAITY_ATTACHMENT_S3_ENDPOINT", "attachments", secret=True),
    Entry("MAITY_ATTACHMENT_S3_REGION", "attachments"),
    Entry("MAITY_ATTACHMENT_S3_PREFIX", "attachments"),
    Entry("MAITY_ATTACHMENT_S3_ALLOW_HTTP", "attachments", "0"),
    Entry("MAITY_ATTACHMENT_S3_ACCESS_KEY_ID", "attachments", secret=True),
    Entry("MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY", "attachments", secret=True),
    # public_pages
    Entry("MAITY_PUBLIC_PAGES", "public_pages", "off"),
    Entry("MAITY_PUBLIC_PAGES_RENDER", "public_pages", "on_change"),
    Entry("MAITY_PUBLIC_PAGES_INTERVAL_HOURS", "public_pages", "6"),
    Entry("MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES", "public_pages", "5"),
    Entry("MAITY_PUBLIC_PAGES_STARTUP_SECONDS", "public_pages", "30"),
    Entry("MAITY_PUBLIC_PAGES_RENDER_SECONDS", "public_pages", "2"),
    # forge: the token, the App's client id and secret and its private key are secret
    Entry("MAITY_FORGE_GITHUB_TOKEN", "forge", secret=True),
    Entry("MAITY_FORGE_INSTANCE_NAMESPACES", "forge"),
    Entry("MAITY_FORGE_GITHUB_APP_ID", "forge"),
    Entry("MAITY_FORGE_GITHUB_APP_SLUG", "forge"),
    Entry("MAITY_FORGE_GITHUB_APP_CLIENT_ID", "forge", secret=True),
    Entry("MAITY_FORGE_GITHUB_APP_CLIENT_SECRET", "forge", secret=True),
    Entry("MAITY_FORGE_GITHUB_APP_PRIVATE_KEY", "forge", secret=True),
)


def _entry(entry: Entry, settings: Settings, env: Mapping[str, str]) -> dict[str, Any]:
    raw = env.get(entry.name)
    row: dict[str, Any] = {
        "name": entry.name,
        "group": entry.group,
        "source": "environment" if raw else "default",
    }
    if entry.secret:
        # Never the value, nor a default: a secret is only there or not.
        row |= {"value": None, "secret": True, "set": bool(raw)}
    else:
        default = entry.default(settings, env) if callable(entry.default) else entry.default
        row |= {"value": raw if raw else default, "secret": False}
    row["admin"] = entry.admin
    return row


def settings_list(settings: Settings) -> list[dict[str, Any]]:
    """§16.14 `settings`: ordered by group, then by name."""
    env = dict(settings.environment)
    order = {group: i for i, group in enumerate(GROUPS)}
    entries = sorted(ENTRIES, key=lambda e: (order[e.group], e.name))
    return [_entry(entry, settings, env) for entry in entries]
