"""Role memory stays with the named role, across authors, instances and role changes (§19)."""

from __future__ import annotations

from typing import Any

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, events, memory
from maity_hub import tables as t
from maity_hub.db import alembic_config, current_revision, downgrade
from maity_hub.errors import ApiError
from tests import factory, flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"
M = f"{BASE}/memory"
REVISION = "20261031121521_role_memory_store"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def add(who: Any, text: str = "A role's shared lesson.", **fields: Any) -> dict[str, Any]:
    response = who.post(M, {"store": "role", "text": text, **fields})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def remove(who: Any, entry: str) -> Any:
    headers = who.auth | who.key() if isinstance(who, flow.Agent) else {"X-CSRF-Token": who.csrf}
    return who.client.request("DELETE", f"/api/v1{M}/{entry}", headers=headers)


def items(who: Any, **params: Any) -> list[dict[str, Any]]:
    response = who.get(M, params={"store": "role", **params})
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()["items"]
    return result


def custom(owner: flow.Human, roles: list[dict[str, str]]) -> Any:
    return owner.client.put(
        f"/api/v1{BASE}/roles", json={"custom": roles}, headers={"X-CSRF-Token": owner.csrf}
    )


def move(owner: flow.Human, agent: flow.Agent, role: str) -> None:
    response = owner.patch(f"{BASE}/members/{agent.id}", {"trust": "member", "role": role})
    assert response.status_code == 200, response.text


