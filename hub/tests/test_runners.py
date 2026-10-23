"""docs/api.md §15.1–15.3: the runner as a caller, pairing, and the owner's runner calls."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.routes import runners as runner_routes
from tests import flow
from tests.conftest import ClientFactory
from tests.test_auth_agent import signed


@dataclass(frozen=True)
class Runner:
    id: str
    credential_id: str
    value: str


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def enroll(owner: flow.Human, **body: Any) -> dict[str, Any]:
    body.setdefault("name", "home-laptop")
    response = owner.post("/runners/enrollments", body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def exchange(client: TestClient, created: dict[str, Any], code: str | None = None) -> Any:
    token = created["pair_url"].rsplit("/", 1)[1]
    return client.post(
        f"/api/v1/runners/pair/{token}",
        json={"code": code or created["code"], "client": "maity-cli/0.3.0"},
    )


def paired(make_client: ClientFactory, owner: flow.Human, **body: Any) -> Runner:
    response = exchange(make_client(), enroll(owner, **body))
    assert response.status_code == 201, response.text
    return Runner(
        response.headers["Maity-Runner-Id"], response.headers["Maity-Credential-Id"], response.text
    )


def call(client: TestClient, runner: Runner, method: str, path: str) -> Any:
    return client.request(method, path, headers=signed(runner, method, path))


def error(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


# --- pairing -----------------------------------------------------------------------------


def test_the_pairing_line_is_shown_once(owner: flow.Human) -> None:
    created = enroll(owner)
    token = created["pair_url"].rsplit("/", 1)[1]
    assert created["runner_id"] is None  # a new runner exists from the exchange on
    assert created["pair_url"] == f"https://hub.example/r/{token}"
    assert created["pair_line"] == (
        f"maity runner pair https://hub.example/r/{token} --code {created['code']}"
    )
    listed = owner.get("/runners/enrollments")
    assert [e["id"] for e in listed.json()["items"]] == [created["id"]]
    assert set(listed.json()["items"][0]) == {
        "id",
        "runner_id",
        "name",
        "attach",
        "created_at",
        "expires_at",
        "used_at",
        "burned",
        "revoked_at",
    }
    assert token not in listed.text and created["code"] not in listed.text


def test_the_exchange_answers_the_credential_once(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    created = enroll(owner)
    response = exchange(make_client(), created)
    assert response.status_code == 201
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["Maity-Signing"] == "required"
    assert response.headers["Maity-Attached"] == ""
    assert response.headers["Maity-Hub"] == "https://hub.example"
    credential_id = response.headers["Maity-Credential-Id"]
    assert credential_id.startswith("rcrd-")
    assert response.text.startswith(f"mty1.{credential_id}.")
    again = exchange(make_client(), created)
    assert (again.status_code, error(again)) == (404, "not_found")
    [runner] = owner.get("/runners").json()["items"]
    assert runner["id"] == response.headers["Maity-Runner-Id"]
    assert (runner["name"], runner["credential_state"]) == ("home-laptop", "active")
    assert runner["credential"]["id"] == credential_id
    assert response.text not in owner.get(f"/runners/{runner['id']}").text


def test_three_wrong_codes_burn_the_enrollment(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    created = enroll(owner)
    for _ in range(3):
        wrong = exchange(make_client(), created, code="AAAA-AAAA-AAAA")
        assert (wrong.status_code, error(wrong)) == (403, "code_invalid")
    late = exchange(make_client(), created)
    assert (late.status_code, error(late)) == (404, "not_found")
    assert owner.get("/runners/enrollments").json()["items"][0]["burned"] is True
    assert owner.get("/runners").json()["items"] == []


def test_the_code_is_read_like_a_join_code(make_client: ClientFactory, owner: flow.Human) -> None:
    created = enroll(owner)
    sloppy = created["code"].replace("-", " ").lower()
    assert exchange(make_client(), created, code=sloppy).status_code == 201


def test_pairing_over_plain_http_follows_the_join_rule(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    created = enroll(owner)
    plain = exchange(make_client(base_url="http://hub.example"), created)
    assert (plain.status_code, error(plain)) == (403, "insecure_transport")
    # The refusal consumed nothing: the code still works.
    flagged = make_client(base_url="http://hub.example", allow_plain_http=True)
    assert exchange(flagged, created).status_code == 201


def test_the_exchange_takes_no_credential(make_client: ClientFactory, owner: flow.Human) -> None:
    created = enroll(owner)
    token = created["pair_url"].rsplit("/", 1)[1]
    response = make_client().post(
        f"/api/v1/runners/pair/{token}",
        json={"code": created["code"], "client": "x"},
        headers={"Authorization": "Bearer whatever"},
    )
    assert (response.status_code, error(response)) == (403, "forbidden")
    assert exchange(make_client(), created).status_code == 201


def test_the_exchange_is_rate_limited_per_address(make_client: ClientFactory) -> None:
    client = make_client(peer="198.51.100.9")
    for i in range(10):
        response = client.post(f"/api/v1/runners/pair/nope{i}", json={"code": "x", "client": "x"})
        assert response.status_code == 404
    limited = client.post("/api/v1/runners/pair/nope", json={"code": "x", "client": "x"})
    assert (limited.status_code, error(limited)) == (429, "rate_limited")
    assert int(limited.headers["Retry-After"]) > 0


def test_there_is_no_pairing_page(make_client: ClientFactory, owner: flow.Human) -> None:
    token = enroll(owner)["pair_url"].rsplit("/", 1)[1]
    client = make_client()
    page = client.get(f"/r/{token}", headers={"Accept": "text/html"})
    assert (page.status_code, error(page)) == (404, "not_found")
    assert client.get(f"/api/v1/runners/pair/{token}").status_code == 405


def test_the_access_log_masks_pairing_tokens(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="maity_hub.access"):
        make_client().get("/r/SECRET-TOKEN")
        make_client().post("/api/v1/runners/pair/SECRET-TOKEN", json={"code": "x", "client": "x"})
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.access"]
    assert lines == ["GET /r/… 404", "POST /api/v1/runners/pair/… 404"]


# --- enrollments -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"name": "x", "ttl_seconds": 900}, {"name": "string_pattern_mismatch"}),
        ({"ttl_seconds": 59}, {"ttl_seconds": "out_of_range"}),
        ({"ttl_seconds": 901}, {"ttl_seconds": "out_of_range"}),
        ({"name": None}, {"name": "required"}),
        ({"runner_id": "rnr-nope", "name": None}, {"runner_id": "not_yours"}),
    ],
)
def test_an_enrollment_validates(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    response = owner.post("/runners/enrollments", {"name": "home-laptop", **body})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == fields


def test_a_name_is_unique_among_ones_runners(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    first, second = enroll(owner), enroll(owner)  # both before either is paired
    assert exchange(make_client(), first).status_code == 201
    taken = owner.post("/runners/enrollments", {"name": "home-laptop"})
    assert taken.json()["error"]["details"]["fields"] == {"name": "taken"}
    # The second exchange is refused and leaves its enrollment unused.
    late = exchange(make_client(), second)
    assert (late.status_code, late.json()["error"]["details"]["fields"]) == (
        400,
        {"name": "taken"},
    )
    unused = [
        e for e in owner.get("/runners/enrollments").json()["items"] if e["id"] == second["id"]
    ]
    assert unused[0]["used_at"] is None
    runner_id = owner.get("/runners").json()["items"][0]["id"]
    assert owner.patch(f"/runners/{runner_id}", {"name": "old-laptop"}).status_code == 200
    assert exchange(make_client(), second).status_code == 201
    names = [r["name"] for r in owner.get("/runners").json()["items"]]
    assert names == ["home-laptop", "old-laptop"]
    other = flow.human(make_client, migrated, "colleague")
    assert other.post("/runners/enrollments", {"name": "home-laptop"}).status_code == 201


def test_revoking_an_enrollment(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    created = enroll(owner)
    other = flow.human(make_client, migrated, "colleague")
    assert other.delete(f"/runners/enrollments/{created['id']}").status_code == 404
    revoked = owner.delete(f"/runners/enrollments/{created['id']}")
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    assert owner.delete(f"/runners/enrollments/{created['id']}").status_code == 200
    assert exchange(make_client(), created).status_code == 404
    used = enroll(owner, name="other")
    assert exchange(make_client(), used).status_code == 201
    refused = owner.delete(f"/runners/enrollments/{used['id']}")
    assert (refused.status_code, error(refused)) == (409, "invalid_transition")
    assert refused.json()["error"]["details"] == {"from": "used", "to": "revoked"}


def test_an_agent_cannot_pair_runners(make_client: ClientFactory, owner: flow.Human) -> None:
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    response = agent.post("/runners/enrollments", {"name": "agent-box"})
    assert (response.status_code, error(response)) == (403, "forbidden")


# --- the runner as a caller ----------------------------------------------------------------


def test_a_runner_credential_as_bearer_is_signature_required(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    response = make_client().get("/api/v1/me", headers={"Authorization": f"Bearer {runner.value}"})
    assert (response.status_code, error(response)) == (403, "signature_required")
    assert response.json()["error"]["details"] == {}
    # Refused before any side effect.
    with migrated.begin() as conn:
        used = conn.execute(
            select(t.runner_credential.c.last_used_at).where(
                t.runner_credential.c.id == runner.credential_id
            )
        ).scalar()
    assert used is None
    wrong = runner.value[:-4] + "AAAA"
    unknown = make_client().get("/api/v1/me", headers={"Authorization": f"Bearer {wrong}"})
    assert (unknown.status_code, error(unknown)) == (401, "unauthenticated")


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/api/v1/projects/maity", 404, "not_found"),
        ("GET", "/api/v1/projects/maity/tasks", 404, "not_found"),
        ("GET", "/api/v1/projects/maity/members", 404, "not_found"),
        ("GET", "/api/v1/projects/maity/events", 404, "not_found"),
        ("GET", "/api/v1/projects/maity/requests", 404, "not_found"),
        ("GET", "/api/v1/projects/elsewhere/tasks", 404, "not_found"),
        ("GET", "/api/v1/projects", 403, "forbidden"),
        ("GET", "/api/v1/me", 403, "forbidden"),
        ("POST", "/api/v1/me/resume", 403, "forbidden"),
        ("GET", "/api/v1/runners", 403, "forbidden"),
        ("GET", "/api/v1/runners/enrollments", 403, "forbidden"),
    ],
)
def test_a_runner_reaches_no_project_and_no_other_route(
    make_client: ClientFactory, owner: flow.Human, method: str, path: str, status: int, code: str
) -> None:
    flow.project(owner)
    runner = paired(make_client, owner)
    response = call(make_client(), runner, method, path)
    assert (response.status_code, error(response)) == (status, code)
    assert response.json()["error"]["details"] == {}


def test_a_wrong_signature_fails_before_the_route_decision(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    forged = Runner(runner.id, runner.credential_id, runner.value[:-4] + "AAAA")
    response = call(make_client(), forged, "GET", "/api/v1/projects")
    assert (response.status_code, error(response)) == (401, "signature_invalid")


def test_a_runner_credential_in_a_payload_is_revoked(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    looks_like = runner.value[:-4] + "AAAA"
    refused = make_client().post("/api/v1/auth/login", json={"handle": looks_like, "password": "x"})
    assert (refused.status_code, error(refused)) == (400, "credential_in_payload")
    assert owner.get(f"/runners/{runner.id}").json()["credential_state"] == "active"
    leaked = make_client().post(
        "/api/v1/auth/login", json={"handle": runner.value, "password": "x"}
    )
    assert (leaked.status_code, error(leaked)) == (400, "credential_in_payload")
    view = owner.get(f"/runners/{runner.id}").json()
    assert view["credential_state"] == "revoked"
    assert view["credential"]["revoked_reason"] == "leaked_in_payload"
    after = call(make_client(), runner, "GET", "/api/v1/me")
    assert (after.status_code, error(after)) == (401, "credential_revoked")


# --- the owner's runner calls --------------------------------------------------------------


def test_a_re_pair_revokes_the_old_credential_and_keeps_the_runner(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    first = paired(make_client, owner)
    created = enroll(owner, name=None, runner_id=first.id)
    assert created["runner_id"] == first.id
    response = exchange(make_client(), created)
    assert response.headers["Maity-Runner-Id"] == first.id
    old = call(make_client(), first, "GET", "/api/v1/me")
    assert (old.status_code, error(old)) == (401, "credential_revoked")
    assert old.json()["error"]["details"] == {"reason": "repaired"}
    [runner] = owner.get("/runners").json()["items"]
    assert runner["credential"]["id"] == response.headers["Maity-Credential-Id"]
    assert runner["credential_state"] == "active"
    with_name = owner.post("/runners/enrollments", {"name": "x-y", "runner_id": first.id})
    assert with_name.json()["error"]["details"]["fields"] == {"name": "with_runner_id"}


def test_a_runner_is_its_owners(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    other = flow.human(make_client, migrated, "colleague")
    assert other.get(f"/runners/{runner.id}").status_code == 404
    assert other.get("/runners").json()["items"] == []
    assert other.post(f"/runners/{runner.id}/revoke").status_code == 404
    assert other.delete(f"/runners/{runner.id}").status_code == 404
    re_pair = other.post("/runners/enrollments", {"runner_id": runner.id})
    assert re_pair.json()["error"]["details"]["fields"] == {"runner_id": "not_yours"}


def test_the_runner_view(make_client: ClientFactory, owner: flow.Human) -> None:
    runner = paired(make_client, owner)
    view = owner.get(f"/runners/{runner.id}").json()
    assert view["owner_id"] == owner.id
    assert (view["presence"], view["listening"], view["last_seen_at"]) == ("offline", False, None)
    assert (view["version"], view["capabilities"], view["projects"]) == (None, None, [])
    assert view["removed_at"] is None
    assert set(view["credential"]) == {
        "id",
        "created_at",
        "last_used_at",
        "revoked_at",
        "revoked_reason",
    }


def test_renaming_a_runner(make_client: ClientFactory, owner: flow.Human) -> None:
    runner = paired(make_client, owner)
    paired(make_client, owner, name="build-box")
    renamed = owner.patch(f"/runners/{runner.id}", {"name": "studio"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "studio"
    assert owner.patch(f"/runners/{runner.id}", {"name": "studio"}).status_code == 200
    taken = owner.patch(f"/runners/{runner.id}", {"name": "build-box"})
    assert taken.json()["error"]["details"]["fields"] == {"name": "taken"}


def test_revoking_a_runner(make_client: ClientFactory, owner: flow.Human) -> None:
    runner = paired(make_client, owner)
    revoked = owner.post(f"/runners/{runner.id}/revoke", {"reason": "laptop stolen"})
    assert revoked.status_code == 200
    assert revoked.json()["credential_state"] == "revoked"
    assert revoked.json()["credential"]["revoked_reason"] == "laptop stolen"
    after = call(make_client(), runner, "GET", "/api/v1/me")
    assert (after.status_code, error(after)) == (401, "credential_revoked")
    assert owner.post(f"/runners/{runner.id}/revoke").status_code == 200  # as it is


def test_removing_a_runner(make_client: ClientFactory, owner: flow.Human) -> None:
    runner = paired(make_client, owner)
    pending = enroll(owner, name=None, runner_id=runner.id)
    removed = owner.delete(f"/runners/{runner.id}")
    assert removed.status_code == 200
    body = removed.json()
    assert body["removed_at"] is not None and body["still_running"] == []
    assert body["credential_state"] == "revoked"
    assert body["credential"]["revoked_reason"] == "runner_removed"
    assert owner.delete(f"/runners/{runner.id}").json()["removed_at"] == body["removed_at"]
    assert owner.get("/runners").json()["items"] == []
    assert owner.get(f"/runners/{runner.id}").json()["removed_at"] == body["removed_at"]
    gone = call(make_client(), runner, "GET", "/api/v1/me")
    assert (gone.status_code, error(gone)) == (401, "credential_revoked")
    # An open re-pair would bring it back: revoked with it.
    assert exchange(make_client(), pending).status_code == 404
    refused = owner.patch(f"/runners/{runner.id}", {"name": "again"})
    assert (refused.status_code, error(refused)) == (409, "invalid_transition")
    # Its name is free again.
    assert paired(make_client, owner).id != runner.id


# --- review: races and edges ------------------------------------------------------------


def test_a_revocation_without_a_reason_reads_revoked(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    revoked = owner.post(f"/runners/{runner.id}/revoke").json()
    assert revoked["credential"]["revoked_reason"] == "revoked"


def test_a_credential_of_a_removed_runner_is_refused(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    with migrated.begin() as conn:  # a credential that outlived its runner, by hand
        conn.execute(
            update(t.runner)
            .where(t.runner.c.id == runner.id)
            .values(removed_at=clock.now(), active=None)
        )
    refused = call(make_client(), runner, "GET", "/api/v1/me")
    assert (refused.status_code, error(refused)) == (401, "credential_revoked")
    # The runner learns what a stop closed; under keep that is nothing (§15.3).
    assert refused.json()["error"]["details"] == {"reason": "runner_removed", "stop": []}


def test_removing_a_runner_while_it_re_pairs_leaves_no_live_credential(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    for i in range(5):
        runner = paired(make_client, owner, name=f"racer-{i}")
        created = enroll(owner, name=None, runner_id=runner.id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pairing = pool.submit(exchange, make_client(), created)
            removal = pool.submit(owner.delete, f"/runners/{runner.id}")
            assert removal.result(timeout=30).status_code == 200
            assert pairing.result(timeout=30).status_code in (201, 404)
        with migrated.begin() as conn:
            live = conn.execute(
                select(t.runner_credential.c.id).where(
                    t.runner_credential.c.runner_id == runner.id,
                    t.runner_credential.c.live.is_(True),
                )
            ).all()
        assert live == []


def test_a_rename_that_loses_the_race_for_a_name_is_taken(
    make_client: ClientFactory, owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = paired(make_client, owner)
    paired(make_client, owner, name="build-box")
    # The check passes as it would for two renames at once; the constraint decides.
    monkeypatch.setattr(runner_routes, "_name_taken", lambda *_args, **_kwargs: False)
    taken = owner.patch(f"/runners/{runner.id}", {"name": "build-box"})
    assert (taken.status_code, taken.json()["error"]["details"]["fields"]) == (
        400,
        {"name": "taken"},
    )


def test_enrollments_are_paged(owner: flow.Human) -> None:
    ids = [enroll(owner, name=f"box-{i}")["id"] for i in range(3)]
    first = owner.get("/runners/enrollments?limit=2").json()
    assert [e["id"] for e in first["items"]] == ids[::-1][:2]
    rest = owner.get(f"/runners/enrollments?limit=2&cursor={first['next_cursor']}").json()
    assert [e["id"] for e in rest["items"]] == ids[:1] and rest["next_cursor"] is None
    bad = owner.get("/runners/enrollments?cursor=nonsense")
    assert bad.json()["error"]["details"]["fields"] == {"cursor": "invalid"}
