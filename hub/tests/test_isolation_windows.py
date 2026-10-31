"""docs/api.md §6.2, "Isolation": lifting with `hide_isolation_events` keeps the isolation's
events out of what the agent may read for good (tsk-895q91frvjnw)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_isolation import isolate, say
from tests.test_tasks import task

PROJECT = "/projects/maintainer/maity"
CHATS = f"{PROJECT}/conversations"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def lift(owner: flow.Human, agent: flow.Agent, hide: bool | None = None) -> Any:
    path = f"/api/v1{PROJECT}/members/{agent.id}/isolate"
    body = None if hide is None else {"hide_isolation_events": hide}
    return owner.client.request("DELETE", path, json=body, headers={"X-CSRF-Token": owner.csrf})


def _windows(owner: flow.Human, agent: flow.Agent) -> list[dict[str, int]]:
    shown: list[dict[str, int]] = owner.get(f"{PROJECT}/members/{agent.id}").json()[
        "isolation_windows"
    ]
    return shown


def _seqs(response: Any) -> list[int]:
    return [item["seq"] for item in response.json()["items"]]


def test_a_plain_lift_hides_nothing(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    isolate(owner, agent.id)
    meanwhile = say(owner, "all", "while it was out").json()["seq"]
    assert lift(owner, agent).status_code == 200
    assert _windows(owner, agent) == []
    assert meanwhile in _seqs(agent.get(f"{PROJECT}/events?after=0&limit=200"))


def test_a_lift_that_hides_keeps_the_isolations_events_out_for_good(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="admin")  # admin trust reads everything else
    agent.resume()
    before = say(owner, "all", "before").json()["seq"]
    isolate(owner, agent.id)
    meanwhile = say(owner, "all", "while it was out").json()["seq"]
    done = lift(owner, agent, hide=True)
    assert done.status_code == 200, done.text
    [window] = done.json()["isolation_windows"]
    assert window["from_seq"] > before and window["from_seq"] <= meanwhile <= window["to_seq"]
    assert _windows(owner, agent) == [window]  # every reader sees the window
    after = say(owner, "all", "after").json()["seq"]
    read = _seqs(agent.get(f"{PROJECT}/events?after=0&limit=200"))
    assert before in read and after in read
    assert meanwhile not in read
    assert not any(window["from_seq"] <= seq <= window["to_seq"] for seq in read)
    # The one event by seq, the project messages, and the lift's own event.
    assert agent.get(f"{PROJECT}/events/{meanwhile}").status_code == 404
    listed = [m["seq"] for m in agent.get(f"{PROJECT}/messages").json()["items"]]
    assert meanwhile not in listed and after in listed
    lifted = owner.get(f"{PROJECT}/events?after={window['to_seq']}&limit=5").json()["items"]
    assert lifted and lifted[0]["kind"] == "member_updated"  # the lift is not in the window
    assert lifted[0]["seq"] in read


def test_a_second_isolation_adds_a_window(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    isolate(owner, agent.id)
    assert lift(owner, agent, hide=True).status_code == 200
    first = _windows(owner, agent)
    assert len(first) == 1
    isolate(owner, agent.id, "again")
    assert lift(owner, agent, hide=True).status_code == 200
    both = _windows(owner, agent)
    assert both[0] == first[0] and len(both) == 2 and both[1]["from_seq"] > first[0]["to_seq"]
    isolate(owner, agent.id, "a third time")
    assert lift(owner, agent).status_code == 200  # not hidden: no third window
    assert len(_windows(owner, agent)) == 2


def test_a_group_chat_it_is_added_to_again_hides_the_isolations_messages(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    other = flow.agent(make_client, owner)
    chat = owner.post(CHATS, {"title": "room", "participants": [agent.id, other.id]}).json()
    url = f"{CHATS}/{chat['id']}"
    before = owner.post(f"{url}/messages", {"body": "before"}).json()["seq"]
    isolate(owner, agent.id)  # leaves the chat
    meanwhile = owner.post(f"{url}/messages", {"body": "while it was out"}).json()["seq"]
    assert lift(owner, agent, hide=True).status_code == 200
    assert owner.post(f"{url}/participants", {"member_id": agent.id}).status_code in (200, 201)
    after = owner.post(f"{url}/messages", {"body": "after"}).json()["seq"]
    earlier = agent.get(f"{url}/messages?before={after + 1}&limit=50")
    assert earlier.status_code == 200, earlier.text
    seen = _seqs(earlier)
    assert before in seen and after in seen and meanwhile not in seen


def test_the_card_history_of_the_window_is_hidden_by_time(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    card = task(owner)
    isolate(owner, agent.id)
    changed = owner.patch(f"{PROJECT}/tasks/{card['id']}", {"title": "Zebra rename"})
    assert changed.status_code == 200, changed.text
    assert lift(owner, agent, hide=True).status_code == 200
    owner.patch(f"{PROJECT}/tasks/{card['id']}", {"title": "Renamed after"})
    mine = agent.get(f"{PROJECT}/tasks/{card['id']}/history").json()["items"]
    ours = owner.get(f"{PROJECT}/tasks/{card['id']}/history").json()["items"]
    missing = {e["id"] for e in ours} - {e["id"] for e in mine}
    assert len(missing) == 1  # the entry made inside the window is the only one it lacks
    assert {e["id"] for e in mine} < {e["id"] for e in ours}


def test_only_a_human_with_members_admin_lifts_and_chooses(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    isolate(owner, agent.id)
    refused = admin.client.request(
        "DELETE",
        f"/api/v1{PROJECT}/members/{agent.id}/isolate",
        json={"hide_isolation_events": True},
        headers=admin.auth | admin.key(),
    )
    assert refused.status_code == 403
    assert _windows(owner, agent) == []
