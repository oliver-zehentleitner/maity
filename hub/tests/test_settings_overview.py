"""docs/api.md §16.14: the instance admin's read-only overview of the hub's settings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import settings_overview
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_orgs import make_org

PATH = "/admin/instance"
SRC = Path(__file__).resolve().parents[1] / "src" / "maity_hub"
README = Path(__file__).resolve().parents[1] / "README.md"

# A value for every secret, each a string no other part of an answer could hold by chance.
# The credentials the contract names (§16.14), written out here rather than read from the
# entries' flags, so that an entry that lost its flag is still given a marker and caught
# (A899 N1). A value for each, a string no other part of an answer could hold by chance.
SECRET_NAMES = (
    "MAITY_ATTACHMENT_S3_ACCESS_KEY_ID",
    "MAITY_ATTACHMENT_S3_ENDPOINT",
    "MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY",
    "MAITY_DATABASE_URL",
    "MAITY_DIRECT_DATABASE_URL",
    "MAITY_FORGE_GITHUB_APP_CLIENT_ID",
    "MAITY_FORGE_GITHUB_APP_CLIENT_SECRET",
    "MAITY_FORGE_GITHUB_APP_PRIVATE_KEY",
    "MAITY_FORGE_GITHUB_TOKEN",
    "MAITY_MAIL_SIGNING_KEY",
    "MAITY_SECRET_KEY",
    "MAITY_SMTP_PASSWORD",
    "MAITY_SMTP_PASSWORD_FILE",
    "MAITY_SMTP_USERNAME",
)
SECRETS = {name: f"s3cr3t-{name.lower()}-x9q" for name in SECRET_NAMES}


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin: the earliest account."""
    return flow.human(make_client, migrated)


def by_name(answer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in answer["settings"]}


def test_the_version_the_schema_and_every_setting(admin: flow.Human) -> None:
    got = admin.get(PATH)
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == "no-store"  # settings are never kept by a cache (§1.1)
    body = got.json()
    assert set(body) == {"version", "schema", "settings", "docs"}
    assert body["docs"] == "hub/README.md#configuration"
    health = admin.get("/health").json()
    assert body["version"] == health["version"]
    assert body["schema"] == {
        "revision": health["database"]["revision"],
        "head": health["database"]["head"],
    }
    names = [row["name"] for row in body["settings"]]
    assert sorted(names) == sorted(e.name for e in settings_overview.ENTRIES)
    # ordered by group in the contract's order, then by name
    order = settings_overview.GROUPS
    keys = [(order.index(row["group"]), row["name"]) for row in body["settings"]]
    assert keys == sorted(keys)


def test_the_defaults_without_an_environment(
    make_client: ClientFactory, migrated: Engine, settings: Settings
) -> None:
    who = flow.human(lambda **kw: make_client(environment=(), **kw), migrated)
    rows = by_name(who.get(PATH).json())
    assert all(row["source"] == "default" for row in rows.values())
    assert rows["MAITY_AGENT_FIREWALL"] == {
        "name": "MAITY_AGENT_FIREWALL",
        "group": "agents",
        "source": "default",
        "value": "off",
        "secret": False,
        "admin": None,
    }
    assert rows["MAITY_REGISTRATION"]["value"] == "closed"
    assert rows["MAITY_REGISTRATION"]["admin"] == "16.4"
    assert rows["MAITY_MAX_ATTACHMENT_STORAGE"]["value"] == "unlimited"
    assert rows["MAITY_SMTP_PORT"]["value"] == "587"
    assert rows["MAITY_JOIN_URL"]["value"] is None
    # a derived default: the public URL the hub uses
    assert rows["MAITY_PUBLIC_URL"]["value"] == settings.public_url
    assert rows["MAITY_SECRET_KEY"] == {
        "name": "MAITY_SECRET_KEY",
        "group": "security",
        "source": "default",
        "value": None,
        "secret": True,
        "set": False,
        "admin": None,
    }


