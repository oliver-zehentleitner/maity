"""docs/api.md §8.3: reading events, the long-poll, the cursor, after=latest."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import clock
from tests import flow
from tests.conftest import ClientFactory
from tests.test_claims import _claim
from tests.test_tasks import task


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def say(who: Any, to: str, body: str = "hello", type_: str = "notice") -> Any:
    return who.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": type_, "to": to, "body": body},
    )


def test_a_read_returns_the_readable_events_and_a_cursor(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    say(owner, agent.id, "for you")
    say(owner, "trust:admin", "not for you")
    body = agent.get("/projects/maintainer/maity/events?after=0").json()
    assert set(body) == {"items", "cursor", "server_time", "superseded"}
    kinds = [(e["kind"], e["payload"].get("body")) for e in body["items"]]
    assert ("message", "for you") in kinds and ("message", "not for you") not in kinds
    # With items, the cursor is the last item's seq (§8.3) ...
    assert body["cursor"] == body["items"][-1]["seq"] and body["superseded"] is False
    again = agent.get(f"/projects/maintainer/maity/events?after={body['cursor']}").json()
    # ... and with none, the highest seq examined, past what was filtered out.
    assert again["items"] == [] and again["cursor"] > body["cursor"]
    assert (
        agent.get(f"/projects/maintainer/maity/events?after={again['cursor']}").json()["cursor"]
        == again["cursor"]
    )


def test_after_latest_starts_from_now_without_history(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    say(owner, agent.id)
    latest = agent.get("/projects/maintainer/maity/events?after=latest").json()
    assert latest["items"] == []
    everything = agent.get("/projects/maintainer/maity/events?after=0").json()
    assert latest["cursor"] == everything["items"][-1]["seq"]


def test_an_after_beyond_the_end_answers_after(owner: flow.Human) -> None:
    body = owner.get("/projects/maintainer/maity/events?after=999999").json()
    assert (body["items"], body["cursor"]) == ([], 999999)


def test_after_acknowledges_for_the_session(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    agent.get("/projects/maintainer/maity/events?after=7")
    assert agent.resume().json()["events"]["after"] == 7
    agent.get("/projects/maintainer/maity/events?after=latest")  # acknowledges nothing
    assert agent.resume().json()["events"]["after"] == 7


@pytest.mark.parametrize("query", ["wait=x", "after=-1", "limit=0", "limit=201"])
def test_bad_parameters_are_invalid(owner: flow.Human, query: str) -> None:
    assert (
        owner.get(f"/projects/maintainer/maity/events?{query}").headers["Maity-Error"] == "invalid"
    )


def test_a_long_poll_wakes_on_an_event_addressed_to_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    cursor = agent.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        start = time.monotonic()
        waiting = pool.submit(
            agent.get, f"/projects/maintainer/maity/events?after={cursor}&wait=20"
        )
        time.sleep(0.5)
        say(owner, agent.id, "wake up")
        body = waiting.result(timeout=10).json()
    assert time.monotonic() - start < 8  # woken, not timed out
    assert [e["payload"]["body"] for e in body["items"]] == ["wake up"]


def test_a_long_poll_is_not_woken_by_its_own_echo_or_the_admin_view(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    cursor = owner.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    say(owner, "trust:owner", "my own echo")
    say(agent, other.id, "between agents")  # the owner may read it, but it is not addressed to it
    start = time.monotonic()
    body = owner.get(f"/projects/maintainer/maity/events?after={cursor}&wait=2").json()
    elapsed = time.monotonic() - start
    kinds = [e["kind"] for e in body["items"]]
    assert "message" not in kinds  # woken only by member_joined broadcasts, if at all
    assert all(k == "member_joined" for k in kinds)
    if not kinds:
        assert elapsed >= 1.5


def test_a_long_poll_times_out_with_an_empty_answer(owner: flow.Human) -> None:
    cursor = owner.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    start = time.monotonic()
    body = owner.get(f"/projects/maintainer/maity/events?after={cursor}&wait=1").json()
    assert body["items"] == [] and body["cursor"] >= cursor and body["superseded"] is False
    assert 0.9 <= time.monotonic() - start < 5


def test_a_second_long_poll_supersedes_the_first(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    cursor = agent.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(agent.get, f"/projects/maintainer/maity/events?after={cursor}&wait=20")
        time.sleep(0.5)
        second = pool.submit(agent.get, f"/projects/maintainer/maity/events?after={cursor}&wait=1")
        superseded = first.result(timeout=10).json()
        second.result(timeout=10)
    assert superseded == superseded | {"items": [], "superseded": True, "cursor": cursor}


def test_listening_shows_while_a_long_poll_is_open(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    cursor = agent.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(agent.get, f"/projects/maintainer/maity/events?after={cursor}&wait=3")
        time.sleep(0.5)
        view = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()
        waiting.result(timeout=10)
    assert view["session"]["listening"] is True and view["presence"] == "online"
    assert (
        owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["session"]["listening"]
        is False
    )


def test_a_long_poll_renews_presence_but_no_lease(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    card = task(owner)
    _claim(agent, card)
    before = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["claim"][
        "lease_until"
    ]
    start = clock.now()
    clock.set_source(lambda: start + timedelta(hours=1))
    agent.get("/projects/maintainer/maity/events?after=latest&wait=1")
    after_poll = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["claim"][
        "lease_until"
    ]
    assert after_poll == before
    agent.get("/projects/maintainer/maity/events?after=latest")  # a plain read is work
    renewed = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["claim"][
        "lease_until"
    ]
    assert renewed != before


def test_a_dashboard_session_may_long_poll(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    cursor = owner.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(
            owner.get, f"/projects/maintainer/maity/events?after={cursor}&wait=20"
        )
        time.sleep(0.5)
        say(agent, owner.id, "for the human")
        body = waiting.result(timeout=10).json()
    assert [e["payload"]["body"] for e in body["items"]] == ["for the human"]


def test_events_of_another_project_are_not_found(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.get("/projects/maintainer/maity/events").headers["Maity-Error"] == "not_found"


# --- review round ------------------------------------------------------------------------


def test_a_superseded_wait_reads_nothing_and_keeps_the_cursor(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    cursor = agent.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    say(owner, agent.id, "waiting already")  # wake-relevant, there before both waits
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(agent.get, f"/projects/maintainer/maity/events?after={cursor}&wait=20")
        second = pool.submit(agent.get, f"/projects/maintainer/maity/events?after={cursor}&wait=20")
        answers = [first.result(timeout=10).json(), second.result(timeout=10).json()]
    superseded = [a for a in answers if a["superseded"]]
    for body in superseded:
        assert body["items"] == [] and body["cursor"] == cursor  # nothing withheld behind it
    assert any(a["items"] for a in answers)


def test_an_unauthenticated_bad_wait_is_unauthenticated_first(
    make_client: ClientFactory, migrated: Engine
) -> None:
    response = make_client().get("/api/v1/projects/maintainer/maity/events?wait=x")
    assert response.headers["Maity-Error"] == "unauthenticated"


@pytest.mark.parametrize("raw", ["100", "55", "999999999999"])
def test_wait_is_clamped_to_55_seconds(raw: str) -> None:
    from starlette.requests import Request

    from maity_hub.deps import wait_of

    request = Request({"type": "http", "query_string": f"wait={raw}".encode(), "headers": []})
    assert wait_of(request) == 55


@pytest.mark.parametrize("after", ["99999999999999999999", "9223372036854775808", "١"])
def test_an_after_out_of_range_is_invalid(owner: flow.Human, after: str) -> None:
    assert (
        owner.get(f"/projects/maintainer/maity/events?after={after}").headers["Maity-Error"]
        == "invalid"
    )
