"""docs/api.md §6.5: a human's calls renew the leases of the claims it holds, and only those
cost anything: a human of many projects who holds no claim pays one statement for it."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import clock
from maity_hub.auth import caller as auth_caller
from maity_hub.net import Origin
from tests import flow
from tests.conftest import ClientFactory
from tests.factory import at
from tests.test_conversation_list import count_statements

LEASE = 7200  # the default lease of a project (§6.5)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def claim(owner: flow.Human, slug: str, card: dict[str, Any]) -> None:
    done = owner.post(f"/projects/maintainer/{slug}/tasks/{card['id']}/claim", {})
    assert done.status_code == 200, done.text


def lease_of(owner: flow.Human, slug: str, card_id: str) -> Any:
    got = owner.get(f"/projects/maintainer/{slug}/tasks/{card_id}")
    return at(got.json()["claim"]["lease_until"])


def test_the_calls_of_a_human_renew_each_claim_it_holds_in_every_project(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    for slug in ("alpha", "beta", "gamma"):
        flow.project(owner, slug)
    held = {}
    for slug in ("alpha", "beta"):  # claims in two of three projects
        card = owner.post(f"/projects/maintainer/{slug}/tasks", {"title": f"a card in {slug}"})
        held[slug] = card.json()["id"]
        claim(owner, slug, card.json())
    agent = flow.agent(make_client, owner, slug="gamma")
    theirs = task_of(owner, "gamma", "the agent's")
    agent.post(f"/projects/maintainer/gamma/tasks/{theirs['id']}/claim", {})
    before = {k: lease_of(owner, k, v) for k, v in held.items()}
    agents_before = lease_of(owner, "gamma", theirs["id"])
    start = clock.now()
    clock.set_source(lambda: start + timedelta(seconds=3600))
    assert owner.get("/me").status_code == 200
    after = {k: lease_of(owner, k, v) for k, v in held.items()}
    for slug in held:
        assert after[slug] > before[slug], slug
        assert after[slug] == (start + timedelta(seconds=3600 + LEASE)).replace(microsecond=0)
    # the human's call renews its own leases only, not the agent's in a third project
    assert lease_of(owner, "gamma", theirs["id"]) == agents_before


def test_a_human_without_a_claim_pays_one_statement_however_many_projects(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "alpha")

    def sign_in() -> int:
        facts = auth_caller.RequestFacts(
            method="GET",
            raw_path=b"/api/v1/me",
            raw_query=b"",
            headers={},
            cookies={auth_caller.SESSION_COOKIE: owner.client.cookies[auth_caller.SESSION_COOKIE]},
            body=b"",
            origin=Origin("127.0.0.1", "http"),
            allow_plain_http=True,
        )

        def call() -> None:
            with migrated.begin() as conn:
                auth_caller.authenticate(conn, facts)

        return count_statements(migrated, call)

    few = sign_in()
    for n in range(6):
        project = flow.project(owner, f"more{n}")
        assert project["slug"]
    many = sign_in()
    assert many == few, (few, many)
    # and a claim held in one of them costs only its own renewal
    card = owner.post("/projects/maintainer/more0/tasks", {"title": "held"}).json()
    claim(owner, "more0", card)
    assert sign_in() > many


def task_of(owner: flow.Human, slug: str, title: str) -> dict[str, Any]:
    made = owner.post(f"/projects/maintainer/{slug}/tasks", {"title": title})
    assert made.status_code == 201, made.text
    body: dict[str, Any] = made.json()
    return body