def test_what_the_environment_sets(make_client: ClientFactory, migrated: Engine) -> None:
    env = {
        "MAITY_AGENT_FIREWALL": "on",
        "MAITY_SMTP_TLS": "implicit",
        "MAITY_DB_POOL_SIZE": "24",
        "MAITY_REGISTRATION": "",  # empty is unset
    }
    who = flow.human(
        lambda **kw: make_client(environment=Settings.from_env(env).environment, **kw), migrated
    )
    rows = by_name(who.get(PATH).json())
    assert rows["MAITY_AGENT_FIREWALL"]["source"] == "environment"
    assert rows["MAITY_AGENT_FIREWALL"]["value"] == "on"
    assert rows["MAITY_DB_POOL_SIZE"]["value"] == "24"
    assert rows["MAITY_SMTP_TLS"]["value"] == "implicit"
    # the port's default follows the TLS mode
    assert rows["MAITY_SMTP_PORT"]["source"] == "default"
    assert rows["MAITY_SMTP_PORT"]["value"] == "465"
    assert rows["MAITY_REGISTRATION"]["source"] == "default"


def test_no_secret_ever_appears(make_client: ClientFactory, migrated: Engine) -> None:
    env = dict(SECRETS)
    env["MAITY_DATABASE_URL"] = "postgresql://maity:s3cr3t-pw-x9q@db.internal:5432/maity"
    env["MAITY_DIRECT_DATABASE_URL"] = "postgresql://maity:s3cr3t-pw-x9q@db-direct.internal/maity"
    env["MAITY_ATTACHMENT_S3_ENDPOINT"] = "https://key:s3cr3t-pw-x9q@s3.internal"
    environment = tuple(sorted(env.items()))
    who = flow.human(lambda **kw: make_client(environment=environment, **kw), migrated)
    got = who.get(PATH)
    assert got.status_code == 200, got.text
    for value in env.values():
        assert value not in got.text
    for part in ("s3cr3t", "db.internal", "db-direct.internal", "s3.internal", "maity:"):
        assert part not in got.text
    rows = by_name(got.json())
    for name in env:
        assert rows[name]["secret"] is True, name
        assert rows[name]["value"] is None, name
        assert rows[name]["set"] is True, name
        assert rows[name]["source"] == "environment", name
    # the file a password is read from is as secret as the password
    assert rows["MAITY_SMTP_PASSWORD_FILE"]["secret"] is True


def test_the_contracts_credentials_are_the_secret_entries() -> None:
    assert {e.name for e in settings_overview.ENTRIES if e.secret} == set(SECRET_NAMES)


def test_every_name_with_a_credential_is_secret() -> None:
    """When in doubt, secret: a name that says it holds a credential or a URL that can carry
    one is never shown (§16.14)."""
    shown_urls = {
        "MAITY_PUBLIC_URL",
        "MAITY_JOIN_URL",
        "MAITY_TERMS_URL",
        "MAITY_KTW_SKILL_SOURCE",
        "MAITY_KTW_SKILL_GUIDE",
    }
    credential = re.compile(
        r"_KEY$|_KEY_ID$|SECRET|_PASSWORD(_FILE)?$|TOKEN|USERNAME|CLIENT_ID|DATABASE_URL|ENDPOINT"
    )
    for entry in settings_overview.ENTRIES:
        if credential.search(entry.name):
            assert entry.secret, entry.name
        if entry.name.endswith(("_URL", "_SOURCE", "_GUIDE")) and not entry.secret:
            assert entry.name in shown_urls, entry.name
        if entry.secret:
            assert entry.default is None, entry.name


def test_only_the_instance_admin_reads_it(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human
) -> None:
    other = flow.human(make_client, migrated, "other")
    assert other.get(PATH).status_code == 403
    # owning an organisation (its admin) makes no instance admin
    make_org(other, "other-org", "Other Org")
    assert other.get(PATH).status_code == 403
    flow.project(admin, "maity")
    bot = flow.agent(make_client, admin, role="admin")
    # an agent is refused as on every other human-only admin route (§16.1)
    assert bot.get(PATH).status_code == bot.get("/admin/settings/sign-in").status_code
    assert bot.get(PATH).status_code == 403


def _names_in_code() -> set[str]:
    """Every `"MAITY_…"` literal of the hub's code but the overview's own list, which names
    them and reads none: an entry must have a reader elsewhere (A899 N2)."""
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        if path.name == "settings_overview.py":
            continue
        names |= set(re.findall(r"[\"'](MAITY_[A-Z0-9_]+)", path.read_text(encoding="utf-8")))
    return names


