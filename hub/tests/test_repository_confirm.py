"""docs/api.md §11.4: the namespace owner confirms the project's repository for their own
forge grants; every change of the URL takes the confirmation back."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

URL = "https://github.com/acme/maity"
OTHER = "https://github.com/acme/private-thing"
CONFIRM = "/projects/maintainer/maity/repository/confirm"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity", repository={"url": URL})
    return human


@pytest.fixture
def anna(make_client: ClientFactory, migrated: Engine, owner: flow.Human) -> flow.Human:
    """A second owner of maintainer/maity, not its namespace owner."""
    human = flow.human(make_client, migrated, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "owner", human_id=human.id)
    return human


def error(response: Any) -> tuple[int, str, dict[str, Any]]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["details"]


def confirmed(who: flow.Human) -> bool:
    flag: bool = who.get("/projects/maintainer/maity").json()["repository"]["owner_confirmed"]
    return flag


def test_a_new_repository_is_unconfirmed_until_the_owner_confirms_it(owner: flow.Human) -> None:
    assert confirmed(owner) is False
    answer = owner.post(CONFIRM, {"url": URL})
    assert answer.status_code == 200, answer.text
    assert answer.json()["repository"]["owner_confirmed"] is True
    assert confirmed(owner) is True
    assert owner.post(CONFIRM, {"url": URL + "/"}).status_code == 200  # the same URL


def test_a_url_the_project_no_longer_carries_is_refused(
    owner: flow.Human, anna: flow.Human
) -> None:
    """A co-admin's change between what the owner saw and the click is never confirmed."""
    assert (
        anna.patch("/projects/maintainer/maity", {"repository": {"url": OTHER}}).status_code == 200
    )
    refused = owner.post(CONFIRM, {"url": URL})
    assert error(refused) == (409, "conflict", {"reason": "repository_changed", "url": OTHER})
    assert confirmed(owner) is False


def test_a_project_without_a_repository_has_nothing_to_confirm(owner: flow.Human) -> None:
    owner.patch("/projects/maintainer/maity", {"repository": None})
    refused = owner.post(CONFIRM, {"url": URL})
    assert error(refused) == (409, "conflict", {"reason": "repository_changed", "url": None})


def test_only_the_namespace_owner_confirms(
    owner: flow.Human, anna: flow.Human, make_client: ClientFactory
) -> None:
    status, code, _ = error(anna.post(CONFIRM, {"url": URL}))
    assert (status, code) == (403, "forbidden")
    agent = flow.agent(make_client, owner, role="admin")
    status, code, details = error(agent.post(CONFIRM, {"url": URL}))
    assert (status, code, details.get("reason")) == (403, "forbidden", "humans_only")
    assert confirmed(owner) is False


@pytest.mark.parametrize("by", ["owner", "anna"])
def test_every_change_of_the_url_takes_the_confirmation_back(
    owner: flow.Human, anna: flow.Human, by: str
) -> None:
    owner.post(CONFIRM, {"url": URL})
    who = {"owner": owner, "anna": anna}[by]
    who.patch("/projects/maintainer/maity", {"repository": {"url": OTHER}})
    assert confirmed(owner) is False
    owner.post(CONFIRM, {"url": OTHER})
    who.patch("/projects/maintainer/maity", {"repository": None})
    who.patch("/projects/maintainer/maity", {"repository": {"url": OTHER}})
    assert confirmed(owner) is False  # removed and set again is a change too


def test_the_same_url_with_another_branch_keeps_it(owner: flow.Human) -> None:
    owner.post(CONFIRM, {"url": URL})
    owner.patch("/projects/maintainer/maity", {"repository": {"url": URL, "default_branch": "dev"}})
    assert confirmed(owner) is True
