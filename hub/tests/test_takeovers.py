"""Takeovers within one owner's agents (docs/api.md §6.19)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, takeovers
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def later() -> Iterator[list[timedelta]]:
    """Moves the hub's clock forward by what the test appends."""
    shift = [timedelta()]
    start = clock.now()
    clock.set_source(lambda: start + sum(shift, timedelta()))
    yield shift
    clock.reset()


def _held(owner: flow.Human, holder: flow.Agent) -> str:
    card = owner.post("/projects/maity/tasks", {"title": "A card"})
    assert card.status_code == 201, card.text
    card_id: str = card.json()["id"]
    claimed = holder.post(f"/projects/maity/tasks/{card_id}/claim", {})
    assert claimed.status_code == 200, claimed.text
    return card_id


def _open(who: Any, card_id: str, **body: Any) -> Any:
    return who.post(
        f"/projects/maity/tasks/{card_id}/takeover", {"reason": "silent for hours", **body}
    )


def _expire(engine: Engine, card_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(lease_until=clock.now()))


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _card(owner: flow.Human, card_id: str) -> Any:
    return owner.get(f"/projects/maity/tasks/{card_id}").json()


# --- opening -----------------------------------------------------------------------------


def test_a_takeover_opens_a_window_and_tells_the_holder(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    response = _open(asker, card_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "open" and body["window_minutes"] == 60
    assert body["from"] == {"member_id": holder.id, "instance": holder.instance}
    assert body["to"] == {"member_id": asker.id, "instance": asker.instance}
    assert body["requested_by"] == {
        "kind": "agent",
        "member_id": asker.id,
        "instance": asker.instance,
    }
    opened = _events(migrated, "takeover_opened")[-1]
    assert f"instance:{holder.id}#{holder.instance}" in opened.audience
    assert f"member:{owner.id}" in opened.audience  # the card's creator
    again = _open(asker, card_id)
    assert again.status_code == 409 and again.json()["error"]["code"] == "takeover_open"
    assert again.json()["error"]["details"] == {"takeover": body["id"]}
    listed = asker.get("/projects/maity/takeovers").json()["items"]
    assert [i["id"] for i in listed] == [body["id"]]


def test_accepting_moves_the_card_with_a_fresh_lease(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    takeover = _open(asker, card_id).json()
    path = f"/projects/maity/takeovers/{takeover['id']}"
    stranger = asker.post(f"{path}/respond", {"accept": True})
    assert stranger.status_code == 409 and stranger.json()["error"]["code"] == "not_holder"
    accepted = holder.post(f"{path}/respond", {"accept": True})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "transferred"
    assert accepted.json()["outcome"]["how"] == "accepted"
    card = _card(owner, card_id)
    assert card["claim"]["holder"] == asker.id and card["claim"]["instance"] == asker.instance
    assert card["assigned_to"] == asker.id and card["assigned_instance"] == asker.instance
    claimed = _events(migrated, "task_claimed")[-1]
    assert claimed.payload["takeover_id"] == takeover["id"]
    assert claimed.payload["from"] == {"member_id": holder.id, "instance": holder.instance}
    assert f"instance:{holder.id}#{holder.instance}" in claimed.audience
    assert _events(migrated, "takeover_closed")[-1].payload["status"] == "transferred"
    closed = holder.post(f"{path}/respond", {"accept": True})
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "takeover_closed"
    assert closed.json()["error"]["details"] == {"status": "transferred"}
    assert asker.get("/projects/maity/takeovers").json()["items"] == []
    assert len(asker.get("/projects/maity/takeovers?status=all").json()["items"]) == 1


def test_an_objection_holds_the_card_until_settled(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    path = f"/projects/maity/takeovers/{_open(asker, card_id).json()['id']}"
    objected = holder.post(f"{path}/respond", {"object": {"reasons": "nearly done"}})
    assert objected.status_code == 200, objected.text
    assert objected.json()["status"] == "objected"
    assert objected.json()["objection"]["by"]["kind"] == "agent"
    answered = _events(migrated, "takeover_answered")[-1]
    assert answered.payload["objection"]["reasons"] == "nearly done"
    assert _card(owner, card_id)["claim"]["holder"] == holder.id
    withdrawn = asker.post(f"{path}/withdraw", {"reason": "fair enough"})
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"


def test_the_window_elapsing_transfers_the_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, later: list[timedelta]
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    takeover_id = _open(asker, card_id).json()["id"]
    later.append(timedelta(minutes=61))
    takeovers.sweep(migrated)
    takeovers.sweep(migrated)  # settled once: a second sweep moves nothing
    row = owner.get(f"/projects/maity/takeovers/{takeover_id}").json()
    assert (row["status"], row["outcome"]["how"]) == ("transferred", "window_elapsed")
    assert len(_events(migrated, "takeover_closed")) == 1
    assert _card(owner, card_id)["claim"]["holder"] == asker.id


def test_an_expired_lease_transfers_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    _expire(migrated, card_id)
    response = _open(asker, card_id)
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["outcome"]["how"]) == (
        "transferred",
        "lease_expired",
    )
    assert _card(owner, card_id)["claim"]["holder"] == asker.id


def test_a_human_admins_takeover_is_immediate(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    holder = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    response = _open(owner, card_id)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"]["how"] == "immediate"
    assert response.json()["requested_by"]["kind"] == "human"
    assert _card(owner, card_id)["claim"]["holder"] == owner.id


def test_a_card_a_human_holds_is_never_taken_over(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    card_id = owner.post("/projects/maity/tasks", {"title": "Mine"}).json()["id"]
    assert owner.post(f"/projects/maity/tasks/{card_id}/claim", {}).status_code == 200
    response = _open(admin, card_id)
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "humans_only"
    moved = admin.post(f"/projects/maity/tasks/{card_id}/assign", {"assignee": admin.id})
    assert moved.status_code == 403
    assert moved.json()["error"]["details"]["reason"] == "humans_only"


def test_a_takeover_needs_a_held_card(owner: flow.Human, make_client: ClientFactory) -> None:
    asker = flow.agent(make_client, owner)
    card_id = owner.post("/projects/maity/tasks", {"title": "Free"}).json()["id"]
    response = _open(asker, card_id)
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_claimed"


def test_naming_someone_else_needs_tasks_admin_or_the_lead(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    holder = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    refused = _open(asker, card_id, to=other.id)
    assert refused.status_code == 403, refused.text
    admin = flow.agent(make_client, owner, role="admin")
    assert _open(admin, card_id, to=other.id).status_code == 201


def test_the_lead_moves_a_card_within_its_team(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    lead = flow.agent(make_client, owner)
    path = f"/projects/maity/members/{lead.id}"
    assert owner.patch(path, {"team": {"max_instances": 2}}).status_code == 200
    sibling = flow.agent(make_client, owner, agent={"id": lead.id}, new_instance=True)
    assert owner.patch(path, {"team": {"lead_instance": lead.instance}}).status_code == 200
    card_id = _held(owner, sibling)
    response = _open(lead, card_id, to=f"{lead.id}#{lead.instance}")
    assert response.status_code == 201, response.text
    open_choice = _open(flow.agent(make_client, owner, role="admin"), card_id, to=lead.id)
    assert open_choice.status_code == 409  # one open takeover per card


def test_a_member_id_that_leaves_the_choice_open_is_refused(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    holder = flow.agent(make_client, owner)
    team = flow.agent(make_client, owner)
    path = f"/projects/maity/members/{team.id}"
    assert owner.patch(path, {"team": {"max_instances": 2}}).status_code == 200
    flow.agent(make_client, owner, agent={"id": team.id}, new_instance=True)
    admin = flow.agent(make_client, owner, role="admin")
    response = _open(admin, _held(owner, holder), to=team.id)
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"to": "instance_required"}


# --- the card routes ----------------------------------------------------------------------


def test_an_agent_moves_a_held_card_only_through_a_takeover(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    card_id = _held(owner, holder)
    path = f"/projects/maity/tasks/{card_id}"
    for response in (
        admin.post(f"{path}/assign", {"assignee": admin.id}),
        admin.post(f"{path}/release", {}),
    ):
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "takeover_required"
        assert response.json()["error"]["details"] == {
            "holder": holder.id,
            "instance": holder.instance,
        }
    # After the lease ran out the move is the admin's, and on record as a takeover.
    _expire(migrated, card_id)
    moved = admin.post(f"{path}/assign", {"assignee": admin.id})
    assert moved.status_code == 200, moved.text
    record = admin.get(f"/projects/maity/takeovers?status=all&task_id={card_id}").json()
    (only,) = record["items"]
    assert (only["status"], only["outcome"]["how"]) == ("transferred", "lease_expired")
    assert only["from"]["member_id"] == holder.id and only["to"]["member_id"] == admin.id


def test_an_open_takeover_blocks_an_agents_move(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    takeover_id = _open(asker, card_id).json()["id"]
    _expire(migrated, card_id)  # a lease that runs out later does not end the takeover
    moved = admin.post(f"/projects/maity/tasks/{card_id}/release", {})
    assert moved.status_code == 409 and moved.json()["error"]["code"] == "takeover_open"
    # A human admin's move decides it.
    assert owner.post(f"/projects/maity/tasks/{card_id}/release", {}).status_code == 200
    row = owner.get(f"/projects/maity/takeovers/{takeover_id}").json()
    assert (row["status"], row["outcome"]["how"]) == ("cancelled", "decided")


def test_the_holders_own_release_cancels_the_takeover(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    takeover_id = _open(asker, card_id).json()["id"]
    assert holder.post(f"/projects/maity/tasks/{card_id}/release", {}).status_code == 200
    row = owner.get(f"/projects/maity/takeovers/{takeover_id}").json()
    assert (row["status"], row["outcome"]["how"]) == ("cancelled", "cancelled")


# --- withdraw and override --------------------------------------------------------------------


def test_only_the_requester_withdraws(owner: flow.Human, make_client: ClientFactory) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    path = f"/projects/maity/takeovers/{_open(asker, _held(owner, holder)).json()['id']}"
    assert holder.post(f"{path}/withdraw", {}).status_code == 403
    assert asker.post(f"{path}/withdraw", {}).json()["status"] == "withdrawn"


def test_the_admin_team_overrides_an_open_takeover(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner, role="admin")
    card_id = _held(owner, holder)
    path = f"/projects/maity/takeovers/{_open(asker, card_id).json()['id']}"
    party = asker.post(f"{path}/override", {"reason": "release waits"})
    assert party.status_code == 403
    assert party.json()["error"]["details"]["reason"] == "party_to_takeover"
    member = flow.agent(make_client, owner)
    outside = member.post(f"{path}/override", {"reason": "release waits"})
    assert outside.json()["error"]["details"]["reason"] == "admin_team_only"
    admin = flow.agent(make_client, owner, role="admin")  # same owner as every agent here
    response = admin.post(f"{path}/override", {"reason": "release waits"})
    assert response.status_code == 200, response.text
    assert response.json()["override"]["by"] == admin.id
    assert response.json()["outcome"]["how"] == "override"
    assert _events(migrated, "takeover_overridden")
    assert "role:admin" in _events(migrated, "takeover_closed")[-1].audience


# --- policy ------------------------------------------------------------------------------------


def test_the_window_is_project_policy(owner: flow.Human, make_client: ClientFactory) -> None:
    out = owner.patch(
        "/projects/maity", {"policy": {"takeover_window_minutes": 4}, "reason": "test"}
    )
    assert out.status_code == 400
    changed = owner.patch(
        "/projects/maity", {"policy": {"takeover_window_minutes": 15}, "reason": "test"}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["policy"]["takeover_window_minutes"] == 15
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    assert _open(asker, _held(owner, holder)).json()["window_minutes"] == 15


def test_removing_a_party_cancels_its_takeovers(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    takeover_id = _open(asker, _held(owner, holder)).json()["id"]
    assert owner.delete(f"/projects/maity/members/{asker.id}").status_code == 200
    row = owner.get(f"/projects/maity/takeovers/{takeover_id}").json()
    assert (row["status"], row["outcome"]["how"]) == ("cancelled", "cancelled")


def test_a_replacement_cancels_a_takeover_from_the_replaced_instance(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    holder = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    card_id = _held(owner, holder)
    takeover_id = _open(asker, card_id).json()["id"]
    flow.agent(make_client, owner, agent={"id": holder.id}, replaces=holder.instance)
    row = owner.get(f"/projects/maity/takeovers/{takeover_id}").json()
    assert row["status"] == "cancelled"


def test_a_humans_expired_claim_is_never_taken_over(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    card_id = owner.post("/projects/maity/tasks", {"title": "Mine"}).json()["id"]
    assert owner.post(f"/projects/maity/tasks/{card_id}/claim", {}).status_code == 200
    _expire(migrated, card_id)  # expired or not, a human's card stays theirs (§2.3)
    for who in (admin, owner):
        response = _open(who, card_id)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["details"]["reason"] == "humans_only"
    assert _card(owner, card_id)["claim"]["holder"] == owner.id
