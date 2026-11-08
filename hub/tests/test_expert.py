"""docs/api.md §2.3 "The expert": it answers and posts, takes no card and files no request."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import tables as t
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
    _invalid(owner.patch(f"{PROJECT}/tasks/{card}", {"assigned_to": expert.id}), "assigned_to")


def test_area_routing_skips_an_expert(owner: flow.Human, expert: flow.Agent) -> None:
    created = _card(owner, area="docs/api.md")
    assert created.status_code == 201, created.text
    assert created.json()["assigned_to"] == owner.id  # "/" is the owner's, not the expert's


def test_a_holder_becomes_an_expert_only_after_its_cards_go_back(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """§2.3 "The expert": the role change waits until the member holds no card, and a holder
    without `tasks:write` writes nothing to a card it still holds."""
    coder = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert coder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    changed = owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["details"] == {"reason": "holds_cards"}
    # A holder whose role took the work away (here written past the API, as an older
    # membership could hold it) neither checkpoints nor reports.
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == coder.id)
            .values(role="expert", role_base="expert")
        )
    step = {"last_step": "read", "next_step": "write"}
    for path, body in (
        ("checkpoint", step),
        ("report", {"summary": "Done.", "pr_status": "none", "code": False}),
    ):
        refused = coder.post(f"{PROJECT}/tasks/{card}/{path}", body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"] == {"scope": "tasks:write"}
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == coder.id)
            .values(role="coder", role_base="coder")
        )
    released = coder.post(f"{PROJECT}/tasks/{card}/release", {})
    assert released.status_code == 200, released.text
    changed = owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
    assert changed.status_code == 200, changed.text


def test_a_role_change_to_expert_that_waits_for_a_go_is_refused_while_cards_are_held(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """§2.3 "The expert": a role change an admin agent proposes is refused at once while
    the member holds a card, not filed as a request that no go could write."""
    admin = flow.agent(make_client, owner, role="admin")
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = _card(owner).json()["id"]
    assert reviewer.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    refused = admin.patch(f"{PROJECT}/members/{reviewer.id}", {"role": "expert"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"] == {"reason": "holds_cards"}


@pytest.mark.parametrize("status", ["cancelled", "done"])
def test_an_expert_reports_on_no_closed_card(
    owner: flow.Human, expert: flow.Agent, migrated: Engine, status: str
) -> None:
    """§6.4: a report needs `tasks:write`, checked before the card's status."""
    card = _card(owner).json()["id"]
    with migrated.begin() as conn:  # closed past the API, the way a card ends anyhow
        conn.execute(update(t.card).where(t.card.c.id == card).values(status=status))
    body = {"summary": "Done.", "pr_status": "none", "code": False}
    refused = expert.post(f"{PROJECT}/tasks/{card}/report", body)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"scope": "tasks:write"}


def test_an_expert_arbiter_moves_its_contract_to_final_and_nothing_else(
    owner: flow.Human, expert: flow.Agent
) -> None:
    """§2.3 "The expert" and §6.8: the arbiter's state move needs no `tasks:write`; every
    other edit of the card still does."""
    created = _card(owner, kind="contract", contract={"arbiter": expert.id})
    assert created.status_code == 201, created.text
    path = f"{PROJECT}/tasks/{created.json()['id']}"
    for body in ({"title": "Mine now"}, {"contract": {"state": "final", "watchers": []}}):
        refused = expert.patch(path, body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"] == {"scope": "tasks:write"}
    final = expert.patch(path, {"contract": {"state": "final"}})
    assert final.status_code == 200, final.text
    assert final.json()["contract"]["state"] == "final"


@pytest.mark.parametrize("entry", ["member", "role:expert"])
def test_an_expert_is_no_substitute(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent, entry: str
) -> None:
    """§6.12: a guest, a proxy or an expert never covers."""
    covered = flow.agent(make_client, owner)
    named = expert.id if entry == "member" else entry
    refused = owner.patch(
        f"{PROJECT}/members/{covered.id}",
        {"availability_policy": {"on_unavailable": "substitute", "substitutes": [named]}},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "availability_policy.substitutes": "expert"
    }


def test_no_takeover_moves_a_card_to_an_expert(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent
) -> None:
    """§6.19: the receiver `to` is never an expert."""
    holder = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert holder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    refused = owner.post(
        f"{PROJECT}/tasks/{card}/takeover", {"reason": "silent for hours", "to": expert.id}
    )
    _invalid(refused, "to")


def test_the_receiver_of_an_open_takeover_does_not_become_an_expert(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """§2.3 "The expert", §6.19: an open takeover would move the card to its receiver."""
    holder = flow.agent(make_client, owner)
    receiver = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert holder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    opened = receiver.post(f"{PROJECT}/tasks/{card}/takeover", {"reason": "silent for hours"})
    assert opened.status_code == 201, opened.text
    changed = owner.patch(f"{PROJECT}/members/{receiver.id}", {"role": "expert"})
    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["details"] == {"reason": "holds_cards"}


def test_a_takeover_to_a_member_that_became_an_expert_moves_nothing(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """§2.3 "The expert", §6.19: the transfer checks the receiver's role when it writes;
    written past the API here, as the role change itself waits for the takeover."""
    holder = flow.agent(make_client, owner)
    receiver = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert holder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    opened = receiver.post(f"{PROJECT}/tasks/{card}/takeover", {"reason": "silent for hours"})
    assert opened.status_code == 201, opened.text
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == receiver.id)
            .values(role="expert", role_base="expert")
        )
    holder.post(f"{PROJECT}/takeovers/{opened.json()['id']}/respond", {"accept": True})
    taken = owner.get(f"{PROJECT}/takeovers/{opened.json()['id']}").json()
    assert taken["status"] == "cancelled"
    held = owner.get(f"{PROJECT}/tasks/{card}").json()
    assert held["claim"]["holder"] == holder.id and held["assigned_to"] != receiver.id
