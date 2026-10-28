"""docs/api.md §5.2, "Meat proxy": a human's switch, shown to the agents that deal with them."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from maity_hub.views import MEAT_PROXY_NOTE
from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def test_it_is_off_until_the_human_switches_it_on(owner: flow.Human) -> None:
    assert owner.get("/me").json()["member"]["meat_proxy"] is False
    answer = owner.patch("/me", {"meat_proxy": True})
    assert answer.status_code == 200
    assert answer.json()["member"]["meat_proxy"] is True and "server_time" in answer.json()
    assert owner.get("/me").json()["member"]["meat_proxy"] is True
    assert owner.patch("/me", {"meat_proxy": False}).json()["member"]["meat_proxy"] is False


def test_the_agents_of_the_human_and_of_the_project_read_it_with_one_fixed_sentence(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, agent={"handle": "agent-b", "display_name": "B"})
    owner.patch("/me", {"meat_proxy": True})
    packet = agent.resume().json()
    assert packet["me"]["owner"] == {
        "id": owner.id,
        "handle": "maintainer",
        "meat_proxy": True,
        "meat_proxy_note": MEAT_PROXY_NOTE,
    }
    (peer,) = packet["peers"]
    assert peer["meat_proxy"] is True and peer["meat_proxy_note"] == MEAT_PROXY_NOTE
    assert MEAT_PROXY_NOTE == "This person says: I am a meat proxy."
    owner.patch("/me", {"meat_proxy": False})  # read live on every resume
    again = agent.resume().json()
    assert (
        "meat_proxy_note" not in again["me"]["owner"]
        and again["me"]["owner"]["meat_proxy"] is False
    )
    assert "meat_proxy_note" not in again["peers"][0]


def test_an_agent_never_sets_it(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    refused = agent.patch("/me", {"meat_proxy": True})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden"
    assert owner.get("/me").json()["member"]["meat_proxy"] is False


def test_a_human_changes_nothing_else_here(owner: flow.Human) -> None:
    assert owner.patch("/me", {}).status_code == 400
    assert owner.patch("/me", {"paused": None}).status_code == 400
    assert owner.patch("/me", {"meat_proxy": "yes"}).status_code == 400
    assert owner.patch("/me", {"meat_proxy": True, "unknown": 1}).status_code == 400


def test_an_agent_still_needs_paused(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    assert agent.patch("/me", {}).status_code == 400
    assert agent.patch("/me", {"paused": {"reason": "quota"}}).status_code == 200
