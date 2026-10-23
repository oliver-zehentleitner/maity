"""docs/api.md §15.3, §6.1, §16: what revoking or removing a runner does to its agents."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_placements import REPOSITORY, Setup, placed
from tests.test_runner_stream import attach, hello
from tests.test_runners import call, error, paired


def setup_with(make_client: ClientFactory, migrated: Engine, **settings: Any) -> Setup:
    client = make_client(**settings)
    owner = flow.human(make_client, migrated) if not settings else _human(client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    attach(owner, runner)
    runner_client = make_client()
    assert hello(runner_client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    return Setup(owner, runner, runner_client, agent, migrated)


def _human(client: Any, migrated: Engine) -> flow.Human:
    from tests import factory

    human_id = factory.human(migrated, "maintainer")
    login = client.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert login.status_code == 200, login.text
    return flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], human_id)


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    return setup_with(make_client, migrated)


def running(s: Setup) -> dict[str, Any]:
    """A placement whose agent holds a credential, as after its pickup."""
    found = placed(s)
    with s.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == found["id"])
            .values(credential_id=s.agent.credential_id)
        )
    return found


def revoke(s: Setup, **body: Any) -> Any:
    return s.owner.post(f"/runners/{s.runner.id}/revoke", body)


def remove(s: Setup, **body: Any) -> Any:
    return s.owner.client.request(
        "DELETE",
        f"/api/v1/runners/{s.runner.id}",
        json=body or None,
        headers={"X-CSRF-Token": s.owner.csrf},
    )


def placement(s: Setup, placement_id: str) -> dict[str, Any]:
    found: dict[str, Any] = s.owner.get(f"/projects/maity/placements/{placement_id}").json()
    return found


def set_policy(s: Setup, rule: str) -> Any:
    return s.owner.patch(
        "/projects/maity", {"policy": {"on_runner_revoke": rule}, "reason": "the runner's agents"}
    )


def later(seconds: float) -> None:
    then = clock.now() + timedelta(seconds=seconds)
    clock.set_source(lambda: then)


def test_keep_is_the_default_and_changes_nothing(setup: Setup) -> None:
    first = running(setup)
    answer = revoke(setup)
    assert answer.status_code == 200, answer.text
    assert answer.json()["on_runner_revoke"] == [
        {"project": "maity", "rule": "keep", "stopped": []}
    ]
    assert placement(setup, first["id"])["active"] is True
    later(3600)
    assert setup.agent.get("/me").status_code == 200  # the agent runs on (§15.3)


def test_stop_closes_tells_and_revokes_after_the_grace(setup: Setup) -> None:
    assert set_policy(setup, "stop").status_code == 200
    first = running(setup)
    answer = revoke(setup, reason="stolen laptop")
    assert answer.json()["on_runner_revoke"] == [
        {"project": "maity", "rule": "stop", "stopped": [first["id"]]}
    ]
    closed = placement(setup, first["id"])
    assert (closed["active"], closed["closed_reason"]) == (False, "runner_revoked")
    with setup.engine.connect() as conn:
        told = conn.execute(
            select(t.event.c.payload).where(t.event.c.kind == "agent_stop_requested")
        ).all()
        notice = conn.execute(
            select(t.event.c.payload).where(t.event.c.kind == "runner_credential_revoked")
        ).scalar_one()
    assert [p.payload["placement_id"] for p in told] == [first["id"]]
    assert (notice["on_runner_revoke"], notice["stopped"]) == ("stop", [first["id"]])
    assert setup.agent.get("/me").status_code == 200  # within its grace: it may park its work
    later(first["stop_grace_seconds"] + 1)
    refused = setup.agent.get("/me")
    assert (refused.status_code, error(refused)) == (401, "credential_revoked")
    assert refused.json()["error"]["details"] == {"reason": "runner_revoked"}
    with setup.engine.connect() as conn:
        written = conn.execute(
            select(t.credential.c.revoked_reason, t.credential.c.revoked_by).where(
                t.credential.c.id == setup.agent.credential_id
            )
        ).one()
    assert tuple(written) == ("runner_revoked", setup.owner.id)


def test_the_owners_override_stops_at_once_whatever_the_policy(setup: Setup) -> None:
    first = running(setup)  # the project keeps (inherit, instance keep)
    answer = revoke(setup, agents="stop")
    assert answer.json()["on_runner_revoke"][0] == {
        "project": "maity",
        "rule": "stop",
        "stopped": [first["id"]],
    }
    refused = setup.agent.get("/me")  # no grace: the machine is in doubt
    assert error(refused) == "credential_revoked"


def test_the_runner_learns_what_was_stopped(setup: Setup) -> None:
    first = running(setup)
    revoke(setup, agents="stop")
    refused = call(setup.client, setup.runner, "GET", "/api/v1/runner/placements")
    assert (refused.status_code, error(refused)) == (401, "credential_revoked")
    assert refused.json()["error"]["details"]["stop"] == [first["id"]]


def test_removing_under_stop_revokes_the_agents_too(setup: Setup) -> None:
    assert set_policy(setup, "stop").status_code == 200
    first = running(setup)
    answer = remove(setup)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["removed_at"] is not None
    assert body["on_runner_revoke"] == [
        {"project": "maity", "rule": "stop", "stopped": [first["id"]]}
    ]
    assert placement(setup, first["id"])["closed_reason"] == "runner_removed"
    later(first["stop_grace_seconds"] + 1)
    assert error(setup.agent.get("/me")) == "credential_revoked"


def test_removing_under_keep_closes_the_placements_and_keeps_the_agents(setup: Setup) -> None:
    first = running(setup)
    body = remove(setup).json()
    assert body["on_runner_revoke"] == [{"project": "maity", "rule": "keep", "stopped": []}]
    assert placement(setup, first["id"])["closed_reason"] == "runner_removed"
    later(3600)
    assert setup.agent.get("/me").status_code == 200


def test_a_replayed_revoke_answers_the_same(setup: Setup) -> None:
    running(setup)
    headers = {"X-CSRF-Token": setup.owner.csrf, "Idempotency-Key": "revoke-replay-0001"}
    url = f"/api/v1/runners/{setup.runner.id}/revoke"
    first = setup.owner.client.post(url, json={"agents": "stop"}, headers=headers)
    again = setup.owner.client.post(url, json={"agents": "stop"}, headers=headers)
    assert first.status_code == again.status_code == 200
    assert first.json()["on_runner_revoke"] == again.json()["on_runner_revoke"]


def test_the_policy_field_and_the_instance_floor(
    make_client: ClientFactory, migrated: Engine
) -> None:
    s = setup_with(make_client, migrated, on_runner_revoke="stop_floor")
    assert s.owner.get("/projects/maity").json()["policy"]["on_runner_revoke"] == "inherit"
    refused = set_policy(s, "keep")
    assert refused.json()["error"]["details"]["fields"] == {"policy.on_runner_revoke": "stop_floor"}
    assert set_policy(s, "unknown").json()["error"]["details"]["fields"] == {
        "policy.on_runner_revoke": "unknown"
    }
    first = running(s)
    answer = s.owner.post(f"/runners/{s.runner.id}/revoke", {})
    assert answer.json()["on_runner_revoke"][0]["rule"] == "stop"  # inherit under the floor
    assert placement(s, first["id"])["closed_reason"] == "runner_revoked"


def test_a_due_credential_shows_as_revoked_before_it_is_used(setup: Setup) -> None:
    assert set_policy(setup, "stop").status_code == 200
    first = running(setup)
    revoke(setup)
    url = f"/projects/maity/members/{setup.agent.id}/credentials"
    [before] = [
        c for c in setup.owner.get(url).json()["items"] if c["id"] == setup.agent.credential_id
    ]
    assert before["revoked_at"] is None  # still within its grace
    later(first["stop_grace_seconds"] + 1)
    [after] = [
        c for c in setup.owner.get(url).json()["items"] if c["id"] == setup.agent.credential_id
    ]
    assert (after["revoked_reason"], after["revoked_by"]) == ("runner_revoked", setup.owner.id)
    view = setup.owner.get(f"/projects/maity/members/{setup.agent.id}").json()
    assert view["credentials"]["active"] == 0
