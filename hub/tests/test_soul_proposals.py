"""Soul proposals are private owner consents, not project memory proposals (§19.1)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_memory import _together, put_soul


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def propose(
    agent: flow.Agent, text: str = "Private proposed soul", reason: str = "Private reason"
) -> Any:
    return agent.post("/me/soul/proposals", {"markdown": text, "reason": reason})


def events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def test_agent_proposes_to_its_owner_and_does_not_write_soul(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    response = propose(agent)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["class"] == "consent" and body["personal"] is True
    assert body["to"] == f"profile_owner:{agent.id}"
    assert body["memory_proposal"] == {
        "store": "soul",
        "agent_id": agent.id,
        "markdown": "Private proposed soul",
        "base_version": 0,
    }
    assert agent.get("/me/soul").json()["version"] == 0
    assert owner.get(f"/requests/{body['id']}").json()["memory_proposal"] == body["memory_proposal"]
    assert [r["id"] for r in owner.get("/requests").json()["items"]] == [body["id"]]


def test_go_writes_agent_provenance_and_owner_confirmation(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request_id = propose(agent).json()["id"]
    response = owner.post(f"/requests/{request_id}/answer", {"reply_id": "go"})
    assert response.status_code == 200, response.text
    soul = agent.get("/me/soul").json()
    assert soul["markdown"] == "Private proposed soul" and soul["version"] == 1
    assert soul["by"]["kind"] == "agent" and soul["by"]["id"] == agent.id
    assert soul["confirmed_by"]["id"] == owner.id
    history = owner.get(f"/agents/{agent.id}/soul/versions").json()["items"]
    assert len(history) == 1 and history[0]["by"] == soul["by"]
    changed = events(migrated, "soul_changed")
    assert len(changed) == 1
    assert changed[0].payload["confirmed_by"] == owner.id
    assert changed[0].payload["by"] == {"kind": "agent", "id": agent.id}


def test_stale_base_is_still_shown_and_go_deliberately_replaces_newer_text(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert put_soul(owner, agent.id, "Original").status_code == 200
    request_id = propose(agent, "Proposal").json()["id"]
    assert put_soul(owner, agent.id, "Newer owner edit").status_code == 200
    view = owner.get(f"/requests/{request_id}").json()
    assert view["memory_proposal"]["base_version"] == 1
    accepted = owner.post(f"/requests/{request_id}/answer", {"reply_id": "go"})
    assert accepted.status_code == 200, accepted.text
    soul = agent.get("/me/soul").json()
    assert soul["markdown"] == "Proposal" and soul["version"] == 3


@pytest.mark.parametrize("action", ["no", "withdraw"])
def test_no_or_owner_withdrawal_leaves_soul_untouched(
    owner: flow.Human, make_client: ClientFactory, action: str
) -> None:
    agent = flow.agent(make_client, owner)
    request_id = propose(agent).json()["id"]
    path = f"/requests/{request_id}/" + ("answer" if action == "no" else "withdraw")
    response = owner.post(path, {"reply_id": "no"} if action == "no" else {})
    assert response.status_code == 200, response.text
    assert agent.get("/me/soul").json()["version"] == 0


def test_private_project_routes_and_other_humans_cannot_read_or_answer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    proxy = flow.agent(make_client, owner, role="proxy")
    other = flow.human(make_client, migrated, "unrelated")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, role="admin", human_id=other.id)
    request_id = propose(agent).json()["id"]
    project_path = f"/projects/maintainer/maity/requests/{request_id}"
    for who in (owner, other, admin, proxy):
        assert who.get(project_path).status_code == 404
        assert who.post(project_path + "/answer", {"reply_id": "go"}).status_code == 404
        assert (
            who.get("/projects/maintainer/maity/requests", params={"to": "all"}).json()["items"]
            == []
        )
    assert other.get(f"/requests/{request_id}").status_code == 404
    assert other.post(f"/requests/{request_id}/answer", {"reply_id": "go"}).status_code == 404
    assert agent.get(project_path).status_code == 200
    assert (
        agent.post(project_path + "/answer", {"reply_id": "go"}).json()["error"]["code"]
        == "self_answer"
    )
    assert agent.post(project_path + "/withdraw", {}).status_code == 404
    # The root personal endpoints refuse every agent identically, even for an unknown id (§2.3).
    for path in (f"/requests/{request_id}", "/requests/req-unknown"):
        assert proxy.get(path).status_code == 403


def test_owner_without_project_membership_can_accept(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside = flow.human(make_client, migrated, "outside")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    stored = factory.agent(migrated, project_id, outside.id)
    agent = flow.Agent(
        make_client(), stored.value, stored.credential_id, stored.agent_id, stored.instance
    )
    request_id = propose(agent).json()["id"]
    assert owner.get(f"/requests/{request_id}").status_code == 404
    assert outside.get(f"/requests/{request_id}").status_code == 200
    accepted = outside.post(f"/requests/{request_id}/answer", {"reply_id": "go"})
    assert accepted.status_code == 200, accepted.text
    soul = outside.get(f"/agents/{agent.id}/soul").json()
    assert soul["confirmed_by"]["id"] == outside.id


def test_events_never_carry_soul_or_reason_or_mentions(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request_id = propose(agent, "Secret soul @maintainer", "Secret reason @maintainer").json()["id"]
    owner.post(f"/requests/{request_id}/answer", {"reply_id": "go", "text": "Private acceptance"})
    for kind in ("request_created", "request_answered"):
        event = events(migrated, kind)[0]
        assert set(event.payload) == {"id", "personal", "status"}
    for kind in ("request_created", "request_answered", "soul_changed"):
        for event in events(migrated, kind):
            encoded = json.dumps(event.payload)
            assert "Secret soul" not in encoded and "Secret reason" not in encoded
            assert "Private acceptance" not in encoded
    with migrated.connect() as conn:
        assert conn.execute(
            select(t.request.c.mentions).where(t.request.c.id == request_id)
        ).scalar() in (None, [])


def test_soul_change_reaches_every_active_project(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    second = factory.project(migrated, "second")
    factory.membership(migrated, second, role="member", agent_id=agent.id)
    request_id = propose(agent).json()["id"]
    assert owner.post(f"/requests/{request_id}/answer", {"reply_id": "go"}).status_code == 200
    changed = events(migrated, "soul_changed")
    assert len(changed) == 2 and second in {e.project_id for e in changed}


def test_replay_keeps_one_private_request_and_original_base(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    headers = agent.auth | {"Idempotency-Key": "soul-proposal-replay-0001"}
    body = {"markdown": "Proposal", "reason": "Reason"}
    first = agent.client.post("/api/v1/me/soul/proposals", json=body, headers=headers)
    assert first.status_code == 202
    put_soul(owner, agent.id, "Owner edit")
    replay = agent.client.post("/api/v1/me/soul/proposals", json=body, headers=headers)
    assert replay.status_code == 202 and replay.json()["id"] == first.json()["id"]
    assert replay.json()["memory_proposal"]["base_version"] == 0
    with migrated.connect() as conn:
        assert len(conn.execute(select(t.request)).all()) == 1


def test_utf8_cap_and_human_refusal(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    assert propose(agent, "ä" * 4096).status_code == 202
    refused = propose(agent, "ä" * 4097)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"markdown": "too_long"}
    assert owner.post("/me/soul/proposals", {"markdown": "x", "reason": "r"}).status_code == 403


@pytest.mark.parametrize(
    "extra", [{"agent_id": "agt-other"}, {"base_version": 99}, {"personal": False}]
)
def test_caller_cannot_choose_target_or_base_or_publicity(
    owner: flow.Human, make_client: ClientFactory, extra: dict[str, Any]
) -> None:
    agent = flow.agent(make_client, owner)
    response = agent.post("/me/soul/proposals", {"markdown": "x", "reason": "r", **extra})
    assert response.status_code == 400


def test_concurrent_owner_write_and_go_both_make_versions(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    request_id = propose(agent, "Proposal text").json()["id"]
    second = flow.Human(make_client(), owner.csrf, owner.id)
    second.client.cookies.update(owner.client.cookies)
    results = _together(
        [
            lambda: put_soul(owner, agent.id, "Owner text"),
            lambda: second.post(f"/requests/{request_id}/answer", {"reply_id": "go"}),
        ]
    )
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    versions = owner.get(f"/agents/{agent.id}/soul/versions").json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert {v["markdown"] for v in versions} == {"Owner text", "Proposal text"}


def test_concurrent_go_from_two_projects_counts_both_versions(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    flow.project(owner, "second")
    sibling = flow.agent(make_client, owner, "second", agent={"id": agent.id})
    first_id = propose(agent, "First project").json()["id"]
    second_id = propose(sibling, "Second project").json()["id"]
    second = flow.Human(make_client(), owner.csrf, owner.id)
    second.client.cookies.update(owner.client.cookies)
    results = _together(
        [
            lambda: owner.post(f"/requests/{first_id}/answer", {"reply_id": "go"}),
            lambda: second.post(f"/requests/{second_id}/answer", {"reply_id": "go"}),
        ]
    )
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    versions = owner.get(f"/agents/{agent.id}/soul/versions").json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert {v["markdown"] for v in versions} == {"First project", "Second project"}
