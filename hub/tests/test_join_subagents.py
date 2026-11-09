"""docs/api.md §3.1, §5.2, §6.2: a join carries the owner's instruction to work in subagents
(`subagents`, `subagents_language`); the exchange moves it to the membership, the resume packet
carries it, and whoever may let the agent join changes it."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import catalog
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
JOINS = f"{PROJECT}/joins"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def told(language: str, handle: str = "maintainer") -> str:
    return catalog.section("subagents", language)["instruction"].replace("{owner}", handle)


def new_join(owner: flow.Human, n: int = 1, role: str = "coder", **body: Any) -> Any:
    trust, role = factory.trust_and_role(role)
    agent = {"handle": f"sub-{n}", "display_name": f"Sub {n}"}
    return owner.post(JOINS, {"agent": agent, "trust": trust, "role": role, **body})


def exchanged(make_client: ClientFactory, created: dict[str, Any]) -> flow.Agent:
    client = make_client()
    response = flow.exchange(client, created)
    assert response.status_code == 201, response.text
    return flow.Agent(
        client,
        response.text,
        response.headers["Maity-Credential-Id"],
        response.headers["Maity-Member-Id"],
        response.headers["Maity-Instance"],
    )


def listed(owner: flow.Human, join_id: str) -> dict[str, Any]:
    joins: list[dict[str, Any]] = owner.get(JOINS).json()["items"]
    [join] = [j for j in joins if j["id"] == join_id]
    return join


def refused(response: Any, field: str, reason: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {field: reason}


def forbidden(response: Any, reason: str) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["details"]["reason"] == reason


def test_a_coder_join_tells_the_agent_in_the_creators_language(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    assert owner.patch("/me", {"interface_language": "de"}).status_code == 200
    created = new_join(owner)
    assert created.status_code == 201, created.text
    assert created.json()["instruction"] == told("de")
    join = listed(owner, created.json()["id"])
    assert (join["subagents"], join["subagents_language"]) == (True, "de")
    token = created.json()["join_url"].rsplit("/", 1)[1]
    page = make_client().get(f"/join/{token}", headers={"Accept": "text/markdown"}).text
    assert f"> {told('de')}" in page  # the join page quotes it (§3.2)
    agent = exchanged(make_client, created.json())
    block = agent.resume().json()["membership"]["subagents"]
    assert block == {
        "on": True,
        "language": "de",
        "by": {"kind": "human", "id": owner.id, "handle": "maintainer"},
        "instruction": told("de"),
    }
    view = owner.get(f"{PROJECT}/members/{agent.id}").json()
    assert (view["subagents"], view["subagents_language"]) == (True, "de")
    assert view["subagents_by"]["id"] == owner.id
    assert "instruction" not in view  # the member view never carries the text


def test_an_english_instruction_whatever_the_interface(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    assert owner.patch("/me", {"interface_language": "de"}).status_code == 200
    created = new_join(owner, subagents_language="en")
    assert created.status_code == 201, created.text
    assert created.json()["instruction"] == told("en")
    agent = exchanged(make_client, created.json())
    assert agent.resume().json()["membership"]["subagents"]["language"] == "en"


@pytest.mark.parametrize(("role", "body"), [("tester", {}), ("coder", {"subagents": False})])
def test_no_instruction_for_other_roles_or_when_switched_off(
    owner: flow.Human, make_client: ClientFactory, role: str, body: dict[str, Any]
) -> None:
    created = new_join(owner, role=role, **body)
    assert created.status_code == 201, created.text
    assert created.json()["instruction"] is None
    join = listed(owner, created.json()["id"])
    assert (join["subagents"], join["subagents_language"]) == (False, None)
    token = created.json()["join_url"].rsplit("/", 1)[1]
    page = make_client().get(f"/join/{token}", headers={"Accept": "text/markdown"}).text
    assert told("en") not in page
    agent = exchanged(make_client, created.json())
    block = agent.resume().json()["membership"]["subagents"]
    assert block == {"on": False, "language": None, "by": None, "instruction": None}


def test_a_tester_may_be_told_too(owner: flow.Human) -> None:
    created = new_join(owner, role="tester", subagents=True)
    assert created.status_code == 201, created.text
    assert created.json()["instruction"] == told("en")


def test_the_language_must_be_an_interface_language(owner: flow.Human) -> None:
    refused(new_join(owner, subagents_language="tlh"), "subagents_language", "not_interface")


def test_a_new_instance_keeps_the_memberships_instruction(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = exchanged(make_client, new_join(owner).json())
    assert (
        owner.patch(f"{PROJECT}/members/{agent.id}", {"team": {"max_instances": 2}}).status_code
        == 200
    )
    body = {"agent": {"id": agent.id}, "new_instance": True, "trust": "member", "role": "coder"}
    refused(owner.post(JOINS, {**body, "subagents": False}), "subagents", "differs_from_membership")
    refused(
        owner.post(JOINS, {**body, "subagents_language": "de"}),
        "subagents_language",
        "differs_from_membership",
    )
    same = owner.post(JOINS, {**body, "subagents": True, "subagents_language": "en"})
    assert same.status_code == 201, same.text
    assert same.json()["instruction"] == told("en")


def test_the_owner_switches_it_off_and_back_in_another_language(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = exchanged(make_client, new_join(owner).json())
    off = owner.patch(f"{PROJECT}/members/{agent.id}", {"subagents": False})
    assert off.status_code == 200, off.text
    assert (off.json()["subagents"], off.json()["subagents_by"]) == (False, None)
    assert _last_changed(migrated) == ["subagents", "subagents_language"]
    assert agent.resume().json()["membership"]["subagents"]["on"] is False
    on = owner.patch(
        f"{PROJECT}/members/{agent.id}", {"subagents": True, "subagents_language": "ja"}
    )
    assert on.status_code == 200, on.text
    assert agent.resume().json()["membership"]["subagents"]["instruction"] == told("ja")
    same = owner.patch(f"{PROJECT}/members/{agent.id}", {"subagents": True})
    assert same.status_code == 200 and same.json()["subagents_language"] == "ja"


def test_subagents_goes_alone_and_only_to_agents(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = exchanged(make_client, new_join(owner).json())
    both = owner.patch(f"{PROJECT}/members/{agent.id}", {"subagents": False, "trust": "member"})
    refused(both, "subagents", "alone")
    refused(
        owner.patch(f"{PROJECT}/members/{owner.id}", {"subagents": False}),
        "subagents",
        "agents_only",
    )


def test_an_agent_never_changes_it(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = exchanged(make_client, new_join(owner).json())
    forbidden(agent.patch(f"{PROJECT}/members/{agent.id}", {"subagents": False}), "humans_only")


def test_an_admin_who_does_not_own_the_agent_may_not(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = exchanged(make_client, new_join(owner).json())
    other = flow.human(make_client, migrated, "other")
    factory.membership(migrated, _project_id(migrated), "owner", human_id=other.id)
    forbidden(other.patch(f"{PROJECT}/members/{agent.id}", {"subagents": False}), "join_rule")


def test_a_member_changes_their_own_agent_while_member_agents_is_on(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project_id(migrated), "member", human_id=friend.id)
    created = friend.post(JOINS, {"agent": {"handle": "friend-sub", "display_name": "F"}})
    assert created.status_code == 201, created.text
    agent = exchanged(make_client, created.json())
    assert friend.patch(f"{PROJECT}/members/{agent.id}", {"subagents": True}).status_code == 200
    policy = owner.patch(PROJECT, {"policy": {"member_agents": "off"}, "reason": "test"})
    assert policy.status_code == 200, policy.text
    forbidden(friend.patch(f"{PROJECT}/members/{agent.id}", {"subagents": False}), "join_rule")


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def _last_changed(engine: Engine) -> Any:
    with engine.connect() as conn:
        event = conn.execute(
            select(t.event).where(t.event.c.kind == "member_updated").order_by(t.event.c.seq.desc())
        ).first()
    assert event is not None
    return event.payload["changed"]


def test_an_owner_outside_the_project_is_told_join_rule(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_mentions import second_owners_agent

    anna = flow.human(make_client, migrated, "anna")
    agent_id = second_owners_agent(migrated, "anna", "builder")
    forbidden(anna.patch(f"{PROJECT}/members/{agent_id}", {"subagents": False}), "join_rule")
    # Anyone else who is no member: the project does not exist (§2.3).
    stranger = flow.human(make_client, migrated, "stranger")
    response = stranger.patch(f"{PROJECT}/members/{agent_id}", {"subagents": False})
    assert response.status_code == 404, response.text


def test_the_briefing_view_carries_the_instruction(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§19.3.1: as a resume computes it, for the owner in the project, an admin and an owner
    outside the project."""
    agent = exchanged(make_client, new_join(owner).json())
    packet = agent.resume().json()["membership"]["subagents"]
    admin = flow.human(make_client, migrated, "second-admin")
    factory.membership(migrated, _project_id(migrated), "admin", human_id=admin.id)
    for reader in (owner, admin):
        view = reader.get(f"{PROJECT}/members/{agent.id}/briefing")
        assert view.status_code == 200, view.text
        assert view.json()["membership"]["subagents"] == packet
    from tests.test_mentions import second_owners_agent

    anna = flow.human(make_client, migrated, "anna")
    agent_id = second_owners_agent(migrated, "anna", "builder")
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent_id)
            .values(subagents=True, subagents_language="en", subagents_by=anna.id)
        )
    outside = anna.get(f"{PROJECT}/members/{agent_id}/briefing")
    assert outside.status_code == 200, outside.text
    assert outside.json()["membership"]["subagents"] == {
        "on": True,
        "language": "en",
        "by": {"kind": "human", "id": anna.id, "handle": "anna"},
        "instruction": told("en", "anna"),
    }


def test_a_language_sent_is_checked_even_where_the_instruction_is_off(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    refused(
        new_join(owner, subagents=False, subagents_language="tlh"),
        "subagents_language",
        "not_interface",
    )
    refused(
        new_join(owner, 2, role="tester", subagents_language="tlh"),
        "subagents_language",
        "not_interface",
    )
    agent = exchanged(make_client, new_join(owner, 3).json())
    path = f"{PROJECT}/members/{agent.id}"
    refused(
        owner.patch(path, {"subagents": False, "subagents_language": "tlh"}),
        "subagents_language",
        "not_interface",
    )
    assert agent.resume().json()["membership"]["subagents"]["on"] is True  # nothing changed


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"subagents": None}, {"subagents": "bool_type"}),
        ({"subagents_language": None}, {"subagents_language": "string_type"}),
        (
            {"subagents": None, "subagents_language": None},
            {"subagents": "bool_type", "subagents_language": "string_type"},
        ),
    ],
)
def test_null_is_no_value_for_either_field(
    owner: flow.Human, make_client: ClientFactory, body: dict[str, Any], fields: dict[str, str]
) -> None:
    agent = exchanged(make_client, new_join(owner).json())
    response = owner.patch(f"{PROJECT}/members/{agent.id}", body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == fields
