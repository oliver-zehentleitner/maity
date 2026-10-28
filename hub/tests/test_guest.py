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
