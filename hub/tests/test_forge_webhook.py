"""docs/api.md §17.4: the forge webhook — its secret sealed with MAITY_SECRET_KEY, signed
deliveries as triggers for the probe, refusals that tell nobody whether a project
exists, the limits before the body, and automatic deploys."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import forge, forge_webhook, probe, secretbox
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import READER, REPO, TOKEN, FakeGitHub

KEY = os.urandom(32)
HOOK = "/api/v1/projects/maity/forge/webhook"


@pytest.fixture(autouse=True)
def _limits() -> None:
    for limiter in (forge_webhook.VERIFIED, forge_webhook.UNVERIFIED, forge_webhook.NOBODY):
        limiter.reset()


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, forge_github_token=TOKEN, secret_key=KEY)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(forge.Forge, "_get", lambda _self, path: fake(path))
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    return fake


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine, github: FakeGitHub) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", repository=REPO)
    return owner


def secret(owner: flow.Human) -> str:
    response = owner.post("/projects/maity/forge/webhook/secret", {})
    assert response.status_code == 201, response.text
    value: str = response.json()["secret"]
    return value


def deliver(
    client: Any, body: dict[str, Any], key: str | None, event: str = "ping", path: str = HOOK
) -> Any:
    raw = json.dumps(body).encode()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "d-1",
        "Content-Type": "application/json",
    }
    if key is not None:
        headers["X-Hub-Signature-256"] = (
            "sha256=" + hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
        )
    return client.post(path, content=raw, headers=headers)


def jobs(owner: flow.Human) -> list[Any]:
    worker = owner.client.app.state.probe  # type: ignore[attr-defined]
    found = []
    while not worker.jobs.empty():
        found.append(worker.jobs.get_nowait())
    return found


# --- the secret ------------------------------------------------------------------------


def test_the_secret_is_answered_once_and_sealed_at_rest(
    owner: flow.Human, migrated: Engine
) -> None:
    response = owner.post("/projects/maity/forge/webhook/secret", {})
    body = response.json()
    assert body["url"] == "https://hub.example/api/v1/projects/maity/forge/webhook"
    view = owner.get("/projects/maity/forge/webhook").json()
    assert view["configured"] is True and "secret" not in view
    with migrated.connect() as conn:
        row = conn.execute(select(t.forge_webhook)).one()
        changed = conn.execute(
            select(t.event).where(t.event.c.kind == "forge_webhook_changed")
        ).one()
    assert body["secret"].encode() not in row.secret_sealed
    assert (
        secretbox.open_sealed(KEY, forge_webhook.FIELD, row.secret_sealed)
        == body["secret"].encode()
    )
    assert changed.audience == ["role:owner", "role:admin"]
    assert (
        body["secret"] not in json.dumps(changed.payload) and changed.payload["action"] == "created"
    )


def test_rotating_stops_the_old_secret(owner: flow.Human) -> None:
    old = secret(owner)
    new = secret(owner)
    assert deliver(owner.client, {}, old).status_code == 401
    assert deliver(owner.client, {}, new).status_code == 202


def test_without_the_instance_key_no_secret_is_stored(
    make_client: ClientFactory, migrated: Engine, settings: Settings, github: FakeGitHub
) -> None:
    client = make_client(secret_key=None)
    human = flow.human(lambda **_: client, migrated)
    flow.project(human, "maity", repository=REPO)
    response = human.post("/projects/maity/forge/webhook/secret", {})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "secret_key_missing")


def test_an_agent_admin_does_not_manage_the_webhook(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    assert agent.post("/projects/maity/forge/webhook/secret", {}).status_code == 403
    assert agent.get("/projects/maity/forge/webhook").status_code == 403


def test_removing_the_secret_refuses_deliveries(owner: flow.Human) -> None:
    key = secret(owner)
    assert owner.delete("/projects/maity/forge/webhook/secret").status_code == 200
    assert deliver(owner.client, {}, key).status_code == 401


# --- deliveries ------------------------------------------------------------------------


def test_refusals_look_alike_whether_the_project_exists_or_not(owner: flow.Human) -> None:
    secret(owner)
    unsigned = deliver(owner.client, {}, None)
    wrong = deliver(owner.client, {}, "not the secret")
    nobody = deliver(owner.client, {}, "x", path="/api/v1/projects/nope/forge/webhook")
    for response in (unsigned, wrong, nobody):
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "webhook_signature",
            "message": response.json()["error"]["message"],
            "details": {},
        }
    assert len({r.json()["error"]["message"] for r in (unsigned, wrong, nobody)}) == 1


def test_a_ping_is_accepted_and_recorded(owner: flow.Human) -> None:
    key = secret(owner)
    response = deliver(owner.client, {"zen": "hi"}, key)
    assert (response.status_code, response.json()) == (202, {})
    view = owner.get("/projects/maity/forge/webhook").json()
    assert view["last_result"] == "ok" and view["last_delivery_at"]


def test_an_unverified_request_records_nothing(owner: flow.Human) -> None:
    secret(owner)
    deliver(owner.client, {}, "wrong")
    assert owner.get("/projects/maity/forge/webhook").json()["last_delivery_at"] is None


def test_a_closed_pull_request_makes_the_probe_look_when_the_ticker_is_on(
    owner: flow.Human,
) -> None:
    key = secret(owner)
    body = {"action": "closed", "pull_request": {"number": 7, "merged": True}}
    assert deliver(owner.client, body, key, "pull_request").status_code == 202
    assert jobs(owner) == [], "the ticker is off: nothing is announced"
    assert owner.get("/projects/maity/forge/webhook").json()["last_result"] == "ignored"
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    assert deliver(owner.client, body, key, "pull_request").status_code == 202
    [job] = jobs(owner)
    assert job[0] == "merges" and job[2] == "d-1"


def test_a_successful_deployment_is_announced_once_to_everyone_waking_no_one(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    key = secret(owner)
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    github.answers["/repos/acme/maity/deployments/42"] = {
        "environment": "production",
        "sha": "1cddc4d" + "0" * 33,
        "ref": "main",
    }
    github.answers["/repos/acme/maity/deployments/42/statuses?per_page=1"] = [
        {"state": "success", "log_url": "https://ci.example/run/9"}
    ]
    assert (
        deliver(
            owner.client,
            {"deployment": {"id": 42}, "deployment_status": {"state": "success"}},
            key,
            "deployment_status",
        ).status_code
        == 202
    )
    [job] = jobs(owner)
    with migrated.connect() as conn:
        pid = conn.execute(select(t.project.c.id)).scalar_one()
    assert probe.announce_deploy(migrated, READER, pid, job[2], job[3]) is True
    assert (
        probe.announce_deploy(migrated, READER, pid, job[2], job[3]) is False
    ), "one item per deploy"
    with migrated.connect() as conn:
        row = conn.execute(select(t.event).where(t.event.c.kind == "ticker")).one()
    assert row.audience == ["all"] and row.payload["reasons"] == []
    assert row.payload["text"] == "Deployed 1cddc4d to production"
    assert row.payload["origin"] == {"via": "webhook", "delivery": "d-1"}
    assert row.payload["dedupe_key"] == "deploy:production:1cddc4d" + "0" * 33


def test_a_deployment_the_forge_does_not_call_successful_writes_nothing(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    github.answers["/repos/acme/maity/deployments/43"] = {"environment": "staging", "sha": "a" * 40}
    github.answers["/repos/acme/maity/deployments/43/statuses?per_page=1"] = [{"state": "failure"}]
    with migrated.connect() as conn:
        pid = conn.execute(select(t.project.c.id)).scalar_one()
    assert probe.announce_deploy(migrated, READER, pid, 43, "d-2") is False


def test_a_body_over_one_mebibyte_is_refused(owner: flow.Human) -> None:
    key = secret(owner)
    response = deliver(owner.client, {"padding": "x" * (1024 * 1024)}, key)
    assert (response.status_code, response.json()["error"]["code"]) == (413, "payload_too_large")


def test_sixty_bad_requests_a_minute_then_rate_limited_alike(owner: flow.Human) -> None:
    secret(owner)
    for _ in range(60):
        deliver(owner.client, {}, "wrong")
        deliver(owner.client, {}, "x", path="/api/v1/projects/nope/forge/webhook")
    known = deliver(owner.client, {}, "wrong")
    unknown = deliver(owner.client, {}, "x", path="/api/v1/projects/nope/forge/webhook")
    for response in (known, unknown):
        assert response.status_code == 429 and response.json()["error"]["code"] == "rate_limited"
        assert response.headers["Retry-After"]


def test_a_secret_the_key_cannot_open_fails_loud(
    owner: flow.Human, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    key = secret(owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.forge_webhook).values(
                secret_sealed=secretbox.seal(os.urandom(32), forge_webhook.FIELD, b"x")
            )
        )
    assert deliver(owner.client, {}, key).status_code == 401
    assert any("does not open" in r.getMessage() for r in caplog.records)


def test_a_bad_instance_key_stops_the_hub() -> None:
    from maity_hub.config import ConfigError

    with pytest.raises(ConfigError):
        Settings.from_env({"MAITY_SECRET_KEY": "dG9vIHNob3J0"})
