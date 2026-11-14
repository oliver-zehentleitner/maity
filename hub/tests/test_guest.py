"""docs/api.md §2.3 "Guest": trust `guest` reads and comments, and is never a target."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def guest(make_client: ClientFactory, owner: flow.Human) -> flow.Agent:
    return flow.agent(make_client, owner, trust="guest", role="reviewer")


def _card(owner: flow.Human) -> str:
    created = owner.post(f"{PROJECT}/tasks", {"title": "A card", "kind": "task"})
    assert created.status_code == 201, created.text
    card_id: str = created.json()["id"]
    return card_id


def _invalid(response: Any, field: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {field: "guest"}


def test_a_guest_reads_and_notes_but_claims_asks_and_posts_nothing(
    owner: flow.Human, guest: flow.Agent
) -> None:
    card = _card(owner)
    assert guest.get(f"{PROJECT}/tasks/{card}").status_code == 200
    assert guest.post(f"{PROJECT}/tasks/{card}/notes", {"body": "Looks off."}).status_code == 201
    assert guest.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 403
    asked = guest.post(f"{PROJECT}/requests", {"class": "info", "title": "Why?", "to": "owner"})
    assert asked.status_code == 403
    posted = guest.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": "all", "body": "Hi"}
    )
    assert posted.status_code == 403
    memory = guest.post(f"{PROJECT}/memory", {"store": "team", "text": "A note to self"})
    assert memory.status_code == 403


def test_a_guest_chats_with_its_human(owner: flow.Human, guest: flow.Agent) -> None:
    chat = guest.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "chat", "conversation_id": guest.id, "body": "Hi"},
    )
    assert chat.status_code == 201, chat.text


def test_a_guest_is_never_a_target(
    owner: flow.Human, guest: flow.Agent, make_client: ClientFactory
) -> None:
    card = _card(owner)
    _invalid(owner.patch(f"{PROJECT}/tasks/{card}", {"assigned_to": guest.id}), "assigned_to")
    _invalid(
        owner.patch(PROJECT, {"policy": {"contract_arbiter": guest.id}, "reason": "test"}),
        "policy.contract_arbiter",
    )
    _invalid(
        owner.patch(PROJECT, {"settings": {"onboarding": {"check_in_with": guest.id}}}),
        "settings.onboarding.check_in_with",
    )
    coder = flow.agent(make_client, owner)
    _invalid(owner.patch(f"{PROJECT}/members/{coder.id}", {"reports_to": guest.id}), "reports_to")
    _invalid(
        coder.post(f"{PROJECT}/requests", {"class": "info", "title": "Why?", "to": guest.id}),
        "to",
    )


def test_area_routing_skips_a_guest(owner: flow.Human, guest: flow.Agent, migrated: Engine) -> None:
    with migrated.begin() as conn:
        conn.execute(
            t.membership.update().where(t.membership.c.agent_id == guest.id).values(areas=["hub/"])
        )
    created = owner.post(f"{PROJECT}/tasks", {"title": "Hub card", "kind": "task", "area": "hub/x"})
    assert created.status_code == 201, created.text
    assert created.json()["assigned_to"] != guest.id


def test_a_human_guest_creates_no_group_chat(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    visitor = flow.human(make_client, migrated, "visitor")
    factory.membership(migrated, project_id, "coder", trust="guest", human_id=visitor.id)
    created = visitor.post(f"{PROJECT}/conversations", {"participants": [owner.id]})
    assert created.status_code == 403


def test_a_guest_holds_no_claim_an_admin_gives(owner: flow.Human, guest: flow.Agent) -> None:
    card = _card(owner)
    for holder in (guest.id, f"{guest.id}#{guest.instance}"):
        refused = owner.post(f"{PROJECT}/tasks/{card}/claim", {"holder": holder})
        _invalid(refused, "holder")


def test_a_newcomer_never_checks_in_with_a_guest(
    owner: flow.Human, guest: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    """The guest is the only reviewer: `role:reviewer` falls back past it to the owner; a
    reviewer who is no guest is found; an id stored before its member became a guest
    resolves to nobody."""
    settings = {"onboarding": {"check_in_with": "role:reviewer"}}
    assert owner.patch(PROJECT, {"settings": settings}).status_code == 200
    newcomer = flow.agent(make_client, owner)

    def checks_in_with() -> Any:
        return (newcomer.resume().json().get("onboarding") or {}).get("check_in_with")

    assert checks_in_with()["member_id"] == owner.id
    reviewer = flow.agent(make_client, owner, role="reviewer")
    assert checks_in_with()["member_id"] == reviewer.id
    coder = flow.agent(make_client, owner)
    by_id = {"onboarding": {"check_in_with": coder.id}}
    assert owner.patch(PROJECT, {"settings": by_id}).status_code == 200
    with migrated.begin() as conn:
        conn.execute(
            t.membership.update().where(t.membership.c.agent_id == coder.id).values(trust="guest")
        )
    found = checks_in_with()
    assert found is None or found["member_id"] != coder.id


# --- a demotion to guest withdraws the arbiter seats (§2.3, §6.2) -----------------------


def _demote(owner: flow.Human, member_id: str, trust: str = "guest") -> None:
    response = owner.patch(f"{PROJECT}/members/{member_id}", {"trust": trust})
    assert response.status_code == 200, response.text


def _set_arbiter(owner: flow.Human, member_id: str) -> None:
    response = owner.patch(PROJECT, {"policy": {"contract_arbiter": member_id}, "reason": "test"})
    assert response.status_code == 200, response.text


def _policy(migrated: Engine) -> Any:
    with migrated.connect() as conn:
        return conn.execute(select(t.project)).one()


def test_a_demoted_arbiter_loses_the_policy_seat_and_the_cards(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    arbiter = flow.agent(make_client, owner, role="reviewer")
    _set_arbiter(owner, arbiter.id)
    made = owner.post(
        f"{PROJECT}/tasks",
        {"title": "A contract", "kind": "contract", "contract": {"arbiter": arbiter.id}},
    )
    assert made.status_code == 201, made.text
    card = made.json()["id"]
    _demote(owner, arbiter.id)
    # no admin agent in the project: the seat goes to the owner (§6.2)
    assert _policy(migrated).contract_arbiter == owner.id
    with migrated.connect() as conn:
        held = conn.execute(select(t.card.c.contract).where(t.card.c.id == card)).scalar_one()
        changed = conn.execute(
            select(t.event).where(t.event.c.kind == "policy_changed").order_by(t.event.c.seq.desc())
        ).first()
    assert held["arbiter"] == owner.id
    assert changed is not None and changed.payload["reason"] == "member_demoted"
    refused = arbiter.patch(f"{PROJECT}/tasks/{card}", {"contract": {"state": "final"}})
    assert refused.status_code == 403, refused.text


def test_a_human_arbiter_demoted_hands_the_seat_to_the_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    human = flow.human(make_client, migrated, "a-reviewer")
    factory.membership(migrated, _policy(migrated).id, "member", human_id=human.id)
    _set_arbiter(owner, human.id)
    _demote(owner, human.id)
    assert _policy(migrated).contract_arbiter == owner.id


def test_a_guest_left_in_an_arbiter_seat_is_routed_past(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A seat a guest holds from before (data written before the reset existed): no state
    move, a new contract card and a contract request get the default, not `400 guest`."""
    from sqlalchemy import update

    arbiter = flow.agent(make_client, owner, role="reviewer")
    made = owner.post(
        f"{PROJECT}/tasks",
        {"title": "A contract", "kind": "contract", "contract": {"arbiter": arbiter.id}},
    )
    card = made.json()["id"]
    _set_arbiter(owner, arbiter.id)
    with migrated.begin() as conn:  # demoted behind the reset's back
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == arbiter.id).values(trust="guest")
        )
    refused = arbiter.patch(f"{PROJECT}/tasks/{card}", {"contract": {"state": "final"}})
    assert refused.status_code == 403, refused.text
    other = flow.agent(make_client, owner)
    fresh = other.post(f"{PROJECT}/tasks", {"title": "Another", "kind": "contract"})
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["contract"]["arbiter"] == owner.id  # the seat's default
    asked = other.post(f"{PROJECT}/requests", {"class": "contract", "title": "Which?"})
    assert asked.status_code == 201, asked.text
    assert asked.json()["to"] == owner.id


