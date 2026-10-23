"""docs/api.md §7, personal requests: the hub's requests to the human who owns an agent
profile, member of the project or not, kept out of the project's request routes."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth.caller import Caller
from maity_hub.events import transaction
from maity_hub.routes.requests import close_request, file_personal
from tests import factory, flow
from tests.conftest import ClientFactory

R = "/projects/maity/requests"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


def _file(engine: Engine, agent_id: str, **kwargs: Any) -> str:
    """What a soul proposal or a takeover notice will do: the hub files it for the agent."""
    with transaction(engine) as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent_id)).one()
        caller = Caller(kind="agent", via="bearer", agent_id=agent_id,
                        membership_id=row.id, project_id=row.project_id)  # fmt: skip
        mine = membership(conn, caller, "maity")
        return file_personal(conn, mine, caller, agent_id, "consent", "May my soul read so?",
                             "the proposed text", **kwargs)  # fmt: skip


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _outside_owner(make_client: ClientFactory, engine: Engine) -> tuple[flow.Human, str]:
    """A human with an agent in the project who is no member of it (§6.2)."""
    outside = flow.human(make_client, engine, "outside")
    with engine.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    return outside, factory.agent(engine, project_id, outside.id).agent_id


def test_the_project_routes_never_show_it_to_anyone_but_the_asker(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, agent.id)
    for who in (owner, admin):
        assert who.get(R, params={"to": "all", "status": "all"}).json()["items"] == []
        assert who.get(f"{R}/{request_id}").status_code == 404
        assert who.post(f"{R}/{request_id}/answer", {"reply_id": "go"}).status_code == 404
        assert who.post(f"{R}/{request_id}/withdraw", {}).status_code == 404
    mine = agent.get(f"{R}/{request_id}")
    assert mine.status_code == 200 and mine.json()["personal"] is True
    assert mine.json()["to"] == f"profile_owner:{agent.id}"
    assert agent.post(f"{R}/{request_id}/answer", {"reply_id": "go"}).json()["error"][
        "code"] == "self_answer"  # fmt: skip
    assert (
        agent.post(f"{R}/{request_id}/withdraw", {}).status_code == 404
    )  # the hub's, or its human's
    assert admin.resume().json()["requests"]["to_answer"] == []


def test_its_events_carry_ids_and_status_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request_id = _file(migrated, agent.id)
    (created,) = _events(migrated, "request_created")
    assert created.payload == {"id": request_id, "personal": True, "status": "open"}
    assert created.audience == [f"member:{agent.id}", f"member:{owner.id}"]  # owner is a member
    owner.post(f"/requests/{request_id}/answer", {"reply_id": "go", "text": "yes, keep it"})
    (answered,) = _events(migrated, "request_answered")
    assert answered.payload == {"id": request_id, "personal": True, "status": "answered"}


def test_an_owner_outside_the_project_reads_and_answers_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside, agent_id = _outside_owner(make_client, migrated)
    request_id = _file(migrated, agent_id)
    (created,) = _events(migrated, "request_created")
    assert created.audience == [f"member:{agent_id}"]  # the owner is no member here
    inbox = outside.get("/requests").json()["items"]
    assert [(i["id"], i["personal"], i["project"]["slug"]) for i in inbox] == [
        (request_id, True, "maity")]  # fmt: skip
    view = outside.get(f"/requests/{request_id}").json()
    assert view["status"] == "open" and view["project"]["slug"] == "maity"
    assert owner.get(f"/requests/{request_id}").status_code == 404  # not addressed to it
    answered = outside.post(f"/requests/{request_id}/answer", {"reply_id": "go"})
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"]["by"] == outside.id
    with migrated.connect() as conn:
        row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
    assert row.answered_by is None  # no membership to record
    assert outside.get(f"/requests/{request_id}").json()["status"] == "answered"
    again = outside.post(f"/requests/{request_id}/answer", {"reply_id": "no"})
    assert again.json()["error"]["code"] == "request_not_open"


def test_its_human_withdraws_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside, agent_id = _outside_owner(make_client, migrated)
    request_id = _file(migrated, agent_id)
    gone = outside.post(f"/requests/{request_id}/withdraw", {"reason": "not now"})
    assert gone.status_code == 200 and gone.json()["status"] == "withdrawn"
    assert _events(migrated, "request_withdrawn")[-1].payload == {
        "id": request_id, "personal": True, "status": "withdrawn"}  # fmt: skip
    assert outside.get("/requests").json()["items"] == []  # open ones by default
    assert len(outside.get("/requests", params={"status": "all"}).json()["items"]) == 1


def test_a_closed_one_keeps_its_card_as_it_was(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside, agent_id = _outside_owner(make_client, migrated)
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent_id)
        ).scalar_one()
    card = factory.card(migrated, project_id, member, title="Before")
    request_id = _file(migrated, agent_id, task_id=card)
    with transaction(migrated) as conn:
        close_request(conn, request_id, "withdrawn", None, reason="the takeover closed")
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card).values(title="After"))
    view = outside.get(f"/requests/{request_id}").json()
    assert view["status"] == "withdrawn" and view["task"]["title"] == "Before"
    assert _events(migrated, "request_withdrawn")[-1].payload["personal"] is True


def test_nobody_else_answers_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _outside, agent_id = _outside_owner(make_client, migrated)
    request_id = _file(migrated, agent_id)
    other = flow.human(make_client, migrated, "stranger")
    assert other.get(f"/requests/{request_id}").status_code == 404
    assert other.post(f"/requests/{request_id}/answer", {"reply_id": "go"}).status_code == 404
    assert other.post(f"/requests/{request_id}/withdraw", {}).status_code == 404
    agent = flow.agent(make_client, owner)
    assert agent.get(f"/requests/{request_id}").status_code == 403  # a human route


def test_a_caller_cannot_address_one(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    refused = agent.post(R, {"class": "decision", "title": "x", "to": f"profile_owner:{agent.id}"})
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"to": "hub_only"}


def test_the_asker_finds_the_answer_in_its_resume(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    cursor = agent.resume().json()["events"]["cursor"]
    request_id = _file(migrated, agent.id)
    owner.post(f"/requests/{request_id}/answer", {"reply_id": "go"})
    answered = agent.resume(cursor=cursor).json()["requests"]["answered_since_cursor"]
    assert [(r["id"], r["answer"]["reply_id"]) for r in answered] == [(request_id, "go")]
