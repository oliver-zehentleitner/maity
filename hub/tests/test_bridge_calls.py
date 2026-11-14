"""docs/api.md §2.3, "The bridge": a bridge calls as the agent it serves with `Maity-For`, and
the hub records it as `via` (tsk-emy3a9vtqxym)."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from typing import Any

import pytest
from fastapi.routing import iter_route_contexts
from sqlalchemy import Engine, select, update

from maity_hub import bridges, clock
from maity_hub import tables as t
from maity_hub.auth import credentials
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
API = "/api/v1"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _pair(
    engine: Engine, owner: flow.Human, trust: str | None = None
) -> tuple[factory.Agent, factory.Agent, str]:
    """The served agent, its bridge (both the owner's) and the connection's id."""
    served = factory.agent(engine, _project(engine), owner.id, "coder", trust=trust)
    bridge = factory.agent(engine, _project(engine), owner.id, "coder", instance="brg1")
    made = owner.post(
        f"{PROJECT}/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "git for the designer"},
    )
    assert made.status_code == 201, made.text
    return served, bridge, made.json()["id"]


class Calls:
    """A bridge's calls over bearer, with or without `Maity-For`."""

    def __init__(self, client: Any, agent: factory.Agent) -> None:
        self.client, self.agent, self.n = client, agent, 0

    def headers(self, served: str | None) -> dict[str, str]:
        self.n += 1
        headers = {
            "Authorization": f"Bearer {self.agent.value}",
            "Idempotency-Key": f"bridge-{self.agent.credential_id}-{self.n:06d}",
        }
        if served is not None:
            headers["Maity-For"] = served
        return headers

    def get(self, path: str, served: str | None = None) -> Any:
        return self.client.get(f"{API}{path}", headers=self.headers(served))

    def post(self, path: str, body: Any, served: str | None = None) -> Any:
        return self.client.post(f"{API}{path}", json=body, headers=self.headers(served))

    def send(self, method: str, path: str, body: Any = None, served: str | None = None) -> Any:
        return self.client.request(method, f"{API}{path}", json=body, headers=self.headers(served))


def _say(calls: Calls, served: str | None, body: str = "hello") -> Any:
    return calls.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": "all", "body": body},
        served,
    )


def _reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def test_the_canonical_string_carries_the_for_line_before_the_body_hash() -> None:
    plain = credentials.canonical_string("get", b"/api/v1/x", b"", "1792000000", "n" * 22, b"")
    carried = credentials.canonical_string(
        "get", b"/api/v1/x", b"", "1792000000", "n" * 22, b"", "agt-served"
    )
    lines = carried.split("\n")
    assert len(lines) == 8 and lines[6] == "for:agt-served"
    assert lines[:6] + lines[7:] == plain.split("\n")


def test_a_signed_call_signs_the_header(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner)
    path = f"{API}{PROJECT}/members/{served.agent_id}"

    def signed(lines_for: str | None, header: str | None) -> Any:
        secret = bridge.value.split(".")[2]
        key = hashlib.sha256(secret.encode()).digest()
        stamp, nonce = str(int(clock.now().timestamp())), secrets.token_urlsafe(16)
        canonical = credentials.canonical_string(
            "GET", path.encode(), b"", stamp, nonce, b"", lines_for
        )
        headers = {
            "Authorization": f"Maity-HMAC {bridge.credential_id}",
            "Maity-Timestamp": stamp,
            "Maity-Nonce": nonce,
            "Maity-Signature": hmac.new(key, canonical.encode(), "sha256").hexdigest(),
        }
        if header is not None:
            headers["Maity-For"] = header
        return make_client().get(path, headers=headers)

    assert signed(served.agent_id, served.agent_id).status_code == 200
    added = signed(None, served.agent_id)  # the header added to a request signed without it
    assert added.headers["Maity-Error"] == "signature_invalid"
    stripped = signed(served.agent_id, None)
    assert stripped.headers["Maity-Error"] == "signature_invalid"


