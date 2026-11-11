"""docs/api.md §6.1 and §11: a repository URL on any DNS host is stored and linked.

Off GitHub the hub does not probe, sends no token and does not fetch the URL.
A probe read answers `forge_not_github`.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest
from sqlalchemy import Engine, inspect

from maity_hub import forge, images, outbound, probe
from tests import flow
from tests.conftest import ClientFactory

TOKEN = "ghp_not_a_real_token"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def _stored(url: str) -> str:
    return forge.stored_repository_url(url)


def _refused(url: str) -> bool:
    with pytest.raises(forge.RepositoryURLError):
        forge.stored_repository_url(url)
    return True


def test_the_five_steps_and_the_forge_kind() -> None:
    same = "https://gitlab.com/Group/proj"
    for url in (
        "HTTPS://GitLab.com/Group/proj",
        "https://gitlab.com/Group/proj.git",
        "https://gitlab.com/Group/proj.git/",
        "https://GitLab.com/Group/proj/",
    ):
        assert _stored(url) == same
    assert forge.kind_of(same) == "gitlab"
    kept = _stored("https://github.com/Owner/Name.git/")
    assert kept == "https://github.com/Owner/Name" and forge.kind_of(kept) == "github"
    # A second trailing slash is an empty segment. `.GIT` is not the clone suffix.
    assert _refused("https://gitlab.com/Group/proj.git//")
    assert _refused("https://gitlab.com/Group/proj.GIT")
    assert _refused("https://gitlab.com/Group/proj.git.git")
    assert _refused("https://gitlab.com/Group/proj.GIT.git")


def test_what_the_checks_refuse() -> None:
    refused = [
        "http://github.com/a/b",
        "https://github.com/a",
        "https://github.com/a/b/c",
        "https://gitlab.com/only",
        "https://127.0.0.1/a/b",
        "https://10.0.0.1/a/b",
        "https://[::1]/a/b",
        "https://localhost/a/b",
        "https://git.localhost/a/b",
        "https://gitlab/a/b",
        "https://gitlab.com:443/a/b",
        "https://user@gitlab.com/a/b",
        "https://gitlab.com/a/b?x=1",
        "https://gitlab.com/a/b#x",
        "https://gitlab.com/a/%2e%2e",
        "https://gitlab.com/a/b c",
        "https://gitlab.com/a/b\n",
        "https://gitlab.com/a/b\x7f",
        "https://gitlab.com/a//b",
        "https://gitlab.com/a/.",
        "https://gitlab.com/a/..",
        "https://gitlab.com/a/b.atom",
        "https://gitlab.com/a/b.ATOM",
        "https://gitlab.com/" + "/".join(["g"] * 23),
        "https://gitlab.com/" + "a" * 256 + "/b",
        "https://bücher.example/a/b",
        "https://" + "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 62 + "/a/b",
    ]
    for url in refused:
        assert _refused(url), url
    host = "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 61
    assert len(host) == 253
    assert _stored(f"https://{host}/a/b") == f"https://{host}/a/b"
    deep = "https://gitlab.example/" + "/".join(f"g{n}" for n in range(22))
    assert _stored(deep) == deep
    assert forge.kind_of(deep) == "gitlab"


def test_forge_comes_from_the_host_alone() -> None:
    kinds = {
        "https://github.com/a/b": "github",
        "https://github.example.com/a/b": "other",
        "https://gitlab.com/a/b": "gitlab",
        "https://gitlab.corp.example/a/b/c": "gitlab",
        "https://bitbucket.org/a/b": "bitbucket",
        "https://bitbucket.example/a/b": "bitbucket",
        "https://codeberg.org/a/b": "gitea",
        "https://gitea.example/a/b": "gitea",
        "https://forgejo.example/a/b": "gitea",
        "https://git.corp.example/a/b": "other",
        "https://my-gitlab.example/a/b": "other",
    }
    for url, kind in kinds.items():
        assert forge.kind_of(_stored(url)) == kind, url


def _of_length(n: int) -> str:
    """An accepted-shape URL whose stored form has `n` characters, or one past a segment."""
    host = "zz.example"
    prefix = f"https://{host}/"
    # Fill with 200-character segments so neither the segment cap nor the 22-segment
    # cap binds before the URL cap.
    body = n - len(prefix)
    segments: list[str] = []
    left = body
    while left > 0:
        if segments:
            left -= 1  # the slash
        take = min(200, left)
        if take <= 0:
            break
        segments.append("a" * take)
        left -= take
    stored = prefix + "/".join(segments)
    assert len(stored) == n, (n, len(stored), len(segments))
    return stored


def test_2048_is_stored_and_2049_is_refused() -> None:
    exact = _of_length(2048)
    assert _stored(exact) == exact
    longer = _of_length(2049)
    assert _refused(longer)


class Outbound(Exception):
    """A test double: any real read raises, and is counted."""


def _forbid(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def refuse(name: str):
        def gone(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise Outbound(name)

        return gone

    monkeypatch.setattr(forge._opener, "open", refuse("opener"))
    monkeypatch.setattr(outbound, "read", refuse("outbound"))
    monkeypatch.setattr(socket, "create_connection", refuse("socket"))
    return calls


def test_the_hub_stores_a_non_github_url_and_never_fetches_it(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _forbid(monkeypatch)
    owner = flow.human(
        lambda **kw: make_client(
            forge_github_token=TOKEN, forge_instance_namespaces=frozenset({"maintainer"}), **kw
        ),
        migrated,
    )
    created = owner.post(
        "/projects",
        {
            "slug": "lab",
            "name": "Lab",
            "repository": {"url": "HTTPS://GitLab.corp.example/Acme/api.git/"},
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["repository"] == {
        "url": "https://gitlab.corp.example/Acme/api",
        "default_branch": "main",
        "required_check": None,
        "forge": "gitlab",
        "probe_configured": False,
        "probe_via": None,
        "owner_confirmed": False,
        "confirmed_by": None,
    }
    # The page would have been on, and the first look would have used the token.
    assert body["public_page"] == "off"
    project_id = body["id"]
    probe_read = owner.get("/projects/maintainer/lab/probe?pr=3")
    assert probe_read.status_code == 409
    assert probe_read.json()["error"]["code"] == "probe_not_configured"
    assert probe_read.json()["error"]["details"] == {"reason": "forge_not_github"}
    agent = flow.agent(make_client, owner, "lab")
    hidden = agent.get("/projects/maintainer/lab/probe?pr=3").json()["error"]
    assert (hidden["code"], hidden["details"]) == ("probe_not_configured", {})
    contract = owner.get("/projects/maintainer/lab/contract")
    assert contract.status_code == 409
    assert contract.json()["error"]["details"] == {"reason": "forge_not_github"}
    summary = owner.get("/projects/maintainer/lab/keep-the-why")
    assert summary.status_code == 409
    assert summary.json()["error"]["code"] == "ktw_not_configured"
    for path in ("/keep-the-why/export", "/keep-the-why/bodies"):
        view = owner.get(f"/projects/maintainer/lab{path}")
        assert view.status_code == 409, path
        assert view.json()["error"]["details"] == {"reason": "forge_not_github"}, path
    logo = owner.get("/projects/maintainer/lab/logo")
    assert logo.status_code == 404 and logo.headers["Maity-Error"] == "not_found"
    imported = owner.post(
        "/projects/maintainer/lab/tasks/import",
        {"issue_url": "https://github.com/acme/api/issues/3"},
    )
    assert imported.status_code == 409
    assert imported.json()["error"]["details"] == {"reason": "forge_not_github"}
    confirmed = owner.post(
        "/projects/maintainer/lab/repository/confirm",
        {"url": "https://gitlab.corp.example/Acme/api"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["repository"]["owner_confirmed"] is True
    again = owner.get("/projects/maintainer/lab/probe?pr=3")
    assert again.json()["error"]["details"] == {"reason": "forge_not_github"}
    # The worker's paths, asked directly, still do not connect.
    probe.observe_visibility(migrated, forge.Forge(TOKEN), project_id)
    images.refresh(migrated, forge.Forge(TOKEN), project_id, "logo")
    assert calls == []


def test_other_hosts_and_a_deep_path_are_stored(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    cases = [
        ("https://codeberg.org/acme/app", "gitea", "https://codeberg.org/acme/app"),
        ("https://git.corp.example/acme/app/", "other", "https://git.corp.example/acme/app"),
        ("https://github.example/acme/app", "other", "https://github.example/acme/app"),
        (
            "https://gitlab.example/" + "/".join(f"g{n}" for n in range(22)),
            "gitlab",
            "https://gitlab.example/" + "/".join(f"g{n}" for n in range(22)),
        ),
    ]
    for number, (url, kind, stored) in enumerate(cases):
        response = owner.post(
            "/projects",
            {"slug": f"h{number}", "name": "H", "repository": {"url": url}, "public_page": "off"},
        )
        assert response.status_code == 201, response.text
        repository = response.json()["repository"]
        assert repository["url"] == stored and repository["forge"] == kind
        assert repository["probe_configured"] is False and repository["probe_via"] is None


def test_the_downgrade_refuses_a_url_the_old_column_cannot_hold(
    owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub.db import current_revision, downgrade

    url = _of_length(300)
    response = owner.post(
        "/projects",
        {"slug": "long", "name": "L", "repository": {"url": url}, "public_page": "off"},
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["repository"]["url"]) == 300
    with pytest.raises(RuntimeError, match="longer than 255"):
        downgrade(migrated, "20261109200000_invite_by_handle")
    assert current_revision(migrated) == "20261111120000_repo_url_2048"


def test_the_column_holds_2048_characters(migrated: Engine) -> None:
    column = next(
        c for c in inspect(migrated).get_columns("project") if c["name"] == "repository_url"
    )
    assert column["type"].length == 2048


def test_a_refused_url_names_not_a_repository_url(owner: flow.Human) -> None:
    response = owner.post(
        "/projects",
        {"slug": "nope", "name": "N", "repository": {"url": "https://127.0.0.1/a/b"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {
        "repository.url": "not_a_repository_url"
    }
