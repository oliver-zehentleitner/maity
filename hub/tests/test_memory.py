"""docs/api.md §19: the soul, team and community memory, and memory in the resume packet."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, events, memory
from maity_hub import tables as t
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
    assert changed[-1].actor_membership is not None  # the owner acted through its membership
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
    # A team the caller cannot read does not exist for it (§1.3).
    assert other.get(M, params={"member_id": agent.id}).status_code == 404
    assert member.get(M, params={"member_id": agent.id}).status_code == 404
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
    # Another team's agent, an admin one included, cannot read the entry: `not_found`, so
    # the refusal does not tell it that the entry exists (§1.3).
    assert remove(admin_agent, entry["id"]).status_code == 404
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


def test_the_packet_reads_many_tiny_entries_in_batches(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    for n in range(memory.PACKET_BATCH + 10):  # past one batch, far under 4 KiB
        added(agent, f"e{n}")
    team = agent.resume().json()["memory"]["team"]
    assert team["total"] == memory.PACKET_BATCH + 10 and team["truncated"] is False
    assert len(team["items"]) == team["total"] and team["items"][0]["text"] == "e59"


def test_soul_changed_reaches_every_project_and_the_owner_outside_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    flow.project(owner, "second")
    flow.agent(make_client, owner, "second", agent={"id": agent.id})
    with migrated.begin() as conn:  # the owner leaves the first project
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == owner.id, t.membership.c.role == "owner")
            .where(
                t.membership.c.project_id
                == select(t.project.c.id).where(t.project.c.slug == "maity").scalar_subquery()
            )
            .values(active=None, removed_at=clock.now())
        )
    assert put_soul(owner, agent.id, "two projects").status_code == 200
    changed = _events(migrated, "soul_changed")
    with migrated.connect() as conn:
        slugs = dict(conn.execute(select(t.project.c.id, t.project.c.slug)).all())
    assert sorted(slugs[e.project_id] for e in changed) == ["maity", "second"]
    for event in changed:
        assert event.audience == [f"member:{agent.id}", f"member:{owner.id}"]
    first = next(e for e in changed if slugs[e.project_id] == "maity")
    assert first.actor_membership is None  # no membership there to act through


def _together(calls: list[Any]) -> list[Any]:
    """Run the calls at the same moment: each thread waits at a barrier first. Only a
    server database runs them side by side; SQLite serialises the writers anyway."""
    barrier = threading.Barrier(len(calls))

    def run(call: Any) -> Any:
        barrier.wait()
        return call()

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(run, calls))


def test_concurrent_first_soul_writes_both_count(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """Meaningful on a server database: without the profile lock both writers insert."""
    agent = flow.agent(make_client, owner)
    second = flow.Human(make_client(), owner.csrf, owner.id)
    second.client.cookies.update(owner.client.cookies)
    answers = _together(
        [lambda: put_soul(owner, agent.id, "soul 0"), lambda: put_soul(second, agent.id, "soul 1")]
    )
    assert sorted(a.status_code for a in answers) == [200, 200], [a.text for a in answers]
    assert sorted(a.json()["version"] for a in answers) == [1, 2]
    versions = owner.get(f"/agents/{agent.id}/soul/versions").json()["items"]
    assert [v["version"] for v in versions] == [2, 1]


def test_a_replayed_soul_write_answers_the_version_it_wrote(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    key = {"X-CSRF-Token": owner.csrf, "Idempotency-Key": "soul-replay-key-0001"}
    url = f"/api/v1/agents/{agent.id}/soul"
    first = owner.client.put(url, json={"markdown": "one"}, headers=key)
    put_soul(owner, agent.id, "two")
    again = owner.client.put(url, json={"markdown": "one"}, headers=key)
    assert again.json() == first.json() and again.json()["version"] == 1


def test_a_member_human_reads_and_deletes_its_own_agents_team(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    member = _second_human(make_client, migrated, "member")
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    profile = factory.agent(migrated, project_id, member.id)  # the member's own agent
    agent = flow.agent(make_client, owner)
    others = added(agent)
    mine = _insert_entry(migrated, project_id, profile.membership_id)
    listed = [e["id"] for e in member.get(M).json()["items"]]
    assert listed == [mine]  # its agent's team, not another owner's
    assert remove(member, others["id"]).status_code == 404
    assert remove(member, mine).status_code == 200


def test_an_admin_human_reads_and_deletes_any_team(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    entry = added(agent)
    admin = _second_human(make_client, migrated, "admin")
    assert [e["id"] for e in admin.get(M).json()["items"]] == [entry["id"]]
    assert admin.get(M, params={"member_id": agent.id}).status_code == 200
    assert remove(admin, entry["id"]).status_code == 200


def test_a_member_human_does_not_delete_community_memory(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    entry = owner.post(M, {"store": "community", "text": "Never on a Friday."}).json()
    member = _second_human(make_client, migrated, "member")
    refused = remove(member, entry["id"])
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"scope": "project:admin"}


def test_community_changes_count_in_changed_since_cursor(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    cursor = agent.resume().json()["events"]["cursor"]
    owner.post(M, {"store": "community", "text": "Never on a Friday."})
    assert agent.resume(cursor=cursor).json()["memory"]["changed_since_cursor"] is True


@pytest.mark.parametrize("text", ["   ", "\n\t"])
def test_blank_text_is_refused(owner: flow.Human, make_client: ClientFactory, text: str) -> None:
    agent = flow.agent(make_client, owner)
    refused = add(agent, text)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"text": "blank"}


def test_two_concurrent_adds_at_the_cap_leave_one_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Meaningful on a server database: without the project lock both adds pass the cap.
    Two humans with their own sessions, so that nothing else (one credential's row, one
    session) puts the two writes in a line before the cap check."""
    admin = _second_human(make_client, migrated, "admin")
    for n in range(memory.STORE_MAX // memory.ENTRY_MAX - 1):
        added_by = owner.post(M, {"store": "community",
                                  "text": f"{n:04d}" + "x" * (memory.ENTRY_MAX - 4)})  # fmt: skip
        assert added_by.status_code == 201, added_by.text
    for who in (owner, admin):  # both clients started, so neither lags at the barrier
        assert who.get(M).status_code == 200
    full = {"store": "community", "text": "y" * memory.ENTRY_MAX}
    answers = _together([lambda: owner.post(M, full), lambda: admin.post(M, full)])
    assert sorted(a.status_code for a in answers) == [201, 409]


def _insert_entry(engine: Engine, project_id: str, team: int) -> str:
    with engine.begin() as conn:
        conn.execute(
            insert(t.memory_entry).values(
                id="mem-direct00001", project_id=project_id, store="team",
                team_membership=team, text="written directly", tags=[], by_kind="agent",
                by_membership=team, created_at=clock.now(),
            )
        )  # fmt: skip
    return "mem-direct00001"


def test_an_agents_community_entry_is_a_proposal_a_project_admin_confirms(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    proposed = agent.post(
        M, {"store": "community", "text": "Never on a Friday.", "tags": ["release"]}
    )
    assert proposed.status_code == 202, proposed.text
    request = proposed.json()
    assert request["class"] == "consent" and request["status"] == "open"
    assert request["memory_proposal"] == {"store": "community", "text": "Never on a Friday.",
                                          "tags": ["release"]}  # fmt: skip
    assert agent.get(M).json()["items"] == []  # nothing is stored before the go
    other = flow.agent(make_client, owner, role="admin")
    refused = other.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    go = owner.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    assert go.status_code == 200, go.text
    (entry,) = agent.get(M).json()["items"]
    assert entry["store"] == "community" and entry["text"] == "Never on a Friday."
    assert entry["by"]["member_id"] == agent.id and entry["by"]["session_id"].startswith("ses-")
    assert entry["confirmed_by"]["id"] == owner.id and entry["request_id"] == request["id"]
    assert _events(migrated, "memory_added")[-1].audience == ["all"]


def test_a_refused_or_withdrawn_proposal_stores_nothing(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    first = agent.post(M, {"store": "community", "text": "one"}).json()
    owner.post(f"/projects/maity/requests/{first['id']}/answer", {"reply_id": "no"})
    second = agent.post(M, {"store": "community", "text": "two"}).json()
    agent.post(f"/projects/maity/requests/{second['id']}/withdraw", {"reason": "rethought"})
    assert agent.get(M).json()["items"] == []


def test_only_a_project_admin_gives_the_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request = agent.post(M, {"store": "community", "text": "Never on a Friday."}).json()
    proxy = _second_human(make_client, migrated, "proxy")
    answered = proxy.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    assert answered.status_code == 403, answered.text
    assert agent.get(M).json()["items"] == []
    assert owner.get(f"/projects/maity/requests/{request['id']}").json()["status"] == "open"


def test_a_replay_answers_only_a_caller_who_still_reads_the_entry(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    entry = added(agent)
    admin = _second_human(make_client, migrated, "admin")
    key = {"X-CSRF-Token": admin.csrf, "Idempotency-Key": "memory-replay-key-01"}
    url = f"/api/v1{M}/{entry['id']}"
    first = admin.client.request("DELETE", url, json={"reason": "stale"}, headers=key)
    assert first.status_code == 200, first.text
    with migrated.begin() as conn:  # the admin is an admin no longer
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == admin.id).values(role="member")
        )
    again = admin.client.request("DELETE", url, json={"reason": "stale"}, headers=key)
    assert again.status_code == 404


def test_go_on_a_full_community_store_refuses_and_keeps_the_request_open(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    request = agent.post(M, {"store": "community", "text": "one more"}).json()
    for n in range(memory.STORE_MAX // memory.ENTRY_MAX):
        owner.post(M, {"store": "community", "text": f"{n:04d}" + "x" * (memory.ENTRY_MAX - 4)})
    go = owner.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    assert go.status_code == 409 and go.json()["error"]["code"] == "memory_full"
    assert owner.get(f"/projects/maity/requests/{request['id']}").json()["status"] == "open"


def test_deleting_a_proposed_entry_clears_the_proposals_text(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    request = agent.post(M, {"store": "community", "text": "a secret by mistake"}).json()
    owner.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    (entry,) = agent.get(M).json()["items"]
    assert remove(owner, entry["id"]).status_code == 200
    proposal = owner.get(f"/projects/maity/requests/{request['id']}").json()["memory_proposal"]
    assert proposal["text"] is None and proposal["store"] == "community"


def test_a_proxy_answers_no_answer_at_all(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request = agent.post(M, {"store": "community", "text": "Never on a Friday."}).json()
    proxy = _second_human(make_client, migrated, "proxy")
    for body in ({"reply_id": "no"}, {"text": "rather not"}, {"reply_id": "go"}):
        refused = proxy.post(f"/projects/maity/requests/{request['id']}/answer", body)
        assert refused.status_code == 403, refused.text
    assert owner.get(f"/projects/maity/requests/{request['id']}").json()["status"] == "open"


def test_the_proposed_text_is_in_no_event(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request = agent.post(M, {"store": "community", "text": "the secret word"}).json()
    owner.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    with migrated.connect() as conn:
        payloads = [str(p) for p in conn.execute(select(t.event.c.payload)).scalars()]
    assert not [p for p in payloads if "the secret word" in p]
    shown = owner.get(f"/projects/maity/requests/{request['id']}").json()
    assert shown["memory_proposal"]["text"] == "the secret word"  # only GET shows it
