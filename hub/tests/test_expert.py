"""docs/api.md §2.3 "The expert": it answers and posts, takes no card and files no request."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def expert(make_client: ClientFactory, owner: flow.Human) -> flow.Agent:
    return flow.agent(make_client, owner, role="expert", areas=["docs/"])


def _card(owner: flow.Human, **body: Any) -> Any:
    return owner.post(f"{PROJECT}/tasks", {"title": "A card", "kind": "task", **body})


def _invalid(response: Any, field: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {field: "expert"}


def test_an_expert_claims_notes_and_asks_nothing_but_posts(
    owner: flow.Human, expert: flow.Agent
) -> None:
    card = _card(owner).json()["id"]
    assert expert.get(f"{PROJECT}/tasks/{card}").status_code == 200
    assert expert.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 403
    assert expert.post(f"{PROJECT}/tasks/{card}/notes", {"body": "Looks off."}).status_code == 403
    assert expert.post(f"{PROJECT}/tasks", {"title": "Mine"}).status_code == 403
    asked = expert.post(f"{PROJECT}/requests", {"class": "info", "title": "Why?", "to": "owner"})
    assert asked.status_code == 403
    posted = expert.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "§2.3 says so."},
    )
    assert posted.status_code == 201, posted.text


def test_an_expert_answers_a_question_to_the_experts(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent
) -> None:
    asker = flow.agent(make_client, owner)
    asked = asker.post(
        f"{PROJECT}/requests",
        {"class": "info", "title": "Which § says who answers?", "to": "role:expert"},
    )
    assert asked.status_code == 201, asked.text
    request = asked.json()["id"]
    mine = expert.get(f"{PROJECT}/requests", params={"to": "me"}).json()["items"]
    assert [item["id"] for item in mine] == [request]
    answered = expert.post(f"{PROJECT}/requests/{request}/answer", {"text": "§7, the `to` row."})
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"]["text"] == "§7, the `to` row."


def test_no_card_is_assigned_to_an_expert(owner: flow.Human, expert: flow.Agent) -> None:
    _invalid(_card(owner, assigned_to=expert.id), "assigned_to")
    card = _card(owner).json()["id"]
    _invalid(owner.post(f"{PROJECT}/tasks/{card}/assign", {"assignee": expert.id}), "assignee")
    _invalid(owner.post(f"{PROJECT}/tasks/{card}/claim", {"holder": expert.id}), "holder")


def test_area_routing_skips_an_expert(owner: flow.Human, expert: flow.Agent) -> None:
    created = _card(owner, area="docs/api.md")
    assert created.status_code == 201, created.text
    assert created.json()["assigned_to"] == owner.id  # "/" is the owner's, not the expert's
