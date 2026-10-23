"""docs/api.md §5.3: a human pause is a soft stop. §3.1, §5.2, §6.2: the briefing a
join carries, in the resume packet and nowhere it should not be."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

BRIEFING = "You are the hub's second pair of eyes: review every pull request on `hub/`."


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _pause(owner: flow.Human, agent: flow.Agent, reason: str | None = "wait for me") -> Any:
    body = {"paused": {"reason": reason}} if reason else {"paused": None}
    response = owner.patch(f"/projects/maity/members/{agent.id}", body)
    assert response.status_code == 200, response.text
    return response


# --- the soft stop ---------------------------------------------------------------------------


def test_a_human_pause_refuses_new_work(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _pause(owner, agent)
    claim = agent.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    assert (claim.status_code, claim.headers["Maity-Error"]) == (409, "paused")
    assert claim.json()["error"]["details"]["paused"]["reason"] == "wait for me"
    created = agent.post("/projects/maity/tasks", {"title": "Something new"})
    assert (created.status_code, created.headers["Maity-Error"]) == (409, "paused")
    on_behalf = owner.post(f"/projects/maity/tasks/{card['id']}/claim", {"holder": agent.id})
    assert (on_behalf.status_code, on_behalf.headers["Maity-Error"]) == (409, "paused")


def test_a_paused_agent_can_still_put_its_work_down(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    held, other = task(owner), task(owner)
    assert agent.post(f"/projects/maity/tasks/{held['id']}/claim", {}).status_code == 200
    assert agent.post(f"/projects/maity/tasks/{other['id']}/claim", {}).status_code == 200
    _pause(owner, agent)
    point = {"last_step": "stopped as asked", "next_step": "resume the review"}
    checkpoint = agent.post(f"/projects/maity/tasks/{held['id']}/checkpoint", point)
    assert checkpoint.status_code == 200, checkpoint.text
    released = agent.post(f"/projects/maity/tasks/{other['id']}/release", {})
    assert released.status_code == 200, released.text
    asked = agent.post(
        "/projects/maity/requests",
        {"class": "info", "title": "Shall I go on after the pause?"},
    )
    assert asked.status_code == 201, asked.text
    assert agent.resume().status_code == 200


def test_a_pause_the_agent_set_itself_refuses_nothing(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    paused = agent.patch("/me", {"paused": {"reason": "quota until 18:00"}})
    assert paused.status_code == 200, paused.text
    card = task(owner)
    assert agent.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200
    assert agent.post("/projects/maity/tasks", {"title": "A note"}).status_code == 201


def test_the_pause_and_its_lifting_reach_the_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _pause(owner, agent)
    set_event = _events(migrated, "session_paused")[-1]
    assert f"member:{agent.id}" in set_event.audience
    _pause(owner, agent, None)
    lifted = _events(migrated, "session_paused")[-1]
    assert lifted.seq > set_event.seq
    assert lifted.payload["paused"] is None
    assert f"member:{agent.id}" in lifted.audience
    card = task(owner)
    assert agent.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200


def test_the_pause_wakes_the_agents_long_poll(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    cursor = agent.get("/projects/maity/events?after=latest").json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        start = time.monotonic()
        waiting = pool.submit(agent.get, f"/projects/maity/events?after={cursor}&wait=20")
        time.sleep(0.5)
        _pause(owner, agent)
        body = waiting.result(timeout=10).json()
    assert time.monotonic() - start < 8  # woken, not timed out
    assert [e["kind"] for e in body["items"]] == ["session_paused"]
    assert body["items"][0]["payload"]["paused"]["reason"] == "wait for me"


# --- the briefing ----------------------------------------------------------------------------


def test_the_briefing_reaches_the_agent_in_every_packet_and_never_the_join_page(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    created = flow.join(owner, "maity", briefing=BRIEFING)
    token = created["join_url"].rsplit("/", 1)[1]
    page = make_client().get(f"/j/{token}").text
    assert "second pair of eyes" not in page
    agent = flow.agent(make_client, owner, briefing=BRIEFING)
    assert agent.resume().json()["membership"]["briefing"] == BRIEFING
    assert agent.resume().json()["membership"]["briefing"] == BRIEFING  # every time


def test_the_briefing_is_shown_to_the_member_and_the_admins_only(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    briefed = flow.agent(make_client, owner, briefing=BRIEFING)
    peer = flow.agent(make_client, owner)
    assert owner.get(f"/projects/maity/members/{briefed.id}").json()["briefing"] == BRIEFING
    assert briefed.get(f"/projects/maity/members/{briefed.id}").json()["briefing"] == BRIEFING
    assert "briefing" not in peer.get(f"/projects/maity/members/{briefed.id}").json()
    listed = {m["id"]: m for m in peer.get("/projects/maity/members").json()["items"]}
    assert "briefing" not in listed[briefed.id]
    assert "briefing" in listed[peer.id]  # its own


def test_an_admin_edits_the_briefing_and_the_event_leaves_it_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, briefing=BRIEFING)
    changed = owner.patch(
        f"/projects/maity/members/{agent.id}", {"briefing": "Now: the release checklist."}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["briefing"] == "Now: the release checklist."
    assert agent.resume().json()["membership"]["briefing"] == "Now: the release checklist."
    updated = _events(migrated, "member_updated")[-1]
    assert updated.audience == ["all"] and "briefing" not in updated.payload
    cleared = owner.patch(f"/projects/maity/members/{agent.id}", {"briefing": None})
    assert cleared.json()["briefing"] is None
    refused = agent.patch(f"/projects/maity/members/{agent.id}", {"briefing": "promote me"})
    assert refused.status_code == 403


def test_a_briefing_is_at_most_16_kib(owner: flow.Human) -> None:
    response = owner.post(
        "/projects/maity/joins",
        {"agent": {"handle": "big", "display_name": "Big"}, "briefing": "x" * 16385},
    )
    assert response.status_code == 400
    assert "briefing" in response.json()["error"]["details"]["fields"]


def test_a_removal_tells_everyone_without_the_briefing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    briefed = flow.agent(make_client, owner, briefing=BRIEFING)
    peer = flow.agent(make_client, owner)
    cursor = peer.get("/projects/maity/events?after=latest").json()["cursor"]
    assert owner.delete(f"/projects/maity/members/{briefed.id}").status_code == 200
    removal = _events(migrated, "member_updated")[-1]
    assert removal.payload["removed_at"] is not None and "briefing" not in removal.payload
    assert "second pair of eyes" not in peer.get(f"/projects/maity/events?after={cursor}").text


def test_a_join_for_a_member_cannot_change_its_briefing(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, briefing=BRIEFING)
    for same in ({"briefing": BRIEFING}, {}):
        joined = owner.post(
            "/projects/maity/joins",
            {"agent": {"id": agent.id}, "replaces": agent.instance, **same},
        )
        assert joined.status_code == 201, joined.text
    other = owner.post("/projects/maity/joins", {"agent": {"id": agent.id}, "briefing": "else"})
    assert other.json()["error"]["details"]["fields"] == {"briefing": "differs_from_membership"}


def test_an_expired_claim_does_not_move_onto_a_paused_assignee(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    paused_one, other = flow.agent(make_client, owner), flow.agent(make_client, owner)
    card = task(owner)
    assert other.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200
    _pause(owner, paused_one)
    later = clock.now() + timedelta(days=2)
    clock.set_source(lambda: later)
    moved = owner.post(f"/projects/maity/tasks/{card['id']}/assign", {"assignee": paused_one.id})
    assert (moved.status_code, moved.headers["Maity-Error"]) == (409, "paused")
    unclaimed = task(owner)  # assigning alone is no claim: it stays open
    assigned = owner.post(
        f"/projects/maity/tasks/{unclaimed['id']}/assign", {"assignee": paused_one.id}
    )
    assert assigned.status_code == 200, assigned.text