def test_a_human_guest_left_on_a_card_falls_to_the_owner_not_the_policy_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A card a human arbitrates, the human a guest from before the reset existed, the policy's
    arbiter an agent: the card's seat falls to the owner, as at a removal, never to the
    agent (§6.2 "a card a human arbitrated never passes to an agent")."""
    from sqlalchemy import update

    human = flow.human(make_client, migrated, "a-reviewer")
    factory.membership(migrated, _policy(migrated).id, "member", human_id=human.id)
    made = owner.post(
        f"{PROJECT}/tasks",
        {"title": "A contract", "kind": "contract", "contract": {"arbiter": human.id}},
    )
    assert made.status_code == 201, made.text
    card = made.json()["id"]
    agent = flow.agent(make_client, owner, role="reviewer")
    _set_arbiter(owner, agent.id)
    with migrated.begin() as conn:  # demoted behind the reset's back
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == human.id).values(trust="guest")
        )
    refused = agent.patch(f"{PROJECT}/tasks/{card}", {"contract": {"state": "final"}})
    assert refused.status_code == 403, refused.text
    decided = owner.patch(f"{PROJECT}/tasks/{card}", {"contract": {"state": "final"}})
    assert decided.status_code == 200, decided.text


def test_a_demotion_to_member_keeps_the_arbiter_seat(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    arbiter = flow.agent(make_client, owner, role="admin")
    _set_arbiter(owner, arbiter.id)
    _demote(owner, arbiter.id, "member")
    assert _policy(migrated).contract_arbiter == arbiter.id


def test_an_agent_no_longer_admin_stops_standing_in_for_the_coordinator(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    stand_in = flow.agent(make_client, owner, role="admin")
    set_it = owner.patch(
        PROJECT, {"policy": {"coordinator_substitute": stand_in.id}, "reason": "test"}
    )
    assert set_it.status_code == 200, set_it.text
    _demote(owner, stand_in.id, "member")
    assert _policy(migrated).coordinator_substitute is None
