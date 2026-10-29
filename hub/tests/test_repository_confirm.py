"""docs/api.md §11.4: the namespace owner confirms the project's repository for their own
forge grants; every change of the URL takes the confirmation back."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_two_factor import Clock, code_now, enrol, signed_in
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

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


def test_a_transfer_takes_the_confirmation_back_and_names_the_repository(
    owner: flow.Human, anna: flow.Human
) -> None:
    owner.post(CONFIRM, {"url": URL})
    filed = owner.post("/projects/maintainer/maity/transfer", {"to": anna.id})
    assert filed.status_code == 202, filed.text
    assert URL in filed.json()["summary"]
    done = anna.post(
        f"/projects/maintainer/maity/requests/{filed.json()['id']}/answer", {"reply_id": "go"}
    )
    assert done.status_code == 200, done.text
    assert anna.get("/projects/anna/maity").json()["repository"]["owner_confirmed"] is False
    # The old owner's confirmation is gone and theirs no longer counts.
    status, code, _ = error(owner.post("/projects/anna/maity/repository/confirm", {"url": URL}))
    assert (status, code) == (403, "forbidden")
    assert anna.post("/projects/anna/maity/repository/confirm", {"url": URL}).status_code == 200


def test_confirming_needs_a_recent_factor(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """The confirmation opens the owner's grants to the repository (§2.8.4, §11.4)."""
    human = signed_in(make_client, migrated)
    flow.project(human, "maity", repository={"url": URL})
    secret, _ = enrol(human, moment)
    moment.move(minutes=11)
    status, code, details = error(human.post(CONFIRM, {"url": URL}))
    assert (status, code, details["reason"]) == (403, "forbidden", "step_up_required")
    assert confirmed(human) is False
    assert human.post("/auth/second-factor/verify", {"code": code_now(secret, moment.at)})
    assert human.post(CONFIRM, {"url": URL}).status_code == 200
    assert confirmed(human) is True
