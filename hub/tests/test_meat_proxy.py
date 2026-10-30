"""docs/api.md §5.2, "Meat proxy": a human's switch, shown to the agents that deal with them."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub.views import MEAT_PROXY_HANDS, MEAT_PROXY_INTRO, MEAT_PROXY_LEAD, meat_proxy_note
from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


BOTH = f"{MEAT_PROXY_INTRO} {MEAT_PROXY_LEAD} {MEAT_PROXY_HANDS}"


def mine(owner: flow.Human) -> dict[str, Any]:
    member: dict[str, Any] = owner.get("/me").json()["member"]
    return {k: v for k, v in member.items() if k.startswith("meat_proxy")}


def test_the_sentences_are_the_contracts_words() -> None:
    assert MEAT_PROXY_INTRO == "This person says: I am a meat proxy."
    assert MEAT_PROXY_LEAD == "Lead me step by step rather than expecting me to explain."
    assert MEAT_PROXY_HANDS == "When you need a human's hands, come to me first."
    assert meat_proxy_note(True, True) == BOTH


def test_it_is_off_until_the_human_switches_it_on_and_the_note_is_always_there(
    owner: flow.Human,
) -> None:
    assert mine(owner) == {
        "meat_proxy": False,
        "meat_proxy_lead": False,
        "meat_proxy_hands": False,
        "meat_proxy_note": BOTH,  # what switching it on would send
    }
    answer = owner.patch("/me", {"meat_proxy": True})
    assert answer.status_code == 200 and "server_time" in answer.json()
    assert mine(owner) == {
        "meat_proxy": True,
        "meat_proxy_lead": True,
        "meat_proxy_hands": True,
        "meat_proxy_note": BOTH,
    }
    assert owner.patch("/me", {"meat_proxy": False}).json()["member"]["meat_proxy"] is False
    assert mine(owner)["meat_proxy_lead"] is False and mine(owner)["meat_proxy_hands"] is False


@pytest.mark.parametrize(
    ("body", "lead", "hands"),
    [
        ({"meat_proxy": True}, True, True),
        ({"meat_proxy": True, "meat_proxy_hands": False}, True, False),
        ({"meat_proxy": True, "meat_proxy_lead": False}, False, True),
        ({"meat_proxy_lead": True}, True, False),  # alone it switches the mode on, one part
        ({"meat_proxy_hands": True}, False, True),
        ({"meat_proxy_lead": True, "meat_proxy_hands": True}, True, True),
        ({"meat_proxy": True, "meat_proxy_lead": False, "meat_proxy_hands": False}, False, False),
        ({"meat_proxy": False}, False, False),
    ],
)
def test_a_patch_applies_the_switch_first_then_the_parts_it_gives(
    owner: flow.Human, body: dict[str, bool], lead: bool, hands: bool
) -> None:
    owner.patch("/me", {"meat_proxy": False})
    answer = owner.patch("/me", body)
    assert answer.status_code == 200, answer.text
    member = answer.json()["member"]
    assert (member["meat_proxy_lead"], member["meat_proxy_hands"]) == (lead, hands)
    assert member["meat_proxy"] is (lead or hands)  # derived: on while a part is
    on = lead or hands
    assert member["meat_proxy_note"] == (meat_proxy_note(lead, hands) if on else BOTH)


def test_a_part_given_alone_leaves_the_other_as_it_is(owner: flow.Human) -> None:
    owner.patch("/me", {"meat_proxy": True})
    member = owner.patch("/me", {"meat_proxy_lead": False}).json()["member"]
    assert (member["meat_proxy"], member["meat_proxy_lead"], member["meat_proxy_hands"]) == (
        True,
        False,
        True,
    )
    assert member["meat_proxy_note"] == f"{MEAT_PROXY_INTRO} {MEAT_PROXY_HANDS}"
    off = owner.patch("/me", {"meat_proxy_hands": False}).json()["member"]
    assert off["meat_proxy"] is False  # both parts off switch the mode off


def test_off_with_a_part_on_is_a_conflict(owner: flow.Human) -> None:
    refused = owner.patch("/me", {"meat_proxy": False, "meat_proxy_hands": True})
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"meat_proxy": "conflicts_with_parts"}
    assert mine(owner)["meat_proxy"] is False  # nothing was applied


def test_nothing_is_kept_from_an_earlier_time_the_mode_was_on(owner: flow.Human) -> None:
    owner.patch("/me", {"meat_proxy": True, "meat_proxy_hands": False})
    owner.patch("/me", {"meat_proxy": False})
    member = owner.patch("/me", {"meat_proxy": True}).json()["member"]
    assert (member["meat_proxy_lead"], member["meat_proxy_hands"]) == (True, True)


def test_the_agents_of_the_human_and_of_the_project_read_the_parts_and_the_note(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, agent={"handle": "agent-b", "display_name": "B"})
    owner.patch("/me", {"meat_proxy": True, "meat_proxy_hands": False})
    packet = agent.resume().json()
    said = {
        "meat_proxy": True,
        "meat_proxy_lead": True,
        "meat_proxy_hands": False,
        "meat_proxy_note": f"{MEAT_PROXY_INTRO} {MEAT_PROXY_LEAD}",
    }
    assert packet["me"]["owner"] == {"id": owner.id, "handle": "maintainer", **said}
    (peer,) = packet["peers"]
    assert {k: v for k, v in peer.items() if k.startswith("meat_proxy")} == said
    owner.patch("/me", {"meat_proxy": False})  # read live on every resume
    again = agent.resume().json()
    assert again["me"]["owner"] == {"id": owner.id, "handle": "maintainer", "meat_proxy": False}
    assert {k: v for k, v in again["peers"][0].items() if k.startswith("meat_proxy")} == {
        "meat_proxy": False
    }


@pytest.mark.parametrize("field", ["meat_proxy", "meat_proxy_lead", "meat_proxy_hands"])
def test_an_agent_never_sets_it(owner: flow.Human, make_client: ClientFactory, field: str) -> None:
    agent = flow.agent(make_client, owner)
    refused = agent.patch("/me", {field: True})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden"
    assert mine(owner)["meat_proxy"] is False


def test_a_human_changes_nothing_else_here(owner: flow.Human) -> None:
    assert owner.patch("/me", {}).status_code == 400
    assert owner.patch("/me", {"paused": None}).status_code == 400
    assert owner.patch("/me", {"meat_proxy": "yes"}).status_code == 400
    assert owner.patch("/me", {"meat_proxy_lead": "yes"}).status_code == 400
    assert owner.patch("/me", {"meat_proxy_hands": None}).status_code == 400
    assert owner.patch("/me", {"meat_proxy": True, "unknown": 1}).status_code == 400


def test_an_agent_still_needs_paused(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    assert agent.patch("/me", {}).status_code == 400
    assert agent.patch("/me", {"paused": {"reason": "quota"}}).status_code == 200


def test_a_repeated_key_replays_the_answer_as_the_profile_is_now(owner: flow.Human) -> None:
    key = {"Idempotency-Key": "meat-proxy-replay-0001"}
    path = "/api/v1/me"
    first = owner.client.patch(
        path, json={"meat_proxy": True}, headers={"X-CSRF-Token": owner.csrf, **key}
    )
    assert first.status_code == 200 and first.json()["member"]["meat_proxy"] is True
    owner.patch("/me", {"meat_proxy": False})
    replay = owner.client.patch(
        path, json={"meat_proxy": True}, headers={"X-CSRF-Token": owner.csrf, **key}
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["member"]["meat_proxy"] is False  # the resource as it is now
    assert "server_time" in replay.json()
    other = owner.client.patch(
        path, json={"meat_proxy": False}, headers={"X-CSRF-Token": owner.csrf, **key}
    )
    assert other.status_code == 409  # the same key with another body