def test_a_message_for_the_served_agent_is_its_own_with_the_bridge_as_via(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, bridge_id = _pair(migrated, owner)
    calls = Calls(make_client(), bridge)
    sent = _say(calls, served.agent_id)
    assert sent.status_code == 201, sent.text
    via = {"member_id": bridge.agent_id, "instance": "brg1", "bridge_id": bridge_id}
    [item] = owner.get(f"{PROJECT}/messages").json()["items"]
    assert item["from"] == served.agent_id and item["via"] == via
    events = owner.get(f"{PROJECT}/events").json()["items"]
    [message] = [e for e in events if e["kind"] == "message"]
    assert message["actor"]["member_id"] == served.agent_id and message["actor"]["via"] == via
    own = _say(calls, None, "mine")  # without the header the bridge acts as itself
    assert own.status_code == 201, own.text
    mine = owner.get(f"{PROJECT}/messages").json()["items"][0]
    assert mine["from"] == bridge.agent_id and "via" not in mine


def test_a_card_written_for_the_served_agent_shows_via_in_its_history(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, bridge_id = _pair(migrated, owner)
    calls = Calls(make_client(), bridge)
    made = calls.post(f"{PROJECT}/tasks", {"title": "Carry the files"}, served.agent_id)
    assert made.status_code == 201, made.text
    assert made.json()["created_by"] == served.agent_id
    history = owner.get(f"{PROJECT}/tasks/{made.json()['id']}/history").json()["items"]
    assert history and all(e["actor"]["via"]["bridge_id"] == bridge_id for e in history)


def test_an_answer_given_for_the_served_agent_names_the_bridge(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, bridge_id = _pair(migrated, owner)
    asked = owner.post(
        f"{PROJECT}/requests", {"class": "decision", "title": "Which?", "to": served.agent_id}
    )
    assert asked.status_code == 201, asked.text
    calls = Calls(make_client(), bridge)
    done = calls.post(
        f"{PROJECT}/requests/{asked.json()['id']}/answer", {"text": "the first"}, served.agent_id
    )
    assert done.status_code == 200, done.text
    answer = done.json()["answer"]
    assert answer["by"] == served.agent_id and answer["via"]["bridge_id"] == bridge_id


def test_a_header_naming_an_agent_it_does_not_serve_is_refused(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner)
    stranger = factory.agent(migrated, _project(migrated), owner.id, "coder")
    calls = Calls(make_client(), bridge)
    refused = _say(calls, stranger.agent_id)
    assert (refused.status_code, _reason(refused)) == (403, "not_your_bridge")
    back = Calls(make_client(), served)  # the connection has a direction
    refused = _say(back, bridge.agent_id)
    assert (refused.status_code, _reason(refused)) == (403, "not_your_bridge")
    human = owner.client.post(
        f"{API}{PROJECT}/events",
        json={"kind": "message", "type": "notice", "to": "all", "body": "x"},
        headers={"Maity-For": served.agent_id, "X-CSRF-Token": owner.csrf},
    )
    assert _reason(human) == "not_your_bridge"


def test_the_header_is_taken_on_project_routes_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner)
    calls = Calls(make_client(), bridge)
    refused = calls.get("/me", served.agent_id)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"Maity-For": "route"}


def test_the_header_is_not_taken_on_the_memory_or_the_connections(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.3: the memory stores are the served agent's own, as its soul is, and a bridge makes,
    changes or ends no connection in the served agent's name. Nothing is written."""
    served, bridge, connection = _pair(migrated, owner)
    other = factory.agent(migrated, _project(migrated), owner.id, "coder", instance="brg2")
    calls = Calls(make_client(), bridge)
    entry = {"store": "team", "text": "written as the served agent"}
    for method, path, body in (
        ("GET", f"{PROJECT}/memory?store=team", None),
        ("POST", f"{PROJECT}/memory", entry),
        ("POST", f"{PROJECT}/memory", {"store": "role", "text": "x"}),
        ("POST", f"{PROJECT}/memory", {"store": "community", "text": "x"}),
        ("DELETE", f"{PROJECT}/memory/mem-000000000000", None),
        (
            "POST",
            f"{PROJECT}/members/{served.agent_id}/bridges",
            {"bridge": other.agent_id, "purpose": "x"},
        ),
        ("PATCH", f"{PROJECT}/members/{served.agent_id}/bridges/{connection}", {"purpose": "y"}),
        ("DELETE", f"{PROJECT}/members/{served.agent_id}/bridges/{connection}", None),
    ):
        refused = calls.send(method, path, body, served.agent_id)
        assert refused.status_code == 400, (method, path, refused.text)
        assert refused.json()["error"]["details"]["fields"] == {"Maity-For": "route"}
    with migrated.connect() as conn:
        assert conn.execute(select(t.memory_entry)).first() is None
        assert conn.execute(select(t.request)).first() is None
        live = conn.execute(select(t.bridge.c.id).where(t.bridge.c.live.is_(True))).scalars().all()
    assert live == [connection]
    # Without the header the bridge is itself: its own memory, as its own role allows.
    own = calls.send("POST", f"{PROJECT}/memory", entry)
    assert own.status_code == 201, own.text
    assert own.json()["by"]["member_id"] == bridge.agent_id


def test_every_memory_and_connection_route_refuses_the_header(client: Any) -> None:
    """A guard (§2.3): a route added under `…/memory` or `…/members/{id}/bridges` is refused for
    `Maity-For` as well, by the path alone, whatever its method."""
    paths = {
        route.path_format
        for route in iter_route_contexts(list(client.app.routes))
        if route.path_format is not None and route.path_format.startswith(f"{API}/projects/")
    }
    guarded = [
        p for p in paths if re.search(r"/\{slug\}/(memory|members/\{[^}]+\}/bridges)(/|$)", p)
    ]
    assert len(guarded) >= 4, guarded  # two paths each, one per method or more
    for path in guarded:
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        assert bridges._never_carried(concrete), path
    # and the other project routes are not caught by it
    assert not bridges._never_carried(f"{API}/projects/x/x/events")
    assert not bridges._never_carried(f"{API}/projects/x/x/members/x")


def test_a_write_through_a_connection_ended_meanwhile_is_refused(
    owner: flow.Human, migrated: Engine
) -> None:
    """§2.3: the connection is read live when the call is carried, before the route runs; an
    ending that commits in between, under the project's lock, refuses the write that follows
    (S124). The write waits on the lock the ending holds, then reads the connection again."""
    import threading

    from maity_hub import bridges, events
    from maity_hub.errors import ApiError

    served, bridge, connection = _pair(migrated, owner)
    project_id = _project(migrated)
    with migrated.connect() as conn:
        served_row = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == served.agent_id)
        ).scalar_one()
    carried = events.Actor(
        served_row,
        bridge={"member_id": bridge.agent_id, "instance": "brg1", "bridge_id": connection},
    )
    ending, written = threading.Event(), threading.Event()
    outcome: list[str] = []

    def end() -> None:
        with events.transaction(migrated) as conn:
            events.lock_project(conn, project_id)
            row = conn.execute(select(t.bridge).where(t.bridge.c.id == connection)).one()
            bridges.end(conn, row, None)
            ending.set()
            written.wait(timeout=2)  # the write is held on the lock until this commits

    def write() -> None:
        ending.wait()
        try:
            with events.transaction(migrated) as conn:
                written.set()
                events.emit(
                    conn,
                    project_id,
                    "message",
                    ["all"],
                    {"type": "notice", "body": "through an ended bridge"},
                    actor=carried,
                )
            outcome.append("written")
        except ApiError as error:
            outcome.append(error.details["reason"])

    threads = [threading.Thread(target=end), threading.Thread(target=write)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcome == ["not_your_bridge"]
    with migrated.connect() as conn:
        bodies = conn.execute(select(t.event.c.payload)).scalars().all()
    assert not any("through an ended bridge" in str(body) for body in bodies)


def test_a_bridge_calls_under_no_governance_scope(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner, trust="admin")
    calls = Calls(make_client(), bridge)
    item = {"type": "note", "text": "Staging is down.", "areas": ["hub/"]}
    refused = calls.post(f"{PROJECT}/ticker", item, served.agent_id)
    assert (refused.status_code, _reason(refused)) == (403, "bridge_no_governance")
    itself = Calls(make_client(), served).post(f"{PROJECT}/ticker", item)
    assert itself.status_code == 201, itself.text  # the served agent holds the scope
    view = calls.get(f"{PROJECT}/members/{served.agent_id}", served.agent_id)
    assert view.status_code == 200  # reading as the served agent stays open


def test_an_isolated_served_agent_is_refused_and_keeps_its_bridge(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == served.membership_id)
            .values(isolated_since=clock.now(), isolated_reason="test", isolated_by="hub")
        )
    calls = Calls(make_client(), bridge)
    refused = _say(calls, served.agent_id)
    assert (refused.status_code, _reason(refused)) == (403, "isolated")
    with migrated.connect() as conn:
        assert conn.execute(select(t.bridge)).first() is not None


