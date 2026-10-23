"""docs/api.md §17.4: the forge webhook — its secret sealed with MAITY_SECRET_KEY, signed
deliveries as triggers for the probe, refusals that tell nobody whether a project
exists, the limits before the body, and automatic deploys."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import forge, forge_webhook, probe, secretbox
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import READER, REPO, TOKEN, FakeGitHub
from tests.test_ticker_merges import merged, project_id

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


def signature(key: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


def deliver(
    client: Any,
    body: Any,
    key: str | None,
    event: str = "ping",
    path: str = HOOK,
    delivery: str = "d-1",
) -> Any:
    raw = json.dumps(body).encode()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "Content-Type": "application/json",
    }
    if key is not None:
        headers["X-Hub-Signature-256"] = signature(key, raw)
    return client.post(path, content=raw, headers=headers)


UNKNOWN = "/api/v1/projects/nope/forge/webhook"


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
        secretbox.open_sealed(KEY, forge_webhook.field(row.project_id), row.secret_sealed)
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


def test_bad_requests_to_unknown_slugs_rate_limit_a_known_one_alike(owner: flow.Human) -> None:
    secret(owner)
    for _ in range(60):
        assert deliver(owner.client, {}, "x", path=UNKNOWN).status_code == 401
    known = deliver(owner.client, {}, "wrong")
    unknown = deliver(owner.client, {}, "x", path=UNKNOWN)
    for response in (known, unknown):
        assert response.status_code == 429 and response.json()["error"]["code"] == "rate_limited"
        assert response.headers["Retry-After"]


def test_bad_requests_to_a_known_slug_rate_limit_unknown_ones_alike(owner: flow.Human) -> None:
    secret(owner)
    for _ in range(60):
        assert deliver(owner.client, {}, "wrong").status_code == 401
    known = deliver(owner.client, {}, "wrong")
    unknown = deliver(owner.client, {}, "x", path=UNKNOWN)
    for response in (known, unknown):
        assert response.status_code == 429 and response.json()["error"]["code"] == "rate_limited"


def test_a_verified_delivery_is_never_refused_for_what_others_sent_from_its_address(
    owner: flow.Human,
) -> None:
    key = secret(owner)
    for _ in range(60):
        deliver(owner.client, {}, "x", path=UNKNOWN)
    assert deliver(owner.client, {}, "x", path=UNKNOWN).status_code == 429
    assert deliver(owner.client, {}, key).status_code == 202


def test_sixty_verified_deliveries_a_minute_per_project(owner: flow.Human) -> None:
    key = secret(owner)
    for _ in range(60):
        assert deliver(owner.client, {}, key).status_code == 202
    over = deliver(owner.client, {}, key)
    assert (over.status_code, over.json()["error"]["code"]) == (429, "rate_limited")
    assert owner.get("/projects/maity/forge/webhook").json()["last_result"] == "rate_limited"


def test_a_body_declared_too_large_or_of_no_length_is_refused_alike(owner: flow.Human) -> None:
    key = secret(owner)
    big = deliver(owner.client, {"padding": "x" * (1024 * 1024)}, key)
    big_unknown = deliver(owner.client, {"padding": "x" * (1024 * 1024)}, "x", path=UNKNOWN)

    def chunked() -> Any:
        yield b"{}"

    headers = {"X-GitHub-Event": "ping", "X-Hub-Signature-256": signature(key, b"{}")}
    unsized = owner.client.post(HOOK, content=chunked(), headers=headers)
    unsized_unknown = owner.client.post(UNKNOWN, content=chunked(), headers=headers)
    for response in (big, big_unknown, unsized, unsized_unknown):
        assert (response.status_code, response.json()["error"]["code"]) == (
            413,
            "payload_too_large",
        )


def held(migrated: Engine, path: str, n: int) -> tuple[list[int], int]:
    """`n` requests to `path` from one address whose bodies are held back: which were
    answered before any body came, and how many began to read theirs."""
    read = 0

    async def run() -> list[int]:
        release = asyncio.Event()

        async def receive() -> dict[str, Any]:
            nonlocal read
            read += 1
            await release.wait()
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(_message: Any) -> None:
            return None

        def scope() -> dict[str, Any]:
            return {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [(b"content-length", b"2"), (b"x-hub-signature-256", b"sha256=0")],
                "state": {"origin": SimpleNamespace(address="192.0.2.7")},
            }

        tasks = [
            asyncio.create_task(forge_webhook.handle(scope(), receive, send, migrated, KEY))
            for _ in range(n)
        ]
        for _ in range(500):  # every task at its body or answered, at most five seconds
            if read + sum(task.done() for task in tasks) >= n:
                break
            await asyncio.sleep(0.01)
        early = [task.result() for task in tasks if task.done()]
        release.set()
        await asyncio.gather(*tasks)
        return early

    return asyncio.run(run()), read


def test_parallel_requests_read_at_most_sixty_bodies_per_project_and_address(
    owner: flow.Human, migrated: Engine
) -> None:
    secret(owner)
    assert held(migrated, HOOK, 61) == ([429], 60), "the 61st is refused before its body"


def test_a_held_back_body_hangs_alike_for_every_slug(owner: flow.Human, migrated: Engine) -> None:
    # One request each: neither is answered before its body comes (A's ruling on #235).
    secret(owner)
    assert held(migrated, HOOK, 1) == ([], 1)
    forge_webhook.NOBODY.reset()
    forge_webhook.UNVERIFIED.reset()
    assert held(migrated, UNKNOWN, 1) == ([], 1)


def test_parallel_requests_to_unknown_slugs_read_at_most_sixty_bodies_per_address(
    owner: flow.Human, migrated: Engine
) -> None:
    assert held(migrated, UNKNOWN, 61) == ([429], 60)


def test_a_body_nested_too_deep_is_invalid(owner: flow.Human) -> None:
    key = secret(owner)
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    raw = b"[" * 100_000 + b"]" * 100_000
    headers = {"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature(key, raw)}
    response = owner.client.post(HOOK, content=raw, headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (400, "invalid")


def test_an_unrelated_event_is_ignored(owner: flow.Human) -> None:
    key = secret(owner)
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    body = {"action": "closed", "pull_request": {"number": 7}, "deployment": {"id": 4}}
    for event in ("push", "pull_request_review", "deployment"):
        assert deliver(owner.client, body, key, event).status_code == 202
    assert deliver(owner.client, {"action": "opened"}, key, "pull_request").status_code == 202
    assert deliver(owner.client, {"deployment": {"id": "4"}}, key, "deployment_status")
    assert jobs(owner) == []
    assert owner.get("/projects/maity/forge/webhook").json()["last_result"] == "ignored"


def test_a_signed_body_that_is_not_an_object_is_invalid_in_the_envelope(
    owner: flow.Human,
) -> None:
    key = secret(owner)
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    for body in ([1], "text", 7):
        response = deliver(owner.client, body, key, "pull_request")
        assert (response.status_code, response.json()["error"]["code"]) == (400, "invalid")
    response = deliver(owner.client, {"pull_request": [1], "action": "closed"}, key, "pull_request")
    assert response.status_code == 202
    [job] = jobs(owner)
    assert job[3] is None


def test_two_signature_headers_are_refused(owner: flow.Human) -> None:
    key = secret(owner)
    raw = b"{}"
    headers = [
        ("X-GitHub-Event", "ping"),
        ("X-Hub-Signature-256", signature(key, raw)),
        ("X-Hub-Signature-256", "sha256=" + "0" * 64),
    ]
    assert owner.client.post(HOOK, content=raw, headers=headers).status_code == 401
    assert owner.client.post(HOOK, content=raw, headers=headers[:2]).status_code == 202


def test_a_delivery_id_is_kept_only_in_its_shape(owner: flow.Human) -> None:
    key = secret(owner)
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    body = {"action": "closed", "pull_request": {"number": 7}}
    for given, kept in (
        ("72d3162e-cc78-11e3-81ab-4c9367dc0958", "72d3162e-cc78-11e3-81ab-4c9367dc0958"),
        ("x" * 20_000, None),
        ("x" * 65, None),
        ("a b", None),
    ):
        assert deliver(owner.client, body, key, "pull_request", delivery=given).status_code == 202
        assert [job[2] for job in jobs(owner)] == [kept]


def test_the_secret_appears_in_no_log(owner: flow.Human, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    key = secret(owner)
    deliver(owner.client, {}, key)
    deliver(owner.client, {}, "wrong")
    owner.get("/projects/maity/forge/webhook")
    assert caplog.records
    assert not [r for r in caplog.records if key in r.getMessage()]


def test_only_the_named_merge_carries_the_delivery(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    merged(github, 7, [])
    merged(github, 8, [])
    assert probe.announce_merges(migrated, READER, project_id(migrated), "d-1", 7) == 2
    with migrated.connect() as conn:
        rows = conn.execute(select(t.event).where(t.event.c.kind == "ticker")).all()
    origins = {row.payload["merge"]["pr"]: row.payload["origin"] for row in rows}
    assert origins == {
        7: {"via": "webhook", "delivery": "d-1"},
        8: {"via": "probe", "delivery": None},
    }


def test_a_deployment_out_of_bounds_writes_nothing(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    ok = [{"state": "success"}]
    cases = {
        50: {"environment": "e" * 65, "sha": "a" * 40},
        51: {"environment": "production", "sha": "not a sha"},
        52: {"environment": "production", "sha": "a" * 39},
    }
    for number, found in cases.items():
        github.answers[f"/repos/acme/maity/deployments/{number}"] = found
        github.answers[f"/repos/acme/maity/deployments/{number}/statuses?per_page=1"] = ok
        assert probe.announce_deploy(migrated, READER, project_id(migrated), number, None) is False
    github.answers["/repos/acme/maity/deployments/53"] = {"environment": "e" * 64, "sha": "b" * 64}
    github.answers["/repos/acme/maity/deployments/53/statuses?per_page=1"] = [
        {"state": "success", "log_url": "javascript:alert(1)"}
    ]
    assert probe.announce_deploy(migrated, READER, project_id(migrated), 53, None) is True
    with migrated.connect() as conn:
        row = conn.execute(select(t.event).where(t.event.c.kind == "ticker")).one()
    assert row.subject_id == "e" * 64 + "@" + "b" * 64
    assert row.payload["url"] is None and row.payload["deploy"]["log_url"] is None


def test_a_secret_the_key_does_not_open_counts_as_not_set(
    owner: flow.Human, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    secret(owner)
    assert owner.get("/projects/maity/forge/webhook").json()["configured"] is True
    assert forge_webhook.check_secrets(migrated, KEY) == 0
    assert forge_webhook.check_secrets(migrated, os.urandom(32)) == 1
    assert forge_webhook.check_secrets(migrated, None) == 1
    assert any("cannot be opened (maity)" in r.getMessage() for r in caplog.records)
    with migrated.begin() as conn:
        conn.execute(
            update(t.forge_webhook).values(
                secret_sealed=secretbox.seal(KEY, forge_webhook.field("prj-other"), b"x")
            )
        )
    view = owner.get("/projects/maity/forge/webhook").json()
    assert view["configured"] is False, "a secret copied from another project's row"


def test_a_sealed_value_opens_only_with_its_key_and_field() -> None:
    sealed = secretbox.seal(KEY, "a", b"secret")
    again = secretbox.seal(KEY, "a", b"secret")
    assert sealed[: secretbox.NONCE_BYTES] != again[: secretbox.NONCE_BYTES]
    assert sealed != again
    assert secretbox.open_sealed(KEY, "a", sealed) == b"secret"
    for key, name in ((KEY, "b"), (os.urandom(32), "a")):
        with pytest.raises(secretbox.SealedError):
            secretbox.open_sealed(key, name, sealed)


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
