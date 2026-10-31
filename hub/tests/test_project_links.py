"""docs/api.md §6.11, "The project's own links", and §16.9: four links set under project:admin,
merged by key, checked as a person's website is; on a public page, a link into the repository's
own path only while the repository is public."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import project_links
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
ISSUES = "https://github.com/acme/maity/issues"
CHAT = "https://discord.gg/abc123"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(lambda **kw: make_client(public_pages=True, **kw), migrated)
    flow.project(human, "maity", repository={"url": "https://github.com/acme/maity"})
    return human


def links_of(who: Any) -> dict[str, Any]:
    got = who.get(PROJECT)
    assert got.status_code == 200, got.text
    links: dict[str, Any] = got.json()["links"]
    return links


def link_events(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        rows = conn.execute(select(t.event).where(t.event.c.kind == "project_updated")).all()
    return [r.payload["fields"] for r in rows if "links" in r.payload["fields"]]


def test_a_project_has_four_empty_links_until_an_admin_sets_them(owner: flow.Human) -> None:
    assert links_of(owner) == {"issues": None, "wiki": None, "discussions": None, "chat": None}


def test_links_merge_by_key_and_null_clears_one_or_all(owner: flow.Human) -> None:
    done = owner.patch(PROJECT, {"links": {"issues": ISSUES, "chat": CHAT}})
    assert done.status_code == 200, done.text
    assert done.json()["links"] == {
        "issues": ISSUES,
        "wiki": None,
        "discussions": None,
        "chat": CHAT,
    }
    # a key left out stays, a key given null clears it
    owner.patch(PROJECT, {"links": {"chat": None, "wiki": "https://wiki.example.org/maity"}})
    assert links_of(owner) == {
        "issues": ISSUES,
        "wiki": "https://wiki.example.org/maity",
        "discussions": None,
        "chat": None,
    }
    assert owner.patch(PROJECT, {"links": None}).status_code == 200
    assert links_of(owner) == {"issues": None, "wiki": None, "discussions": None, "chat": None}


def test_a_change_emits_one_project_updated_and_an_unchanged_patch_none(
    owner: flow.Human, migrated: Engine
) -> None:
    owner.patch(PROJECT, {"links": {"issues": ISSUES}})
    owner.patch(PROJECT, {"links": {"issues": ISSUES}})  # the same again
    owner.patch(PROJECT, {"links": {}})  # nothing named
    assert link_events(migrated) == [{"links": True}]  # where they point is read from the project


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/acme/maity/issues",  # not https
        "https://user@github.com/acme/maity/issues",  # a user part
        "https://github.com:8443/acme/maity",  # a port
        "https://127.0.0.1/issues",  # an IP literal
        "https://localhost/issues",  # no DNS name
        "https://github.com/acme maity",  # whitespace
        "https://github.com/acme/\u0007",  # a control character
        "issues",  # not absolute
        42,  # not text
    ],
)
def test_a_link_not_of_the_website_form_is_format(owner: flow.Human, value: Any) -> None:
    refused = owner.patch(PROJECT, {"links": {"issues": value}})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"links.issues": "format"}


def test_a_link_over_500_characters_is_too_long_and_500_are_fine(owner: flow.Human) -> None:
    base = "https://wiki.example.org/"
    fine = base + "a" * (500 - len(base))
    assert owner.patch(PROJECT, {"links": {"wiki": fine}}).status_code == 200
    refused = owner.patch(PROJECT, {"links": {"wiki": fine + "a"}})
    assert refused.json()["error"]["details"]["fields"] == {"links.wiki": "too_long"}


def test_an_unknown_key_and_a_links_that_is_no_object_are_refused(owner: flow.Human) -> None:
    unknown = owner.patch(PROJECT, {"links": {"forum": CHAT, "chat": "nope"}})
    assert unknown.json()["error"]["details"]["fields"] == {
        "links.forum": "unknown",
        "links.chat": "format",
    }
    assert owner.patch(PROJECT, {"links": ["x"]}).json()["error"]["details"]["fields"] == {
        "links": "format"
    }
    assert links_of(owner)["chat"] is None  # nothing of a refused PATCH is kept


def test_an_agent_does_not_set_them(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    assert agent.patch(PROJECT, {"links": {"chat": CHAT}}).status_code == 403
    assert links_of(agent)["chat"] is None  # and reads them as every member does


def page(make_client: ClientFactory) -> str:
    got = make_client(public_pages=True).get("/maintainer/maity")
    assert got.status_code == 200
    return str(got.text)


def test_the_public_page_shows_a_link_into_the_repository_only_while_it_is_public(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner.patch(PROJECT, {"public_page": "on"})
    owner.patch(PROJECT, {"links": {"issues": ISSUES, "chat": CHAT}})
    text = page(make_client)
    assert f'<a href="{CHAT}" rel="nofollow ugc">{CHAT}</a>' in text  # elsewhere: as set
    assert ISSUES not in text  # the hub has not seen the repository public
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(repository_public=True))
    owner.patch(PROJECT, {"links": {"wiki": "https://wiki.example.org/maity"}})  # renders again
    assert f'<a href="{ISSUES}" rel="nofollow ugc">{ISSUES}</a>' in page(make_client)


def test_inside_the_repository_is_its_host_and_path_by_segment_without_case() -> None:
    repo = "https://github.com/acme/maity"
    links = {
        "issues": "https://GitHub.com/Acme/Maity/issues",  # inside, by case
        "wiki": "https://github.com/acme/maity-other/wiki",  # a name that merely starts alike
        "discussions": "https://github.com/acme",  # above the repository
        "chat": "https://matrix.to/#/#maity:example.org",  # another host
    }
    hidden = project_links.public(links, repo, False)
    assert hidden == [links["wiki"], links["discussions"], links["chat"]]
    # Escapes and dot-segments resolve as a browser resolves them: these point into the repository.
    tricks = {
        "issues": "https://github.com/acme/x/../maity/issues",  # a dot-segment
        "wiki": "https://github.com/acme/%6Daity/wiki",  # an escaped letter
        "discussions": "https://github.com/acme/x/%2e%2e/maity/discussions",  # escaped dots
        "chat": "https://github.com/acme%2Fmaity/chat",  # an escaped slash
    }
    assert project_links.public(tricks, repo, False) == []
    backslash = {"issues": "https://github.com/acme\\maity/issues"}  # a browser reads `\` as `/`
    assert project_links.public(backslash, repo, False) == []
    assert project_links.public(tricks, repo, True) == list(tricks.values())
    assert project_links.public(links, repo, True) == list(links.values())
    assert project_links.public(links, None, None) == list(links.values())
