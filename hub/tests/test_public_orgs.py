"""docs/api.md §16.9, "An organisation's page": its name, its handle, its public projects, and
never who belongs to it; served exactly while `public_page` is `on`."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import public_pages
from tests import flow
from tests.conftest import ClientFactory

READ = "/api/v1/public/pages/acme"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine, settings: Any) -> Any:
    public_pages.configure(replace(settings, public_pages=True))
    make = lambda **kw: make_client(public_pages=True, **kw)  # noqa: E731
    human = flow.human(make, migrated)
    made = human.post("/orgs", {"handle": "acme", "display_name": "Acme Inc"})
    assert made.status_code == 201, made.text
    created = human.post(
        "/projects", {"slug": "tool", "name": "Tool", "owner": "acme", "public_page": "on"}
    )
    assert created.status_code == 201, created.text
    return human


@pytest.fixture
def anyone(make_client: ClientFactory) -> Any:
    return make_client(public_pages=True)


def on(owner: Any) -> None:
    assert owner.patch("/orgs/acme", {"public_page": "on"}).status_code == 200


def test_the_page_exists_only_while_it_is_on(owner: Any, anyone: Any) -> None:
    assert anyone.get(READ).status_code == 404
    on(owner)
    got = anyone.get(READ)
    assert got.json() == {
        "path": "/acme",
        "kind": "organisation_page",
        "data": {
            "name": "Acme Inc",
            "handle": "acme",
            "projects": [{"name": "Tool", "full_name": "acme/tool"}],
        },
    }
    assert "Acme Inc" in anyone.get("/acme").text
    assert owner.patch("/orgs/acme", {"public_page": "off"}).status_code == 200
    assert anyone.get(READ).status_code == 404


def test_it_never_names_a_member(owner: Any, anyone: Any) -> None:
    on(owner)
    assert owner.handle not in anyone.get(READ).text
    assert owner.handle not in anyone.get("/acme").text


def test_it_follows_the_project_and_the_name(owner: Any, anyone: Any) -> None:
    on(owner)
    assert owner.patch("/orgs/acme", {"display_name": "Acme Two"}).status_code == 200
    assert anyone.get(READ).json()["data"]["name"] == "Acme Two"
    assert owner.patch("/projects/acme/tool", {"public_page": "off"}).status_code == 200
    assert anyone.get(READ).json()["data"]["projects"] == []
