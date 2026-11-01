"""docs/api.md §2.3, "The bridge": what a bridge reads for the agents it serves — their events
with `for`, their direct conversation — and the presence it lends them (tsk-emy3a9vtqxym)."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, longpoll
from maity_hub import tables as t
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
    engine: Engine, owner: flow.Human, *, served_session: bool = True, instance: str = "wk2e"
) -> tuple[factory.Agent, factory.Agent]:
    served = factory.agent(
        engine, _project(engine), owner.id, "coder", with_session=served_session, instance=instance
    )
    bridge = factory.agent(engine, _project(engine), owner.id, "coder", instance="brg1")
    made = owner.post(
        f"{PROJECT}/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "git for the designer"},
    )
    assert made.status_code == 201, made.text
    return served, bridge


def _get(client: Any, agent: factory.Agent, path: str, served: str | None = None) -> Any:
    headers = {"Authorization": f"Bearer {agent.value}"}
    if served is not None:
        headers["Maity-For"] = served
    return client.get(f"{API}{path}", headers=headers)


def _tell(owner: flow.Human, to: str, body: str = "for you") -> int:
    sent = owner.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": to, "body": body}
    )
    assert sent.status_code == 201, sent.text
    seq: int = sent.json()["seq"]
    return seq


def _seqs(response: Any) -> list[int]:
    assert response.status_code == 200, response.text
    return [e["seq"] for e in response.json()["items"]]


def test_for_reads_what_the_served_agent_reads_and_moves_no_cursor(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    seq = _tell(owner, served.agent_id)
    chat = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "hi"})
    assert chat.status_code == 201, chat.text
    client = make_client()
    read_for = _seqs(_get(client, bridge, f"{PROJECT}/events?for={served.agent_id}"))
    assert seq in read_for and chat.json()["seq"] in read_for
    assert seq not in _seqs(_get(client, bridge, f"{PROJECT}/events"))  # not its own
    read = _get(client, bridge, f"{PROJECT}/events?for={served.agent_id}&after={seq}")
    assert read.status_code == 200, read.text
    with migrated.connect() as conn:
        acknowledged = conn.execute(
            select(t.agent_session.c.acknowledged_seq).where(
                t.agent_session.c.id == bridge.session_id
            )
        ).scalar()
        delivered = conn.execute(select(t.message_delivery)).first()
    assert acknowledged == 0 and delivered is None  # nothing reached the served agent


def test_the_long_poll_with_for_answers_the_served_agents_wake(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    seq = _tell(owner, served.agent_id)
    waited = _get(make_client(), bridge, f"{PROJECT}/events?for={served.agent_id}&wait=1")
    assert seq in _seqs(waited)


def test_a_wait_for_an_agent_and_the_bridges_own_stand_beside_each_other(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    client = make_client()
    events = f"{PROJECT}/events?after=latest"
    mine_at = _get(client, bridge, events).json()["cursor"]
    for_at = _get(client, bridge, f"{events}&for={served.agent_id}").json()["cursor"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        own = pool.submit(_get, client, bridge, f"{PROJECT}/events?after={mine_at}&wait=3")
        time.sleep(0.5)
        carried = pool.submit(
            _get,
            client,
            bridge,
            f"{PROJECT}/events?for={served.agent_id}&after={for_at}&wait=10",
        )
        time.sleep(0.5)
        seq = _tell(owner, served.agent_id)
        woken = carried.result(timeout=10).json()
        mine = own.result(timeout=10).json()
    assert seq in [e["seq"] for e in woken["items"]] and woken["superseded"] is False
    assert mine["superseded"] is False and seq not in [e["seq"] for e in mine["items"]]


def _bridge_row(engine: Engine, bridge: factory.Agent) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.bridge).where(t.bridge.c.bridge == bridge.membership_id)).one()


@pytest.mark.parametrize("meanwhile", ["ended", "isolated", "removed"])
def test_a_wait_for_an_agent_reads_nothing_once_the_bridge_may_not(
    meanwhile: str,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The long-poll checked the connection when it began; what commits before a pass ends
    what it reads (§2.3), on any replica."""
    served, bridge = _pair(migrated, owner)
    _tell(owner, served.agent_id)
    row = _bridge_row(migrated, bridge)
    real = longpoll.registry.enter

    def changed_meanwhile(waiter: Any) -> None:
        with migrated.begin() as conn:
            if meanwhile == "ended":
                conn.execute(update(t.bridge).where(t.bridge.c.id == row.id).values(live=None))
            else:
                values = (
                    {"isolated_since": clock.now(), "isolated_reason": "x", "isolated_by": "x"}
                    if meanwhile == "isolated"
                    else {"active": None}
                )
                conn.execute(
                    update(t.membership)
                    .where(t.membership.c.id == bridge.membership_id)
                    .values(**values)
                )
        real(waiter)

    monkeypatch.setattr(longpoll.registry, "enter", changed_meanwhile)
    waited = _get(make_client(), bridge, f"{PROJECT}/events?for={served.agent_id}&after=0&wait=1")
    assert waited.status_code == 200, waited.text
    assert waited.json()["items"] == []


