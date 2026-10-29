"""docs/api.md §2.2 "Signing required", §3.2 step 7, §3.3, §6.1 `signing`, §10 `last_used_via`."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import DEFAULT_CLI_INSTALL
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_auth_agent import bearer, signed

KEY = {"Idempotency-Key": "signing-test-key-0001"}


@pytest.fixture
def project_id(migrated: Engine) -> str:
    return factory.project(migrated, "maity")


@pytest.fixture
def agent(migrated: Engine, project_id: str) -> factory.Agent:
    owner = factory.human(migrated, "maintainer")
    factory.membership(migrated, project_id, human_id=owner)
    return factory.agent(migrated, project_id, owner)


def _require(engine: Engine, project_id: str, signing: str = "required") -> None:
    with engine.begin() as conn:
        conn.execute(update(t.project).where(t.project.c.id == project_id).values(signing=signing))


def _credential(engine: Engine, agent: factory.Agent) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()


# --- the refusal --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/me"),
        ("POST", "/api/v1/me/resume"),
        ("GET", "/api/v1/projects/maintainer/maity/events?after=0"),
        ("GET", "/api/v1/projects/maintainer/maity/tasks"),
    ],
)
def test_a_bearer_call_is_refused_where_signing_is_required(
    make_client: ClientFactory,
    agent: factory.Agent,
    migrated: Engine,
    project_id: str,
    method: str,
    path: str,
) -> None:
    _require(migrated, project_id)
    body = {"client": "curl"} if method == "POST" else None
    response = make_client().request(method, path, headers=bearer(agent), json=body)
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "signature_required"
    error = response.json()["error"]
    assert error["details"] == {"cli": DEFAULT_CLI_INSTALL, "then": "maity resume"}
    assert "install the CLI" in error["message"]


def test_a_signed_call_goes_through_where_signing_is_required(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine, project_id: str
) -> None:
    _require(migrated, project_id)
    response = make_client().get("/api/v1/me", headers=signed(agent, "GET", "/api/v1/me"))
    assert response.status_code == 200, response.text


def test_the_refusal_has_no_side_effects(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine, project_id: str
) -> None:
    start = clock.now()
    card = factory.card(
        migrated,
        project_id,
        agent.membership_id,
        status="in_progress",
        claim_holder=agent.membership_id,
        claim_since=start,
        lease_until=start + timedelta(minutes=5),
    )
    _require(migrated, project_id)
    with migrated.connect() as conn:
        session_before = conn.execute(
            select(t.agent_session.c.last_seen_at).where(t.agent_session.c.id == agent.session_id)
        ).scalar()
    clock.set_source(lambda: start + timedelta(hours=1))
    assert make_client().get("/api/v1/me", headers=bearer(agent)).status_code == 403
    with migrated.connect() as conn:
        lease = conn.execute(select(t.card.c.lease_until).where(t.card.c.id == card)).scalar()
        seen = conn.execute(
            select(t.membership.c.last_seen_at).where(t.membership.c.id == agent.membership_id)
        ).scalar()
        session_seen = conn.execute(
            select(t.agent_session.c.last_seen_at).where(t.agent_session.c.id == agent.session_id)
        ).scalar()
    credential = _credential(migrated, agent)
    assert lease == start + timedelta(minutes=5)
    assert seen is None
    assert session_seen == session_before
    assert (credential.last_used_at, credential.last_used_via) == (None, None)


def test_possession_is_proven_before_the_refusal(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine, project_id: str
) -> None:
    _require(migrated, project_id)
    wrong = agent.value.rsplit(".", 1)[0] + ".wrongsecretwrongsecretwrongsecret"
    response = make_client().get("/api/v1/me", headers={"Authorization": f"Bearer {wrong}"})
    assert response.headers["Maity-Error"] == "unauthenticated"
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(revoked_at=clock.now(), revoked_reason="rotated")
        )
    response = make_client().get("/api/v1/me", headers=bearer(agent))
    assert response.headers["Maity-Error"] == "credential_revoked"


def test_an_answer_stored_over_bearer_is_not_replayed_after_the_flip(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    created = agent.client.post(
        "/api/v1/projects/maintainer/maity/tasks",
        json={"title": "A card"},
        headers=agent.auth | KEY,
    )
    assert created.status_code == 201, created.text
    owner.patch(
        "/projects/maintainer/maity", {"policy": {"signing": "required"}, "reason": "CLI only"}
    )
    again = agent.client.post(
        "/api/v1/projects/maintainer/maity/tasks",
        json={"title": "A card"},
        headers=agent.auth | KEY,
    )
    assert again.status_code == 403
    assert again.headers["Maity-Error"] == "signature_required"
    assert "Idempotency-Replayed" not in again.headers


def test_human_sessions_are_not_affected(owner: flow.Human, migrated: Engine) -> None:
    flow.project(owner)
    patched = owner.patch(
        "/projects/maintainer/maity", {"policy": {"signing": "required"}, "reason": "x"}
    )
    assert patched.status_code == 200, patched.text
    assert owner.get("/projects/maintainer/maity/tasks").status_code == 200


# --- last_used_via ------------------------------------------------------------------------


def test_the_last_use_records_its_path(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine
) -> None:
    client = make_client()
    assert client.get("/api/v1/me", headers=bearer(agent)).status_code == 200
    assert _credential(migrated, agent).last_used_via == "bearer"
    assert client.get("/api/v1/me", headers=signed(agent, "GET", "/api/v1/me")).status_code == 200
    assert _credential(migrated, agent).last_used_via == "signed"


def test_the_credentials_list_shows_the_last_path(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    [listed] = owner.get(f"/projects/maintainer/maity/members/{agent.id}/credentials").json()[
        "items"
    ]
    assert listed["last_used_via"] is None  # the exchange is not a use
    assert agent.get("/me").status_code == 200
    [listed] = owner.get(f"/projects/maintainer/maity/members/{agent.id}/credentials").json()[
        "items"
    ]
    assert listed["last_used_via"] == "bearer"


# --- the policy field ---------------------------------------------------------------------


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def test_signing_is_a_policy_field(owner: flow.Human) -> None:
    flow.project(owner)
    assert owner.get("/projects/maintainer/maity").json()["policy"]["signing"] == "optional"
    patched = owner.patch(
        "/projects/maintainer/maity", {"policy": {"signing": "required"}, "reason": "x"}
    )
    assert patched.json()["policy"]["signing"] == "required"
    unknown = owner.patch(
        "/projects/maintainer/maity", {"policy": {"signing": "always"}, "reason": "x"}
    )
    assert unknown.json()["error"]["details"]["fields"] == {"policy.signing": "unknown"}


def test_a_preset_change_keeps_signing(owner: flow.Human) -> None:
    flow.project(owner)
    owner.patch("/projects/maintainer/maity", {"policy": {"signing": "required"}, "reason": "x"})
    solo = owner.patch("/projects/maintainer/maity", {"policy": {"preset": "solo"}, "reason": "x"})
    assert solo.json()["policy"]["signing"] == "required"
    assert solo.json()["policy"]["done_authority"] == "holder"  # the rest was refilled
    both = owner.patch(
        "/projects/maintainer/maity",
        {"policy": {"preset": "hierarchical", "signing": "optional"}, "reason": "x"},
    )
    assert both.json()["policy"]["signing"] == "optional"


def test_a_project_can_start_with_signing_required(owner: flow.Human) -> None:
    created = flow.project(owner, policy={"preset": "solo", "signing": "required"})
    assert created["policy"]["signing"] == "required"


def test_an_agent_cannot_switch_signing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner)
    agent = flow.agent(make_client, owner, role="admin")
    response = agent.patch(
        "/projects/maintainer/maity", {"policy": {"signing": "optional"}, "reason": "x"}
    )
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "forbidden"


# --- the join page and the exchange -------------------------------------------------------


def test_the_exchange_says_whether_signing_is_required(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner)
    optional = flow.exchange(make_client(), flow.join(owner, "maity"))
    assert optional.headers["Maity-Signing"] == "optional"
    owner.patch("/projects/maintainer/maity", {"policy": {"signing": "required"}, "reason": "x"})
    required = flow.exchange(make_client(), flow.join(owner, "maity"))
    assert required.status_code == 201
    assert required.headers["Maity-Signing"] == "required"


def test_the_join_page_puts_the_cli_first_when_signing_is_required(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner)
    created = flow.join(owner, "maity")
    token = created["join_url"].rsplit("/", 1)[1]
    page = make_client().get(f"/join/{token}").text
    assert "This project requires the CLI" not in page
    assert "It is optional:" in page
    owner.patch("/projects/maintainer/maity", {"policy": {"signing": "required"}, "reason": "x"})
    page = make_client().get(f"/join/{token}").text
    required = page.index("## This project requires the CLI")
    assert required < page.index("## 1. What this is")
    assert f"maity join https://hub.example/join/{token} --code <code>" in page[required:]
    assert "{{" not in page
    assert "This project requires it: every call after the exchange must be signed." in page
