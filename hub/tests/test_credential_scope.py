"""docs/api.md §2.2: a credential is bound to (agent profile, project). A profile
that is a member of two projects holds two credentials, and each reaches only
its own project."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "alpha")
    flow.project(human, "beta")
    return human


def _two_credentials(owner: flow.Human, make_client: ClientFactory) -> tuple[Any, Any]:
    """One agent profile, joined to alpha and to beta: one credential each."""
    in_alpha = flow.agent(make_client, owner, "alpha")
    created = flow.join(owner, "beta", agent={"id": in_alpha.id})
    response = flow.exchange(make_client(), created)
    assert response.status_code == 201, response.text
    in_beta = flow.Agent(
        in_alpha.client,
        response.text,
        response.headers["Maity-Credential-Id"],
        response.headers["Maity-Member-Id"],
    )
    assert in_beta.id == in_alpha.id  # the same profile
    return in_alpha, in_beta


def test_a_credential_does_not_read_the_profiles_other_project(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    in_alpha, in_beta = _two_credentials(owner, make_client)
    assert in_beta.get("/projects/maintainer/beta/tasks").status_code == 200
    for path in (
        "/projects/maintainer/beta",
        "/projects/maintainer/beta/tasks",
        "/projects/maintainer/beta/members",
    ):
        response = in_alpha.get(path)
        assert response.status_code == 404, path
        assert response.headers["Maity-Error"] == "not_found"
    assert in_alpha.get("/projects/maintainer/beta/events?after=0").status_code == 404


def test_a_credential_does_not_write_into_the_profiles_other_project(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    in_alpha, _ = _two_credentials(owner, make_client)
    response = in_alpha.post("/projects/maintainer/beta/tasks", {"title": "Through the wrong door"})
    assert response.status_code == 404
    with migrated.connect() as conn:
        titles = conn.execute(select(t.card.c.title)).scalars().all()
    assert "Through the wrong door" not in titles


def test_revoking_one_credential_leaves_no_way_in_through_the_other(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    in_alpha, in_beta = _two_credentials(owner, make_client)
    revoked = owner.post(
        f"/projects/maintainer/beta/credentials/{in_beta.credential_id}/revoke",
        {"reason": "rotated"},
    )
    assert revoked.status_code == 200, revoked.text
    assert (
        in_beta.get("/projects/maintainer/beta/tasks").headers["Maity-Error"]
        == "credential_revoked"
    )
    assert in_alpha.get("/projects/maintainer/beta/tasks").status_code == 404
    assert in_alpha.get("/projects/maintainer/alpha/tasks").status_code == 200


def test_an_idempotency_key_does_not_replay_into_another_project(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    in_alpha, _ = _two_credentials(owner, make_client)
    key = {"Idempotency-Key": "scope-test-key-000001"}
    body = {"title": "Once"}
    headers = in_alpha.auth | key
    first = in_alpha.client.post(
        "/api/v1/projects/maintainer/alpha/tasks", json=body, headers=headers
    )
    assert first.status_code == 201, first.text
    again = in_alpha.client.post(
        "/api/v1/projects/maintainer/beta/tasks", json=body, headers=headers
    )
    assert again.status_code == 404
    assert "Idempotent-Replayed" not in again.headers


def test_the_refusal_leaves_no_trace_on_the_credential(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    in_alpha, _ = _two_credentials(owner, make_client)
    with migrated.connect() as conn:
        before = conn.execute(
            select(t.credential.c.last_used_at).where(t.credential.c.id == in_alpha.credential_id)
        ).scalar()
    assert in_alpha.get("/projects/maintainer/beta/tasks").status_code == 404
    with migrated.connect() as conn:
        after = conn.execute(
            select(t.credential.c.last_used_at).where(t.credential.c.id == in_alpha.credential_id)
        ).scalar()
    assert after == before