def test_ending_the_connection_ends_the_open_wait_for_the_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    row = _bridge_row(migrated, bridge)
    cursor = _get(make_client(), bridge, f"{PROJECT}/events?for={served.agent_id}&after=latest")
    after = cursor.json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        start = time.monotonic()
        waiting = pool.submit(
            _get,
            make_client(),
            bridge,
            f"{PROJECT}/events?for={served.agent_id}&after={after}&wait=20",
        )
        _until_waiting("|for:")
        ended = owner.delete(f"{PROJECT}/members/{served.agent_id}/bridges/{row.id}")
        assert ended.status_code == 200, ended.text
        answered = waiting.result(timeout=10)
    assert answered.json()["items"] == [] and time.monotonic() - start < 10


def _until_waiting(marker: str) -> None:
    """Until a long-poll whose key holds `marker` is registered, not a fixed sleep: under
    load the call may open later than that."""
    deadline = time.monotonic() + 10
    while not any(marker in key for key in list(longpoll.registry._by_key)):
        assert time.monotonic() < deadline, "the wait never opened"
        time.sleep(0.05)


def test_the_registry_ends_a_bridges_waits_with_the_connection_or_its_isolation() -> None:
    loop = asyncio.new_event_loop()
    made = [
        longpoll.Waiter(
            key=f"cred|for:agt-{n}",
            project_id="prj-x",
            session_id=None,
            loop=loop,
            membership_id=n,
            bridge_id=f"brg-{n}",
            bridge_membership_id=9,
        )
        for n in (1, 2)
    ]
    own = longpoll.Waiter(key="cred", project_id="prj-x", session_id=None, loop=loop)
    try:
        for waiter in [*made, own]:
            longpoll.registry.enter(waiter)
        longpoll.registry.end_bridge("brg-1")
        assert [w.ended for w in made] == [True, False]
        longpoll.registry.end(9)  # the bridge isolated
        assert made[1].ended is True and own.ended is False
    finally:
        for waiter in [*made, own]:
            longpoll.registry.leave(waiter)
        loop.close()


def test_a_carried_read_wakes_as_the_member_token_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    to_instance = owner.post(
        f"{PROJECT}/conversations/{served.agent_id}/messages",
        {"body": "only you", "to_instance": served.instance},
    )
    assert to_instance.status_code == 201, to_instance.text
    plain = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "all"})
    assert plain.status_code == 201, plain.text
    waited = _get(make_client(), bridge, f"{PROJECT}/events?for={served.agent_id}&after=0&wait=1")
    woken = _seqs(waited)
    assert plain.json()["seq"] in woken and to_instance.json()["seq"] not in woken


