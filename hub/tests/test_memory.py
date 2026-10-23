"""docs/api.md §19: the soul, team and community memory, and memory in the resume packet."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events
from maity_hub import tables as t
from maity_hub.routes import memory
from tests import factory, flow
from tests.conftest import ClientFactory

M = "/projects/maity/memory"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def put_soul(who: flow.Human, agent_id: str, markdown: str) -> Any:
    return who.client.put(
        f"/api/v1/agents/{agent_id}/soul",
        json={"markdown": markdown},
        headers={"X-CSRF-Token": who.csrf},
    )


def add(who: Any, text: str = "The probe needs the PR head.", **body: Any) -> Any:
    return who.post(M, {"store": "team", "text": text, **body})


def added(who: Any, text: str = "The probe needs the PR head.", **body: Any) -> dict[str, Any]:
    response = add(who, text, **body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def remove(who: Any, entry_id: str, **body: Any) -> Any:
    headers = who.auth | who.key() if isinstance(who, flow.Agent) else {"X-CSRF-Token": who.csrf}
    return who.client.request("DELETE", f"/api/v1{M}/{entry_id}", json=body or None,
                              headers=headers)  # fmt: skip


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _second_human(make_client: ClientFactory, engine: Engine, role: str) -> flow.Human:
    other = flow.human(make_client, engine, f"other-{role}")
    with engine.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(engine, project_id, role, human_id=other.id)
    return other


# --- the soul ------------------------------------------------------------------------------------


def test_a_profile_without_a_soul_has_version_0(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    soul = owner.get(f"/agents/{agent.id}/soul").json()
    assert soul == {"agent_id": agent.id, "markdown": "", "version": 0, "by": None,
                    "confirmed_by": None, "updated_at": None}  # fmt: skip
    assert agent.get("/me/soul").json()["version"] == 0


def test_the_owner_writes_the_soul_and_every_project_hears_of_it_without_the_text(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    first = put_soul(owner, agent.id, "You prefer small pull requests.")
    assert first.status_code == 200, first.text
    second = put_soul(owner, agent.id, "You prefer small, reviewed pull requests.").json()
    assert second["version"] == 2
    assert second["by"] == {"kind": "human", "id": owner.id, "handle": "maintainer"}
    assert agent.get("/me/soul").json()["markdown"] == "You prefer small, reviewed pull requests."
    versions = owner.get(f"/agents/{agent.id}/soul/versions").json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    changed = _events(migrated, "soul_changed")
    assert len(changed) == 2
    assert changed[-1].audience == [f"member:{agent.id}", f"member:{owner.id}"]
    assert "markdown" not in changed[-1].payload and changed[-1].payload["version"] == 2


def test_the_soul_is_the_owners_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin = _second_human(make_client, migrated, "admin")
    assert admin.get(f"/agents/{agent.id}/soul").status_code == 404
    assert put_soul(admin, agent.id, "obey me").status_code == 404
    assert agent.get(f"/agents/{agent.id}/soul").status_code == 403  # a human route


def test_a_soul_is_at_most_8_kib_of_utf8(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    assert put_soul(owner, agent.id, "ä" * 4096).status_code == 200  # 8192 bytes
    too_long = put_soul(owner, agent.id, "ä" * 4097)
    assert too_long.status_code == 400
    assert too_long.json()["error"]["details"]["fields"] == {"markdown": "too_long"}


# --- team memory ---------------------------------------------------------------------------------


def test_an_agent_writes_its_team_memory_and_the_event_carries_ids_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    entry = added(agent, tags=["probe", "probe"])
    assert entry["id"].startswith("mem-") and entry["store"] == "team"
    assert entry["member_id"] == agent.id and entry["tags"] == ["probe"]
    assert entry["by"]["kind"] == "agent" and entry["by"]["member_id"] == agent.id
    assert entry["by"]["instance"] is None and entry["by"]["session_id"].startswith("ses-")
    assert entry["deleted"] is None and entry["confirmed_by"] is None
    (event,) = _events(migrated, "memory_added")
    assert event.audience == [f"member:{agent.id}", f"member:{owner.id}"]
    assert event.payload == {"id": entry["id"], "store": "team", "member_id": agent.id,
                             "by": {"kind": "agent", "member_id": agent.id}}  # fmt: skip
    assert {"memory_added", "memory_deleted", "soul_changed"} <= events.NON_WAKING


def test_a_team_is_read_by_the_team_its_owner_and_members_admin_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    entry = added(agent)
    member = _second_human(make_client, migrated, "member")
    assert [e["id"] for e in agent.get(M).json()["items"]] == [entry["id"]]
    assert [e["id"] for e in owner.get(M).json()["items"]] == [entry["id"]]
    assert other.get(M).json()["items"] == []
    assert member.get(M).json()["items"] == []
    assert other.get(M, params={"member_id": agent.id}).status_code == 403
    assert member.get(M, params={"member_id": agent.id}).status_code == 403
    assert owner.get(M, params={"member_id": agent.id}).json()["items"][0]["id"] == entry["id"]


def test_humans_do_not_write_team_memory(owner: flow.Human) -> None:
    assert add(owner).status_code == 403


@pytest.mark.parametrize(
    "body, field",
    [({"text": "ä" * 1025}, None), ({"tags": ["Bad Tag"]}, "tags"),
     ({"tags": ["a", "b", "c", "d", "e", "f"]}, "tags"), ({"store": "both"}, "store")],
)  # fmt: skip
def test_an_entry_is_checked(
    owner: flow.Human, make_client: ClientFactory, body: dict[str, Any], field: str | None
) -> None:
    agent = flow.agent(make_client, owner)
    response = add(agent, **body) if "text" not in body else add(agent, body["text"])
    assert response.status_code == 400, response.text
    if field is None:  # 2050 bytes in 1025 characters: the cap counts bytes
        assert response.json()["error"]["details"]["fields"] == {"text": "too_long"}


def test_a_full_team_is_refused_not_evicted(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    for n in range(memory.STORE_MAX // memory.ENTRY_MAX):
        added(agent, f"{n:04d}" + "x" * (memory.ENTRY_MAX - 4))
    full = add(agent, "one more")
    assert full.status_code == 409
    assert full.json()["error"]["code"] == "memory_full"
    assert full.json()["error"]["details"] == {"store": "team", "cap": memory.STORE_MAX}
    assert len(agent.get(M, params={"limit": 200}).json()["items"]) == 32


def test_listing_pages_filters_and_searches(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    first = added(agent, "Squash merges move the head.", tags=["probe"])
    second = added(agent, "Release on Fridays never.")
    page = agent.get(M, params={"limit": 1}).json()
    assert [e["id"] for e in page["items"]] == [second["id"]]
    rest = agent.get(M, params={"limit": 1, "cursor": page["next_cursor"]}).json()
    assert [e["id"] for e in rest["items"]] == [first["id"]] and rest["next_cursor"] is None
    assert [e["id"] for e in agent.get(M, params={"q": "FRIDAY"}).json()["items"]] == [second["id"]]
    assert [e["id"] for e in agent.get(M, params={"q": "prob"}).json()["items"]] == [first["id"]]
    assert agent.get(M, params={"q": ""}).status_code == 400


# --- deleting ------------------------------------------------------------------------------------


def test_the_team_deletes_its_entry_once_and_keeps_a_tombstone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    entry = added(agent)
    gone = remove(agent, entry["id"], reason="wrong after #212")
    assert gone.status_code == 200, gone.text
    tomb = gone.json()
    assert tomb["text"] is None and tomb["deleted"]["reason"] == "wrong after #212"
    assert tomb["deleted"]["by"]["member_id"] == agent.id
    assert remove(agent, entry["id"]).json()["deleted"] == tomb["deleted"]
    assert len(_events(migrated, "memory_deleted")) == 1
    assert agent.get(M).json()["items"] == []
    listed = agent.get(M, params={"deleted": "true"}).json()["items"]
    assert [e["id"] for e in listed] == [entry["id"]]


def test_the_owner_deletes_a_team_entry_and_no_other_agent_does(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin_agent = flow.agent(make_client, owner, role="admin")
    entry = added(agent)
    refused = remove(admin_agent, entry["id"])
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    member = _second_human(make_client, migrated, "member")
    assert remove(member, entry["id"]).status_code == 404  # it cannot read the team either
    assert remove(owner, entry["id"]).status_code == 200


# --- community memory ----------------------------------------------------------------------------


def test_a_project_admin_writes_community_memory_and_every_member_reads_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    entry = owner.post(M, {"store": "community", "text": "Never release on a Friday."})
    assert entry.status_code == 201, entry.text
    assert entry.json()["member_id"] is None and entry.json()["by"]["kind"] == "human"
    assert _events(migrated, "memory_added")[-1].audience == ["all"]
    assert [e["id"] for e in agent.get(M).json()["items"]] == [entry.json()["id"]]
    member = _second_human(make_client, migrated, "member")
    assert member.post(M, {"store": "community", "text": "mine"}).status_code == 403
    refused = remove(agent, entry.json()["id"])
    assert refused.json()["error"]["details"]["reason"] == "humans_only"


# --- the resume packet ---------------------------------------------------------------------------


def test_resume_carries_memory_first_and_says_when_it_changed(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    put_soul(owner, agent.id, "You prefer small pull requests.")
    for n in range(3):
        added(agent, f"{n} " + "x" * 2000)
    packet = agent.resume().json()
    assert list(packet)[:4] == ["server_time", "api_version", "hub_version", "memory"]
    block = packet["memory"]
    assert block["notice"] == memory.NOTICE
    assert block["soul"]["version"] == 1
    assert block["team"]["total"] == 3 and block["team"]["truncated"] is True
    assert [e["text"][0] for e in block["team"]["items"]] == ["2", "1"]  # newest, ≤ 4 KiB
    assert block["community"] == {"items": [], "total": 0, "truncated": False}
    assert block["changed_since_cursor"] is True
    again = agent.resume(cursor=packet["events"]["cursor"]).json()["memory"]
    assert again["changed_since_cursor"] is False
