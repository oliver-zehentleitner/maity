"""docs/api.md §7: forwarding and claiming a decision request; humans_only at every entry."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_requests import _events, answer, ask, asked


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def admin_human(make_client: ClientFactory, migrated: Engine, handle: str) -> flow.Human:
    human = flow.human(make_client, migrated, handle)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=human.id)
    return human


def forward(who: Any, request: dict[str, Any], to: str, **body: Any) -> Any:
    return who.post(f"/projects/maity/requests/{request['id']}/forward", {"to": to, **body})


def claim(who: Any, request: dict[str, Any]) -> Any:
    return who.post(f"/projects/maity/requests/{request['id']}/claim", {})


def reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def field(response: Any, name: str) -> Any:
    return response.json()["error"]["details"]["fields"][name]


def mine(who: Any) -> list[str]:
    return [r["id"] for r in who.get("/projects/maity/requests?to=me").json()["items"]]


def test_the_holder_forwards_to_an_admin_who_then_answers_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin = admin_human(make_client, migrated, "admin")
    request = asked(agent, options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}])
    assert (request["holder"], request["forwarding"], request["humans_only"]) == (
        owner.id,
        [],
        False,
    )
    moved = forward(owner, request, admin.id, reason="yours")
    assert moved.status_code == 200, moved.text
    step = moved.json()["forwarding"]
    assert moved.json()["holder"] == admin.id
    assert [(s["action"], s["from"], s["to"], s["by"], s["reason"]) for s in step] == [
        ("forwarded", owner.id, admin.id, owner.id, "yours")
    ]
    assert request["id"] in mine(admin) and request["id"] not in mine(owner)
    refused = answer(owner, request, reply_id="a")
    assert (refused.status_code, reason(refused)) == (403, "not_request_holder")
    done = answer(admin, request, reply_id="b")
    assert done.status_code == 200, done.text
    assert (done.json()["answer"]["by"], done.json()["answer"]["on_behalf_of"]) == (
        admin.id,
        owner.id,
    )
    [event] = _events(migrated, "request_forwarded")
    assert {f"member:{m}" for m in (agent.id, owner.id, admin.id)} <= set(event.audience)
    with migrated.connect() as conn:
        admin_row = conn.execute(
            select(t.membership).where(t.membership.c.human_id == admin.id)
        ).one()
    assert events.wakes(event, admin_row, admin.id)


def test_what_may_not_be_forwarded(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    member = flow.agent(make_client, owner)
    admin = admin_human(make_client, migrated, "admin")
    request = asked(agent)
    assert reason(forward(admin, request, owner.id)) == "not_request_holder"
    assert field(forward(owner, request, member.id), "to") == "not_admin"
    assert field(forward(owner, request, owner.id), "to") == "self"
    assert field(forward(owner, request, agent.id), "to") == "self"  # the asker
    assert field(forward(owner, request, "hum-nobody"), "to") == "not_a_member"
    info = asked(agent, **{"class": "info"})
    assert field(forward(owner, info, admin.id), "class") == "not_forwardable"
    assert answer(owner, request, text="done").status_code == 200
    closed = forward(owner, request, admin.id)
    assert closed.json()["error"]["code"] == "request_not_open"


def test_opened_to_the_admins_the_first_claim_wins(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin_agent = flow.agent(make_client, owner, role="admin")
    admin = admin_human(make_client, migrated, "admin")
    request = asked(agent)
    opened = forward(owner, request, "role:admin")
    assert opened.json()["holder"] == "role:admin"
    assert opened.json()["forwarding"][0]["action"] == "opened"
    assert request["id"] in mine(admin) and request["id"] in mine(admin_agent)
    [event] = _events(migrated, "request_forwarded")
    with migrated.connect() as conn:
        agent_row = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == admin_agent.id)
        ).one()
    assert not events.wakes(event, agent_row, admin_agent.id)  # it would wake every one
    assert reason(claim(agent, request)) == "not_admin"
    first = claim(admin_agent, request)
    assert first.status_code == 200, first.text
    assert first.json()["holder"] == admin_agent.id
    late = claim(admin, request)
    assert (late.status_code, late.json()["error"]["code"]) == (409, "request_claimed")
    assert late.json()["error"]["details"]["holder"] == admin_agent.id
    assert request["id"] not in mine(admin)
    assert answer(admin_agent, request, text="on it").status_code == 200


def test_humans_only_holds_at_every_entry(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin_agent = flow.agent(make_client, owner, role="admin")
    refused = ask(agent, to=admin_agent.id, humans_only=True)
    assert field(refused, "to") == "humans_only"
    request = asked(agent, humans_only=True)
    assert request["humans_only"] is True
    to_agent = forward(owner, request, admin_agent.id)
    assert (to_agent.status_code, reason(to_agent)) == (403, "humans_only")
    assert forward(owner, request, "role:admin").status_code == 200
    taken = claim(admin_agent, request)
    assert (taken.status_code, reason(taken)) == (403, "humans_only")
    assert claim(owner, request).status_code == 403  # the owner holds no admin role
    admin = admin_human(make_client, migrated, "admin")
    assert claim(admin, request).status_code == 200


def test_a_personal_request_is_never_forwarded(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_personal_requests import _file

    agent = flow.agent(make_client, owner)
    request = {"id": _file(migrated, agent.id)}
    assert forward(owner, request, "role:admin").status_code == 404
    assert claim(owner, request).status_code == 404


def test_a_request_filed_to_the_admins_is_claimed_from_the_start(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The reviewer's first probe: `to: role:admin` is the open pool before any forward."""
    agent = flow.agent(make_client, owner)
    admin = admin_human(make_client, migrated, "admin")
    request = asked(agent, to="role:admin")
    assert request["holder"] == "role:admin"
    claimed = claim(admin, request)
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["holder"] == admin.id
    assert claimed.json()["forwarding"][0]["from"] == "role:admin"


def test_a_forward_back_to_the_owner_named_by_its_token(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The reviewer's second probe: `to: owner`, to an admin, and back to the owner."""
    agent = flow.agent(make_client, owner)
    admin = admin_human(make_client, migrated, "admin")
    request = asked(agent, to="owner")
    assert forward(owner, request, admin.id).status_code == 200
    back = forward(admin, request, owner.id)
    assert back.status_code == 200, back.text
    assert back.json()["holder"] == owner.id


def test_a_demotion_that_commits_first_ends_the_claim(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer's third probe: the admin is demoted right before the lock returns."""
    agent = flow.agent(make_client, owner)
    admin = admin_human(make_client, migrated, "admin")
    request = asked(agent, to="role:admin")
    real = events.lock_project

    def demoted_meanwhile(conn: Any, project: str) -> Any:
        conn.execute(
            t.membership.update().where(t.membership.c.human_id == admin.id).values(role="member")
        )
        return real(conn, project)

    monkeypatch.setattr("maity_hub.routes.requests.lock_project", demoted_meanwhile)
    # A member no longer reads a request to the admins at all: it does not exist for it.
    assert claim(admin, request).status_code == 404
    with migrated.connect() as conn:
        holder = conn.execute(
            select(t.request.c.holder_member).where(t.request.c.id == request["id"])
        ).scalar()
    assert holder is None