def test_for_is_refused_without_a_connection_or_against_maity_for(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    stranger = factory.agent(migrated, _project(migrated), owner.id, "coder")
    client = make_client()
    refused = _get(client, bridge, f"{PROJECT}/events?for={stranger.agent_id}")
    assert refused.json()["error"]["details"]["reason"] == "not_your_bridge"
    mismatch = _get(client, bridge, f"{PROJECT}/events?for={stranger.agent_id}", served.agent_id)
    assert mismatch.json()["error"]["details"]["fields"] == {"for": "not_maity_for"}
    human = owner.get(f"{PROJECT}/events?for={served.agent_id}")
    assert human.json()["error"]["details"]["reason"] == "not_your_bridge"


def test_the_bridge_reads_the_direct_conversation_with_maity_for(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    said = owner.post(
        f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "how far are you?"}
    )
    assert said.status_code == 201, said.text
    client = make_client()
    path = f"{PROJECT}/conversations/{served.agent_id}"
    assert _get(client, bridge, path, served.agent_id).status_code == 200
    messages = _get(client, bridge, f"{path}/messages", served.agent_id)
    assert [m["body"] for m in messages.json()["items"]] == ["how far are you?"]
    assert _get(client, bridge, f"{path}/messages").status_code in (403, 404)  # as itself
    with migrated.connect() as conn:
        delivered = conn.execute(select(t.message_delivery)).first()
    assert delivered is None  # read through the bridge, not by the agent


def test_unread_through_the_bridge_is_the_served_agents_not_the_bridges_cursor(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    old = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "old"})
    assert old.status_code == 201, old.text
    said = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "news"})
    assert said.status_code == 201, said.text
    with migrated.begin() as conn:
        # The served agent read the first in a session that has ended since; the bridge's
        # own session has read far past both.
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.id == served.session_id)
            .values(acknowledged_seq=old.json()["seq"], live=None)
        )
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.id == bridge.session_id)
            .values(acknowledged_seq=said.json()["seq"] + 100)
        )
    client = make_client()
    one = _get(client, bridge, f"{PROJECT}/conversations/{served.agent_id}", served.agent_id)
    assert one.status_code == 200, one.text
    assert one.json()["unread"] == 1
    listed = _get(client, bridge, f"{PROJECT}/conversations", served.agent_id).json()["items"]
    assert [c["unread"] for c in listed if c.get("agent_id") == served.agent_id] == [1]


def test_a_served_agent_without_a_session_is_present_through_its_bridge(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner, served_session=False)
    assert _get(make_client(), bridge, "/me").status_code == 200  # the bridge is seen now
    view = owner.get(f"{PROJECT}/members/{served.agent_id}").json()
    assert view["session"] is None and view["presence"] == "online"
    assert view["availability"]["state"] == "available"  # read after the bridge's presence
    loose = factory.agent(migrated, _project(migrated), owner.id, "coder", with_session=False)
    assert owner.get(f"{PROJECT}/members/{loose.agent_id}").json()["presence"] == "offline"


@pytest.mark.parametrize("paused", ["membership", "instance"])
def test_a_paused_bridge_leaves_the_served_agent_offline(
    paused: str, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner, served_session=False)
    assert _get(make_client(), bridge, "/me").status_code == 200
    table = t.membership if paused == "membership" else t.credential
    key = bridge.membership_id if paused == "membership" else bridge.credential_id
    with migrated.begin() as conn:
        conn.execute(
            update(table)
            .where(table.c.id == key)
            .values(paused_since=clock.now(), paused_by=owner.id, paused_reason="break")
        )
    view = owner.get(f"{PROJECT}/members/{served.agent_id}").json()
    assert view["presence"] == "offline" and view["availability"]["state"] == "offline"


def test_a_request_asked_through_the_bridge_is_the_served_agents_without_an_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    asked = make_client().post(
        f"{API}{PROJECT}/requests",
        json={"class": "decision", "title": "Which?", "to": "owner"},
        headers={
            "Authorization": f"Bearer {bridge.value}",
            "Idempotency-Key": "bridge-ask-000001",
            "Maity-For": served.agent_id,
        },
    )
    assert asked.status_code == 201, asked.text
    done = owner.post(f"{PROJECT}/requests/{asked.json()['id']}/answer", {"text": "the first"})
    assert done.status_code == 200, done.text
    with migrated.connect() as conn:
        answered = conn.execute(select(t.event).where(t.event.c.kind == "request_answered")).one()
    assert f"member:{served.agent_id}" in answered.audience
    assert not any(a.startswith(f"instance:{served.agent_id}#") for a in answered.audience)