def test_every_setting_the_hub_reads_is_listed() -> None:
    """A new `MAITY_*` setting must appear in the overview, or in `NOT_LISTED` with a reason."""
    listed = {e.name for e in settings_overview.ENTRIES}
    assert len(listed) == len(settings_overview.ENTRIES), "a setting is listed twice"
    found = _names_in_code()
    missing = found - listed - set(settings_overview.NOT_LISTED)
    assert not missing, f"read by the hub but not in settings_overview.ENTRIES: {sorted(missing)}"
    stale = (listed | set(settings_overview.NOT_LISTED)) - found
    assert not stale, f"listed but read nowhere in the hub: {sorted(stale)}"
    assert all(reason.strip() for reason in settings_overview.NOT_LISTED.values())
    assert {e.group for e in settings_overview.ENTRIES} <= set(settings_overview.GROUPS)


def test_every_setting_is_described_where_the_overview_points() -> None:
    text = README.read_text(encoding="utf-8").split("## Configuration", 1)[1].split("\n## ", 1)[0]
    for entry in settings_overview.ENTRIES:
        assert f"`{entry.name}`" in text, f"{entry.name} is not in hub/README.md, Configuration"


def test_spaces_count_as_the_parsers_count_them(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Set exactly when the hub runs with it: a password of only spaces is set (the hub takes
    the SMTP password as written), a key or a switch of only spaces or a newline is not (their
    parsers trim) (§16.14; A895 N1, A899 P2, A904)."""
    env = {
        "MAITY_SIGN_IN_DEVICE_CODE": "   ",
        "MAITY_SMTP_PASSWORD": "   ",
        "MAITY_SECRET_KEY": "\n",
        "MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY": " ",
        "MAITY_SMTP_USERNAME": "   ",
        "MAITY_FORGE_GITHUB_TOKEN": " ",
        "MAITY_AGENT_FIREWALL": " on ",
    }
    loaded = Settings.from_env(env)
    assert loaded.secret_key is None and loaded.mail.username is None
    assert loaded.mail.password == "   " and loaded.forge_github_token == " "
    who = flow.human(lambda **kw: make_client(environment=loaded.environment, **kw), migrated)
    rows = by_name(who.get(PATH).json())
    assert rows["MAITY_SIGN_IN_DEVICE_CODE"]["source"] == "default"
    assert rows["MAITY_SIGN_IN_DEVICE_CODE"]["value"] == "1"
    assert rows["MAITY_SMTP_PASSWORD"]["set"] is True
    assert rows["MAITY_SMTP_PASSWORD"]["source"] == "environment"
    assert rows["MAITY_SMTP_PASSWORD"]["value"] is None
    assert rows["MAITY_FORGE_GITHUB_TOKEN"]["set"] is True
    for name in (
        "MAITY_SECRET_KEY",
        "MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY",
        "MAITY_SMTP_USERNAME",
    ):
        assert rows[name]["set"] is False, name
        assert rows[name]["source"] == "default", name
    assert rows["MAITY_AGENT_FIREWALL"]["value"] == "on"


# A setting read only in a mode (the S3 credentials, under MAITY_ATTACHMENT_STORE=s3) is
# probed with that mode set too, or the binding below would never see its reader (A911 N1).
MODE_BASES: tuple[dict[str, str], ...] = (
    {},
    {
        "MAITY_ATTACHMENT_STORE": "s3",
        "MAITY_ATTACHMENT_S3_BUCKET": "maity",
        "MAITY_ATTACHMENT_S3_ENDPOINT": "https://s3.example",
        "MAITY_ATTACHMENT_S3_ACCESS_KEY_ID": "key-id",
        "MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY": "secret",
    },
)


def _loaded(env: dict[str, str]) -> object:
    """What the hub makes of an environment: its settings, or the error that stops it."""
    try:
        return Settings.from_env(env)
    except ValueError as error:  # ConfigError and the mail, registration and App errors
        return (type(error), str(error))


def test_as_written_is_what_the_parsers_do() -> None:
    """`as_written` is bound to the hub's own parsers: a setting of only spaces changes what
    `Settings.from_env` loads (or how it stops) exactly for the entries marked so, in every
    mode that reads it, so a new setting read as written cannot be shown unset while the hub
    runs with it (A904, A911 N1)."""
    taken = set()
    for base in MODE_BASES:
        for entry in settings_overview.ENTRIES:
            without = {k: v for k, v in base.items() if k != entry.name}
            if _loaded({**without, entry.name: "  "}) != _loaded(without):
                taken.add(entry.name)
    assert taken == {e.name for e in settings_overview.ENTRIES if e.as_written}
