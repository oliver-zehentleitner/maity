"""docs/api.md §11.4: the instance token serves the operator's own namespaces only
(`MAITY_FORGE_INSTANCE_NAMESPACES`), and a listed name nobody has is held for the operator.

The forge's answers (`Forge._send`) are faked; the choice of the source, the first look at a
new project's repository and the handle checks run for real.
"""

from __future__ import annotations

import io
import logging
from collections import OrderedDict
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import config, forge, forge_access, handles, registration_accounts
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory

OPERATOR = "operator-token"
OWN = frozenset({"maintainer", "acme-org"})  # the owner's handle and an organisation not yet made
URL = "https://github.com/maintainer-gh/thing"
REPO = "maintainer-gh/thing"


class FakeForge:
    """A public repository; every request is noted with the token it carried."""

    def __init__(self) -> None:
        self.sent: list[tuple[str | None, str]] = []

    def send(self, fg: forge.Forge, path: str, query: Any = None) -> Any:
        self.sent.append((fg.token, path))
        if path == f"/repos/{REPO}":
            return {"private": False, "full_name": REPO}
        return None


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    fg = FakeForge()
    monkeypatch.setattr(
        forge.Forge, "_send", lambda self, path, query=None: fg.send(self, path, query)
    )
    monkeypatch.setattr(forge, "_public", {})
    monkeypatch.setattr(forge_access, "_last_via", OrderedDict())
    return fg


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, forge_github_token=OPERATOR, forge_instance_namespaces=OWN)


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def _reader(engine: Engine, own: frozenset[str] = OWN) -> forge.Forge:
    access = forge_access.ForgeAccess(engine, None, None, own)
    return forge.Forge(OPERATOR, access=access).for_project(_project_id(engine))


# --- the setting ---------------------------------------------------------------------------


def test_the_list_is_comma_separated_trimmed_and_lower_case() -> None:
    assert config.parse_namespaces(" Maintainer , ,acme-org,") == frozenset(
        {"maintainer", "acme-org"}
    )
    assert config.parse_namespaces("") == frozenset()
    env = {"MAITY_FORGE_INSTANCE_NAMESPACES": "oliver-zehentleitner"}
    assert config.parse_namespaces(env["MAITY_FORGE_INSTANCE_NAMESPACES"]) == frozenset(
        {"oliver-zehentleitner"}
    )


# --- which projects the instance token reads for ---------------------------------------


def test_a_listed_namespace_is_read_with_the_instance_token(
    make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "thing", repository={"url": URL})
    reader = _reader(migrated)
    assert (reader.via, reader.token, reader.refused) == ("instance", OPERATOR, None)
    shown = owner.get("/projects/maintainer/thing").json()["repository"]
    assert shown["probe_via"] == "instance" and shown["probe_configured"] is True


def test_any_other_namespace_is_not_read_at_all(
    make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    """Unlisted: the reader refuses with `no_grant` and asks the forge nothing, not even
    whether the repository is public."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, "thing", repository={"url": URL})
    reader = _reader(migrated, frozenset({"someone-else"}))
    assert (reader.token, reader.refused) == (None, "no_grant")
    with pytest.raises(forge.NotCoveredError) as raised:
        reader.branch(REPO, "main")
    assert raised.value.reason == "no_grant"
    assert fake.sent == []


def test_an_unset_list_serves_no_project(
    make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "thing", repository={"url": URL})
    assert _reader(migrated, frozenset()).refused == "no_grant"
    assert fake.sent == []


def test_the_view_shows_no_instance_source_for_an_unlisted_namespace(
    make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    owner = flow.human(make_client, migrated, "outsider")
    flow.project(owner, "thing", repository={"url": URL})
    shown = owner.get("/projects/outsider/thing").json()["repository"]
    assert (shown["probe_via"], shown["probe_configured"]) == (None, False)


def test_a_rename_out_of_the_list_takes_the_project_out_at_once(
    make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "thing", repository={"url": URL})
    access = forge_access.ForgeAccess(migrated, None, None, OWN)
    base = forge.Forge(OPERATOR, access=access)
    assert base.for_project(_project_id(migrated)).via == "instance"
    assert owner.patch("/me", {"handle": "renamed"}).status_code == 200
    # Within the ten minutes the choice is kept: the namespace is part of what it depends on.
    assert base.for_project(_project_id(migrated)).refused == "no_grant"


# --- the first look at a new project's repository (§6.1, §16.9) ----------------------------


def test_a_new_project_outside_the_list_starts_private_without_a_look(
    make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    owner = flow.human(make_client, migrated, "outsider")
    made = owner.post(
        "/projects", {"slug": "thing", "name": "Thing", "repository": {"url": URL}}
    ).json()
    assert made["public_page"] == "off"
    assert fake.sent == []


def test_a_new_project_in_the_list_is_looked_at_and_stays_public(
    make_client: ClientFactory, migrated: Engine, fake: FakeForge
) -> None:
    owner = flow.human(make_client, migrated)
    made = owner.post(
        "/projects", {"slug": "thing", "name": "Thing", "repository": {"url": URL}}
    ).json()
    assert made["public_page"] == "on"
    assert fake.sent == [(OPERATOR, f"/repos/{REPO}")]


# --- a listed name nobody has is held for the operator ------------------------------------


def test_a_held_name_is_refused_at_registration_an_organisation_and_a_rename(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    with migrated.begin() as conn:
        assert registration_accounts.check_names(conn, "acme-org", "Acme") == {"handle": "reserved"}
        assert registration_accounts.check_names(conn, "free-name", "Free") == {}
    refused = owner.post("/orgs", {"handle": "acme-org", "display_name": "Acme"})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"handle": "reserved"}
    renamed = owner.patch("/me", {"handle": "acme-org"})
    assert renamed.status_code == 400, renamed.text
    assert renamed.json()["error"]["details"]["fields"] == {"handle": "reserved"}
    assert owner.post("/orgs", {"handle": "free-org", "display_name": "Free"}).status_code == 201


def test_an_alias_is_not_held_and_its_id_takes_it_back(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    with migrated.begin() as conn:
        assert not handles.held_for_instance(conn, "maintainer")  # boss's alias now
    back = owner.patch("/me", {"handle": "maintainer"})
    assert back.status_code == 200, back.text


def test_an_agent_profile_handle_is_not_checked_against_the_list(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    with migrated.begin() as conn:
        handles.ensure_free(conn, owner.id, "acme-org")  # an agent's scope: no address


def test_the_operators_owner_create_may_take_a_listed_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from maity_hub.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAITY_DATABASE_URL", "sqlite:///maity-hub.db")
    monkeypatch.setenv("MAITY_FORGE_INSTANCE_NAMESPACES", "acme-org")
    monkeypatch.setattr(handles, "_instance_names", frozenset({"acme-org"}))
    assert main(["migrate"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("a long password\n"))
    assert main(["owner", "create", "--handle", "acme-org", "--display-name", "Acme"]) == 0


def test_the_start_names_held_and_former_names(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    owner = flow.human(make_client, migrated)
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200  # maintainer: an alias
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="maity_hub.app"):
        make_client()
    warned = [r.getMessage() for r in caplog.records if "INSTANCE_NAMESPACES" in r.getMessage()]
    assert len(warned) == 2
    assert "'acme-org', which nobody has" in warned[0]
    assert "'maintainer', a former name" in warned[1]