def test_role_members_share_entries_and_delete_each_others_entries(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    author, peer = flow.agent(make_client, owner), flow.agent(make_client, owner)
    stranger = flow.agent(make_client, owner, role="writer")
    entry = add(author)
    assert (entry["store"], entry["role"], entry["member_id"]) == ("role", "coder", None)
    assert items(peer)[0]["id"] == entry["id"]
    assert items(stranger) == []
    assert stranger.get(M).json()["items"] == []
    assert stranger.get(M, params={"store": "role", "role": "coder"}).status_code == 404
    assert remove(stranger, entry["id"]).status_code == 404
    deleted = remove(peer, entry["id"])
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["text"] is None
    assert deleted.json()["role"] == "coder"
    assert deleted.json()["deleted"]["by"]["member_id"] == peer.id
    assert items(author) == []
    assert items(author, deleted=True)[0]["id"] == entry["id"]


def test_a_regular_human_writes_their_own_role_without_a_proposal(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    human = flow.human(make_client, migrated, "colleague")
    with migrated.connect() as conn:
        project = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project, "member", human_id=human.id)
    entry = add(human)
    assert entry["role"] == "coder" and entry["by"]["member_id"] == human.id
    assert "instance" not in entry["by"] and entry["request_id"] is None


def test_guests_read_but_never_change_their_roles_memory(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    author = flow.agent(make_client, owner)
    guest = flow.agent(make_client, owner, trust="guest", role="coder")
    entry = add(author)
    assert items(guest)[0]["id"] == entry["id"]
    assert guest.post(M, {"store": "role", "text": "change"}).status_code == 403
    assert remove(guest, entry["id"]).status_code == 403
    assert items(author)[0]["id"] == entry["id"]


def test_owners_and_admin_agents_choose_other_roles_but_a_proxy_does_not(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, trust="admin", role="coder")
    proxy = flow.agent(make_client, owner, trust="admin", role="proxy")
    entry = add(owner, role="writer")
    assert items(admin, role="writer")[0]["id"] == entry["id"]
    another = add(admin, role="writer")
    assert remove(admin, entry["id"]).status_code == 200
    assert proxy.get(M, params={"store": "role", "role": "writer"}).status_code == 404
    assert remove(proxy, another["id"]).status_code == 404
    assert proxy.post(M, {"store": "role", "role": "writer", "text": "override"}).status_code == 403
    own = add(proxy)
    assert own["role"] == "proxy"
    assert [e["id"] for e in proxy.get(M).json()["items"]] == [own["id"]]
    assert items(admin) == []  # an explicit role store defaults to the caller's own
    assert {e["id"] for e in admin.get(M).json()["items"]} == {another["id"], own["id"]}


def test_project_role_memory_keeps_its_name_and_does_not_share_with_its_base(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    assert custom(owner, [{"name": "legal", "base": "coder"}]).status_code == 200
    lawyer = flow.agent(make_client, owner, trust="member", role="legal")
    coder = flow.agent(make_client, owner)
    start = lawyer.resume().json()["events"]["cursor"]
    entry = add(lawyer)
    assert entry["role"] == "legal"
    packet = lawyer.resume(cursor=start).json()["memory"]
    assert packet["changed_since_cursor"] is True
    packet_role = packet["role"]
    assert packet_role["role"] == "legal"
    assert packet_role["items"][0]["id"] == entry["id"]
    assert items(coder) == []
    assert coder.get(M, params={"store": "role", "role": "legal"}).status_code == 404
    assert lawyer.get(M, params={"store": "role", "role": "coder"}).status_code == 404
    move(owner, lawyer, "writer")
    assert lawyer.resume().json()["memory"]["role"] == {
        "role": "writer",
        "items": [],
        "total": 0,
        "truncated": False,
    }
    assert items(owner, role="legal")[0]["id"] == entry["id"]


def test_a_role_change_does_not_leak_the_old_store_through_an_idempotent_replay(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    headers = agent.auth | {"Idempotency-Key": "role-memory-before-role-change"}
    body = {"store": "role", "text": "A coder's private lesson."}
    first = agent.client.post(f"/api/v1{M}", json=body, headers=headers)
    assert first.status_code == 201, first.text
    move(owner, agent, "writer")
    replay = agent.client.post(f"/api/v1{M}", json=body, headers=headers)
    assert replay.status_code == 404, replay.text
    assert "private lesson" not in replay.text
    assert items(owner, role="coder")[0]["id"] == first.json()["id"]


def test_live_role_entries_keep_a_project_role_in_use_but_tombstones_do_not(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    assert custom(owner, [{"name": "legal", "base": "coder"}]).status_code == 200
    author = flow.agent(make_client, owner, trust="member", role="legal")
    entry = add(author)
    move(owner, author, "coder")
    refused = custom(owner, [])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"]["uses"] == ["memory"]
    assert remove(owner, entry["id"]).status_code == 200
    assert custom(owner, []).status_code == 200
    historical = items(owner, role="legal", deleted=True)
    assert historical[0]["role"] == "legal" and historical[0]["text"] is None


def test_a_role_removed_after_validation_cannot_receive_an_orphan_entry(
    owner: flow.Human, migrated: Engine
) -> None:
    assert custom(owner, [{"name": "legal", "base": "coder"}]).status_code == 200
    with migrated.connect() as conn:
        writer = conn.execute(select(t.membership).where(t.membership.c.human_id == owner.id)).one()
    # A request validated "legal", but another request removed it before the write lock.
    assert custom(owner, []).status_code == 200
    with pytest.raises(ApiError) as failed, events.transaction(migrated) as conn:
        memory.add_entry(
            conn,
            writer.project_id,
            memory.Writer(writer, "human", None),
            None,
            "role",
            "Must not outlive its role definition.",
            [],
            role="legal",
        )
    assert failed.value.code == "invalid"
    assert failed.value.details["fields"] == {"role": "unknown"}
    assert owner.get(M).json()["items"] == []


def test_role_memory_is_scoped_to_the_project(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    entry = add(flow.agent(make_client, owner))
    flow.project(owner, "other")
    other = flow.agent(make_client, owner, slug="other")
    path = "/projects/maintainer/other/memory"
    assert other.get(path, params={"store": "role"}).json()["items"] == []
    assert (
        other.client.request(
            "DELETE", f"/api/v1{path}/{entry['id']}", headers=other.auth | other.key()
        ).status_code
        == 404
    )


def test_role_entries_record_the_instance_and_events_only_ids(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    entry = add(agent, "Private words.", tags=["private"])
    assert entry["by"]["instance"] == agent.instance
    assert entry["by"]["session_id"].startswith("ses-")
    with migrated.connect() as conn:
        event = conn.execute(select(t.event).where(t.event.c.kind == "memory_added")).one()
    assert event.audience == ["role:coder"]
    assert event.payload == {
        "id": entry["id"],
        "store": "role",
        "member_id": None,
        "role": "coder",
        "by": {"kind": "agent", "member_id": agent.id},
    }
    assert event.kind in events.NON_WAKING


def test_role_caps_are_shared_by_authors_but_independent_of_other_stores(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    author, peer = flow.agent(make_client, owner), flow.agent(make_client, owner)
    text = "ä" * (memory.ENTRY_MAX // 2)
    entries = [add(author, text) for _ in range(memory.STORE_MAX // memory.ENTRY_MAX)]
    full = peer.post(M, {"store": "role", "text": "one more"})
    assert full.status_code == 409, full.text
    assert full.json()["error"]["details"] == {"store": "role", "cap": 65536}
    assert add(owner, text, role="writer")["role"] == "writer"
    assert author.post(M, {"store": "team", "text": text}).status_code == 201
    assert owner.post(M, {"store": "community", "text": text}).status_code == 201
    assert remove(peer, entries[0]["id"]).status_code == 200
    assert add(peer, text)["role"] == "coder"


def test_each_packet_store_has_its_own_compact_budget(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    for n in range(3):
        text = f"{n} " + "ä" * 1000
        add(agent, text)
        assert agent.post(M, {"store": "team", "text": text}).status_code == 201
        assert owner.post(M, {"store": "community", "text": text}).status_code == 201
    block = agent.resume().json()["memory"]
    assert block["role"]["role"] == "coder"
    for name in ("team", "role", "community"):
        store = block[name]
        assert store["total"] == 3 and store["truncated"] is True
        assert [e["text"][0] for e in store["items"]] == ["2", "1"]
        assert sum(memory.size(e["text"]) for e in store["items"]) <= 4096
    assert block["notice"] == memory.NOTICE


def test_role_change_flags_follow_the_members_current_role(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent, peer = flow.agent(make_client, owner), flow.agent(make_client, owner)
    writer = flow.agent(make_client, owner, role="writer")
    start = agent.resume().json()["events"]["cursor"]
    add(writer)
    unaffected = agent.resume(cursor=start).json()
    assert unaffected["memory"]["changed_since_cursor"] is False
    entry = add(peer)
    changed = agent.resume(cursor=unaffected["events"]["cursor"]).json()
    assert changed["memory"]["changed_since_cursor"] is True
    assert remove(peer, entry["id"]).status_code == 200
    deleted = agent.resume(cursor=changed["events"]["cursor"]).json()
    assert deleted["memory"]["changed_since_cursor"] is True
    assert deleted["memory"]["role"]["total"] == 0
    assert (
        agent.resume(cursor=deleted["events"]["cursor"]).json()["memory"]["changed_since_cursor"]
        is False
    )


def test_role_selectors_are_only_used_for_role_memory(owner: flow.Human) -> None:
    wrong = owner.post(M, {"store": "community", "role": "coder", "text": "wrong store"})
    assert wrong.status_code == 400
    assert wrong.json()["error"]["details"]["fields"] == {"role": "role_only"}
    assert owner.get(M, params={"role": "coder"}).status_code == 400
    assert owner.get(M, params={"store": "role", "member_id": owner.id}).status_code == 400
    unknown = owner.post(M, {"store": "role", "role": "missing", "text": "wrong role"})
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["fields"] == {"role": "unknown"}


@pytest.mark.parametrize(
    ("store", "role"), [("role", None), ("community", "coder"), ("team", "coder")]
)
def test_the_database_keeps_the_three_store_shapes_distinct(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, store: str, role: str | None
) -> None:
    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        member = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()
    with pytest.raises(IntegrityError), migrated.begin() as conn:
        conn.execute(
            insert(t.memory_entry).values(
                id="mem-invalid-shape",
                project_id=member.project_id,
                store=store,
                team_membership=member.id if store == "team" else None,
                role=role,
                text="invalid shape",
                tags=[],
                by_kind="agent",
                by_membership=member.id,
                created_at=clock.now(),
            )
        )


def test_downgrade_refuses_to_discard_role_memory_history(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    entry = add(agent)
    assert remove(agent, entry["id"]).status_code == 200
    before = ScriptDirectory.from_config(alembic_config(migrated)).get_revision(REVISION)
    assert before is not None and isinstance(before.down_revision, str)
    with pytest.raises(RuntimeError, match="role memory history"):
        downgrade(migrated, before.down_revision)
    assert current_revision(migrated) == REVISION
    with migrated.connect() as conn:
        history = conn.execute(
            select(t.memory_entry.c.role, t.memory_entry.c.text).where(
                t.memory_entry.c.id == entry["id"]
            )
        ).one()
    assert history.role == "coder" and history.text is None
