"""docs/api.md §15.4, §15.8, §15.10: attaching runners, hello, the runner's stream,
and runners as event actors."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from maity_hub import events
from maity_hub import tables as t
from maity_hub.events import Actor
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_auth_agent import signed
from tests.test_runners import Runner, call, enroll, error, exchange, paired

CAPABILITIES: dict[str, Any] = {
    "backend": "local",
    "max_agents": 4,
    "running": 0,
    "targets": [
        {
            "name": "local",
            "max_agents": 4,
            "running": 0,
            "reachable": True,
            "unreachable_since": None,
            "isolation": {"kind": "shared_user", "user": "oliver", "runner_separate": False},
        }
    ],
    "harnesses": [
        {
            "id": "claude-code",
            "version": "2.1.308",
            "available": True,
            "reason": None,
            "modes": ["interactive", "supervised"],
            "default_mode": "interactive",
            "models": ["opus"],
            "targets": ["local"],
            "confinement": "allowlist",
            "sandbox": "off",
        }
    ],
    "projects": ["maity"],
    "repositories": ["github.com/oliver-zehentleitner/*"],
    "require_local_approval": False,
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, repository={"url": "https://github.com/oliver-zehentleitner/maity"})
    return human


def send(
    client: TestClient,
    runner: Runner,
    method: str,
    path: str,
    body: Any,
    headers: dict[str, str] | None = None,
) -> Any:
    raw = json.dumps(body).encode()
    return client.request(
        method,
        path,
        content=raw,
        headers={
            "Content-Type": "application/json",
            **signed(runner, method, path, body=raw),
            **(headers or {}),
        },
    )


def hello(client: TestClient, runner: Runner, **body: Any) -> Any:
    payload = {"client": "maity-cli/0.3.0", "capabilities": CAPABILITIES, **body}
    return send(client, runner, "POST", "/api/v1/runner/hello", payload)


def attach(owner: flow.Human, runner: Runner, slug: str = "maity", key: str | None = None) -> Any:
    headers = {"X-CSRF-Token": owner.csrf} | ({"Idempotency-Key": key} if key else {})
    return owner.client.post(
        f"/api/v1/projects/{slug}/runners", json={"runner_id": runner.id}, headers=headers
    )


def stream(client: TestClient, runner: Runner, query: str) -> Any:
    path = "/api/v1/runner/events"
    return client.get(f"{path}?{query}", headers=signed(runner, "GET", path, query))


def member(make_client: ClientFactory, migrated: Engine, role: str) -> flow.Human:
    human = flow.human(make_client, migrated, f"{role}-human")
    project_id = factory_project_id(migrated)
    factory.membership(migrated, project_id, role, human_id=human.id)
    return human


def factory_project_id(engine: Engine, slug: str = "maity") -> str:
    with engine.begin() as conn:
        project_id: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == slug)
        ).scalar_one()
    return project_id


# --- attaching ---------------------------------------------------------------------------


def test_attaching_a_runner(make_client: ClientFactory, owner: flow.Human) -> None:
    runner = paired(make_client, owner)
    created = attach(owner, runner, key="attach-key-0000001")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["id"].startswith("ratt-") and body["project"] == "maity"
    assert (body["attached_by"], body["detached_at"], body["active_placements"]) == (
        owner.id,
        None,
        0,
    )
    assert body["runner"]["projects"] == ["maity"]
    listed = owner.get("/projects/maity/runners").json()["items"]
    assert [a["id"] for a in listed] == [body["id"]]
    replay = attach(owner, runner, key="attach-key-0000001")
    assert (replay.status_code, replay.json()["id"]) == (201, body["id"])
    again = attach(owner, runner, key="attach-key-0000002")
    assert (again.status_code, error(again)) == (409, "already_attached")
    assert again.json()["error"]["details"]["attachment"]["id"] == body["id"]
    assert owner.get(f"/runners/{runner.id}").json()["projects"] == ["maity"]


def test_only_an_admin_attaches_and_only_their_own_runner(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    plain = member(make_client, migrated, "member")
    refused = attach(plain, runner)
    assert (refused.status_code, refused.json()["error"]["details"]) == (
        403,
        {"scope": "members:admin"},
    )
    admin = member(make_client, migrated, "admin")
    not_theirs = attach(admin, runner)
    assert not_theirs.json()["error"]["details"]["fields"] == {"runner_id": "not_yours"}
    assert attach(owner, runner).status_code == 201
    # A reader sees the attachment without what the runner advertises, and no credential.
    [seen] = plain.get("/projects/maity/runners").json()["items"]
    assert "capabilities" not in seen["runner"] and "credential" not in seen["runner"]
    [admin_view] = admin.get("/projects/maity/runners").json()["items"]
    assert "capabilities" in admin_view["runner"] and "credential" not in admin_view["runner"]
    # An admin of an attached project sees the runner; a plain member does not.
    assert admin.get(f"/runners/{runner.id}").status_code == 200
    assert [r["id"] for r in admin.get("/runners").json()["items"]] == [runner.id]
    assert plain.get(f"/runners/{runner.id}").status_code == 404


def test_an_agent_does_not_read_the_projects_runners(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    response = agent.get("/projects/maity/runners")
    assert (response.status_code, error(response)) == (403, "forbidden")


def test_detaching_a_runner(make_client: ClientFactory, owner: flow.Human) -> None:
    runner = paired(make_client, owner)
    attached = attach(owner, runner).json()
    detached = owner.delete(f"/projects/maity/runners/{runner.id}")
    assert detached.status_code == 200
    assert detached.json()["id"] == attached["id"] and detached.json()["detached_at"]
    assert owner.delete(f"/projects/maity/runners/{runner.id}").json() == detached.json()
    assert owner.get("/projects/maity/runners").json()["items"] == []
    assert owner.get(f"/runners/{runner.id}").json()["projects"] == []
    other = paired(make_client, owner, name="never-attached")
    assert owner.delete(f"/projects/maity/runners/{other.id}").status_code == 404
    # Attached again: a new attachment.
    assert attach(owner, runner).json()["id"] != attached["id"]


def test_an_enrollment_attaches_at_the_exchange(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "sample")
    created = enroll(owner, attach=["maity", "sample", "maity"])
    listed = owner.get("/runners/enrollments").json()["items"][0]
    assert listed["attach"] == ["maity", "sample"]
    # The creator is no longer an admin of `sample` when the runner pairs.
    sample = factory_project_id(migrated, "sample")
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.project_id == sample, t.membership.c.human_id == owner.id)
            .values(role="member")
        )
    response = exchange(make_client(), created)
    assert response.headers["Maity-Attached"] == "maity"
    runner_id = response.headers["Maity-Runner-Id"]
    assert owner.get(f"/runners/{runner_id}").json()["projects"] == ["maity"]
    attached = owner.get("/projects/maity/events?after=0").json()["items"]
    assert [e["payload"]["runner_id"] for e in attached if e["kind"] == "runner_attached"] == [
        runner_id
    ]


def test_an_enrollment_attaches_only_where_its_creator_is_admin(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    plain = member(make_client, migrated, "member")
    refused = plain.post("/runners/enrollments", {"name": "box", "attach": ["maity"]})
    assert (refused.status_code, refused.json()["error"]["details"]) == (
        403,
        {"scope": "members:admin"},
    )
    unknown = owner.post("/runners/enrollments", {"name": "box", "attach": ["nope"]})
    assert unknown.status_code == 404


# --- hello and what a runner advertises ----------------------------------------------------


def test_hello_opens_a_session_and_answers_the_packet(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    attach(owner, runner)
    client = make_client()
    first = hello(client, runner)
    assert first.status_code == 200, first.text
    packet = first.json()
    assert set(packet) == {"server_time", "runner", "projects", "placements", "cursor"}
    assert packet["runner"]["id"] == runner.id and packet["runner"]["name"] == "home-laptop"
    assert packet["runner"]["session_id"].startswith("rses-")
    assert packet["projects"] == [
        {
            "slug": "maity",
            "name": "Maity",
            "repository": "https://github.com/oliver-zehentleitner/maity",
        }
    ]
    assert packet["placements"] == []
    # The runner_attached event named the runner: the cursor stands on it.
    assert packet["cursor"] > 0
    second = hello(client, runner).json()
    with migrated.begin() as conn:
        live = conn.execute(
            select(t.runner_session.c.id).where(t.runner_session.c.live.is_(True))
        ).all()
    assert [r.id for r in live] == [second["runner"]["session_id"]]
    view = owner.get(f"/runners/{runner.id}").json()
    assert view["version"] == "maity-cli/0.3.0" and view["presence"] == "online"
    assert view["last_seen_at"] is not None
    stored = view["capabilities"]
    assert stored["harnesses"][0]["id"] == "claude-code" and stored["reported_at"] is not None


@pytest.mark.parametrize(
    "change",
    [
        {"backend": "lokalä"},
        {"harnesses": [{**CAPABILITIES["harnesses"][0], "id": "emacs"}]},
        {"surprise": True},
    ],
)
def test_hello_validates_what_a_runner_advertises(
    make_client: ClientFactory, owner: flow.Human, change: dict[str, Any]
) -> None:
    runner = paired(make_client, owner)
    response = hello(make_client(), runner, capabilities={**CAPABILITIES, **change})
    assert (response.status_code, error(response)) == (400, "invalid")


def test_patch_runner_replaces_the_capabilities_with_a_key(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner)
    changed = {**CAPABILITIES, "max_agents": 2}
    keyless = send(client, runner, "PATCH", "/api/v1/runner", {"capabilities": changed})
    assert (keyless.status_code, error(keyless)) == (400, "invalid")
    patched = send(
        client,
        runner,
        "PATCH",
        "/api/v1/runner",
        {"capabilities": changed},
        {"Idempotency-Key": "runner-patch-00001"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["capabilities"]["max_agents"] == 2
    assert "credential" not in patched.json()  # the owner's alone


def test_runner_endpoints_are_the_runners(make_client: ClientFactory, owner: flow.Human) -> None:
    human = owner.post("/runner/hello", {"client": "x", "capabilities": CAPABILITIES})
    assert (human.status_code, error(human)) == (403, "forbidden")
    agent = flow.agent(make_client, owner)
    assert agent.get("/runner/events").status_code == 403


# --- the stream --------------------------------------------------------------------------


def test_the_stream_reads_only_what_names_the_runner(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    flow.project(owner, "sample")
    flow.project(owner, "elsewhere")
    runner = paired(make_client, owner)
    client = make_client()
    attach(owner, runner)
    cursor = hello(client, runner).json()["cursor"]
    attach(owner, runner, "sample")
    flow.agent(make_client, owner)  # member_joined, to `all` in maity
    flow.agent(make_client, owner, "elsewhere")
    body = stream(client, runner, f"after={cursor}").json()
    assert set(body) == {"items", "cursor", "server_time", "superseded"}
    assert [(e["kind"], e["payload"]["project"]) for e in body["items"]] == [
        ("runner_attached", "sample")
    ]
    assert body["items"][0]["actor"]["kind"] == "member"
    assert stream(client, runner, f"after={body['cursor']}").json()["items"] == []
    latest = stream(client, runner, "after=latest").json()
    assert latest["items"] == [] and latest["cursor"] == body["cursor"]


def test_a_detached_runner_still_reads_its_detachment(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    attach(owner, runner)
    cursor = hello(client, runner).json()["cursor"]
    owner.delete(f"/projects/maity/runners/{runner.id}")
    items = stream(client, runner, f"after={cursor}").json()["items"]
    assert [e["kind"] for e in items] == ["runner_detached"]
    assert hello(client, runner).json()["projects"] == []


def test_the_long_poll_wakes_on_an_attachment_and_shows_listening(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    flow.project(owner, "sample")
    runner = paired(make_client, owner)
    client = make_client()
    attach(owner, runner)
    cursor = hello(client, runner).json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        start = time.monotonic()
        waiting = pool.submit(stream, client, runner, f"after={cursor}&wait=20")
        time.sleep(0.5)
        assert owner.get(f"/runners/{runner.id}").json()["listening"] is True
        attach(owner, runner, "sample")
        body = waiting.result(timeout=10).json()
    assert time.monotonic() - start < 8
    assert [e["kind"] for e in body["items"]] == ["runner_attached"]
    assert owner.get(f"/runners/{runner.id}").json()["listening"] is False


def test_a_second_long_poll_supersedes_the_first(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    attach(owner, runner)
    cursor = hello(client, runner).json()["cursor"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(stream, client, runner, f"after={cursor}&wait=20")
        time.sleep(0.5)
        second = pool.submit(stream, client, runner, f"after={cursor}&wait=1")
        superseded = first.result(timeout=10).json()
        second.result(timeout=10)
    assert superseded == superseded | {"items": [], "superseded": True, "cursor": cursor}


def test_a_revocation_ends_the_long_poll(make_client: ClientFactory, owner: flow.Human) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    attach(owner, runner)
    cursor = hello(client, runner).json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(stream, client, runner, f"after={cursor}&wait=20")
        time.sleep(0.5)
        owner.post(f"/runners/{runner.id}/revoke", {"reason": "stolen"})
        ended = waiting.result(timeout=10)
    assert (ended.status_code, error(ended)) == (401, "credential_revoked")


# --- events --------------------------------------------------------------------------------


def test_a_revocation_is_announced_in_every_attached_project(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    flow.project(owner, "sample")
    runner = paired(make_client, owner)
    attach(owner, runner)
    attach(owner, runner, "sample")
    owner.post(f"/runners/{runner.id}/revoke", {"reason": "stolen"})
    for slug in ("maity", "sample"):
        [revoked] = [
            e
            for e in owner.get(f"/projects/{slug}/events?after=0").json()["items"]
            if e["kind"] == "runner_credential_revoked"
        ]
        assert revoked["audience"] == ["role:owner"]
        assert revoked["payload"] == {
            "runner_id": runner.id,
            "credential_id": runner.credential_id,
            "reason": "stolen",
            "on_runner_revoke": "keep",  # the instance default, nothing running (§15.3)
            "stopped": [],
        }
        assert revoked["actor"]["member_id"] == owner.id


def test_removing_a_runner_detaches_it_everywhere(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    attach(owner, runner)
    owner.delete(f"/runners/{runner.id}")
    kinds = [e["kind"] for e in owner.get("/projects/maity/events?after=0").json()["items"]]
    assert kinds[-2:] == ["runner_credential_revoked", "runner_detached"]
    assert owner.get("/projects/maity/runners").json()["items"] == []


def test_a_re_pair_is_announced_where_the_runner_is_attached(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    attach(owner, runner)
    exchange(make_client(), enroll(owner, name=None, runner_id=runner.id))
    [revoked] = [
        e
        for e in owner.get("/projects/maity/events?after=0").json()["items"]
        if e["kind"] == "runner_credential_revoked"
    ]
    assert revoked["payload"]["reason"] == "repaired"


def test_a_runner_as_an_event_actor(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    project_id = factory_project_id(migrated)
    with events.transaction(migrated) as conn:
        events.emit(
            conn,
            project_id,
            "notice_for_test",
            ["role:owner"],
            {},
            actor=Actor(
                membership_id=None,
                session_id="rses-test",
                credential_id=runner.credential_id,
                via="signed",
                runner_id=runner.id,
            ),
        )
    [event] = [
        e
        for e in owner.get("/projects/maity/events?after=0").json()["items"]
        if e["kind"] == "notice_for_test"
    ]
    assert event["actor"] == {
        "kind": "runner",
        "id": runner.id,
        "name": "home-laptop",
        "credential_id": runner.credential_id,
        "session_id": "rses-test",
        "via": "signed",
    }


def test_a_runner_reaches_its_own_routes_only(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    assert call(make_client(), runner, "GET", "/api/v1/runner/events").status_code == 200
    assert call(make_client(), runner, "GET", "/api/v1/projects/maity").status_code == 404


def test_attaching_while_the_runner_is_removed_leaves_no_attachment(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    for i in range(5):
        runner = paired(make_client, owner, name=f"racer-{i}")
        with ThreadPoolExecutor(max_workers=2) as pool:
            attaching = pool.submit(attach, owner, runner)
            removal = pool.submit(owner.delete, f"/runners/{runner.id}")
            assert removal.result(timeout=30).status_code == 200
            assert attaching.result(timeout=30).status_code in (201, 400)
        with migrated.begin() as conn:
            active = conn.execute(
                select(t.runner_attachment.c.id).where(
                    t.runner_attachment.c.runner_id == runner.id,
                    t.runner_attachment.c.active.is_(True),
                )
            ).all()
        assert active == []


# --- review: races and edges of hello ------------------------------------------------------


def test_concurrent_hellos_leave_one_live_session(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    clients = [make_client() for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda c: hello(c, runner), clients))
    assert [r.status_code for r in results] == [200] * 6, [r.text for r in results]
    with migrated.begin() as conn:
        live = conn.execute(
            select(t.runner_session.c.id).where(t.runner_session.c.live.is_(True))
        ).all()
    assert len(live) == 1


def test_hello_racing_other_runner_calls(make_client: ClientFactory, owner: flow.Human) -> None:
    """A runner restarting while its old process still polls: hello and authentication
    take the rows in one order, so neither deadlocks the other (§15.8)."""
    runner = paired(make_client, owner)
    clients = [make_client() for _ in range(8)]
    hello(clients[0], runner)

    def one(i: int) -> Any:
        return hello(clients[i], runner) if i % 2 else stream(clients[i], runner, "after=0")

    outcomes: list[tuple[int, str]] = []
    for _ in range(5):
        with ThreadPoolExecutor(max_workers=8) as pool:
            for response in pool.map(one, range(8)):
                code = "" if response.status_code == 200 else error(response)
                outcomes.append((response.status_code, code))
    assert [o for o in outcomes if o[0] != 200] == []


@pytest.mark.parametrize(
    "body",
    [
        {"client": "maity-cli/0.3.0ä"},
        {
            "capabilities": {
                **CAPABILITIES,
                "harnesses": [{**CAPABILITIES["harnesses"][0], "available": False}],
            }
        },
        {
            "capabilities": {
                **CAPABILITIES,
                "harnesses": [CAPABILITIES["harnesses"][0], CAPABILITIES["harnesses"][0]],
            }
        },
        {
            "capabilities": {
                **CAPABILITIES,
                "targets": [
                    {**CAPABILITIES["targets"][0], "unreachable_since": "2026-10-22T13:00:00"}
                ],
            }
        },
    ],
)
def test_hello_refuses_what_it_cannot_show_or_trust(
    make_client: ClientFactory, owner: flow.Human, body: dict[str, Any]
) -> None:
    runner = paired(make_client, owner)
    payload = {"client": "maity-cli/0.3.0", "capabilities": CAPABILITIES, **body}
    response = send(make_client(), runner, "POST", "/api/v1/runner/hello", payload)
    assert (response.status_code, error(response)) == (400, "invalid")