def test_a_claim_through_the_bridge_is_the_served_agents_without_an_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, bridge_id = _pair(migrated, owner)
    card = owner.post(f"{PROJECT}/tasks", {"title": "Carry the files"}).json()["id"]
    calls = Calls(make_client(), bridge)
    claimed = calls.post(f"{PROJECT}/tasks/{card}/claim", {}, served.agent_id)
    assert claimed.status_code == 200, claimed.text
    with migrated.connect() as conn:
        row = conn.execute(select(t.card).where(t.card.c.id == card)).one()
    assert (row.claim_holder, row.claim_instance) == (served.membership_id, None)
    events = owner.get(f"{PROJECT}/events").json()["items"]
    [event] = [e for e in events if e["kind"] == "task_claimed"]
    assert event["actor"]["instance"] is None
    assert event["actor"]["via"] == {
        "member_id": bridge.agent_id,
        "instance": "brg1",
        "bridge_id": bridge_id,
    }
    released = calls.post(f"{PROJECT}/tasks/{card}/release", {}, served.agent_id)
    assert released.status_code == 200, released.text  # the holder, through its bridge


def test_a_bridge_writes_no_chat_into_the_direct_conversation(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner)
    calls = Calls(make_client(), bridge)
    chat = {"kind": "message", "type": "chat", "conversation_id": served.agent_id, "body": "x"}
    refused = calls.post(f"{PROJECT}/events", chat, served.agent_id)
    assert (refused.status_code, _reason(refused)) == (403, "bridge_observer")
    refused = calls.post(
        f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "x"}, served.agent_id
    )
    assert (refused.status_code, _reason(refused)) == (403, "bridge_observer")


def test_an_ended_connection_carries_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, bridge_id = _pair(migrated, owner)
    ended = owner.delete(f"{PROJECT}/members/{served.agent_id}/bridges/{bridge_id}")
    assert ended.status_code == 200, ended.text
    refused = _say(Calls(make_client(), bridge), served.agent_id)
    assert (refused.status_code, _reason(refused)) == (403, "not_your_bridge")


def test_a_call_through_the_bridge_renews_what_it_holds_for_the_served_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner)
    card = owner.post(f"{PROJECT}/tasks", {"title": "Carry the files"}).json()["id"]
    calls = Calls(make_client(), bridge)
    assert calls.post(f"{PROJECT}/tasks/{card}/claim", {}, served.agent_id).status_code == 200
    past = clock.now() - timedelta(hours=1)
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card).values(lease_until=past))
    assert calls.get(f"{PROJECT}/members/{served.agent_id}", served.agent_id).status_code == 200
    with migrated.connect() as conn:
        renewed = conn.execute(select(t.card.c.lease_until).where(t.card.c.id == card)).scalar()
    assert renewed is not None and renewed > clock.now()
