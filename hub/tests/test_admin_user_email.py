"""docs/api.md §16.1: the instance admin's list of users carries each human's sign-in address
(§18.4, verified or `disabled`), finds it by `q`, and reads it in one query for any page."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import count_statements
from tests.test_runners import call, paired


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _settings(engine: Engine, human_id: str, **address: Any) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(t.notification_settings).values(
                human_id=human_id, preferences={}, epoch=0, hard_failures=0,
                updated_at=clock.now(), **address,
            )
        )  # fmt: skip


def _emails(owner: flow.Human, **params: str) -> dict[str, Any]:
    response = owner.get("/admin/users", params=params)
    assert response.status_code == 200, response.text
    return {u["handle"]: u["email"] for u in response.json()["items"]}


def test_the_admin_sees_the_sign_in_address_and_nothing_else(
    owner: flow.Human, migrated: Engine
) -> None:
    verified = factory.human(migrated, "verified")
    _settings(
        migrated, verified, address="Ver.Ified@Example.org",
        address_normalized="ver.ified@example.org", address_status="verified",
        verified_at=clock.now(),
    )  # fmt: skip
    bounced = factory.human(migrated, "bounced")
    _settings(
        migrated, bounced, address="bounced@example.org",
        address_normalized="bounced@example.org", address_status="disabled",
        verified_at=clock.now(), disabled_at=clock.now(),
    )  # fmt: skip
    # A change that waits for its link is not the sign-in address; nor is a first address.
    changing = factory.human(migrated, "changing")
    _settings(
        migrated, changing, address=None, address_status="pending",
        pending_address="new@example.org",
    )  # fmt: skip
    # A verified address with a change waiting: the verified one is still the sign-in address.
    moving = factory.human(migrated, "moving")
    _settings(
        migrated, moving, address="old@example.org", address_normalized="old@example.org",
        address_status="verified", verified_at=clock.now(), pending_address="next@example.org",
    )  # fmt: skip
    factory.human(migrated, "nothing")
    assert _emails(owner) == {
        "bounced": "bounced@example.org",
        "changing": None,
        "maintainer": None,
        "moving": "old@example.org",
        "nothing": None,
        "verified": "Ver.Ified@Example.org",
    }
    assert _emails(owner, q="next@") == {}


def test_q_finds_a_user_by_part_of_the_address(owner: flow.Human, migrated: Engine) -> None:
    someone = factory.human(migrated, "someone")
    _settings(
        migrated, someone, address="Jo.Doe@Example.org", address_normalized="jo.doe@example.org",
        address_status="verified", verified_at=clock.now(),
    )  # fmt: skip
    pending = factory.human(migrated, "pending")
    _settings(migrated, pending, address_status="pending", pending_address="jo.doe@other.org")
    assert _emails(owner, q="DOE@EXAMPLE") == {"someone": "Jo.Doe@Example.org"}
    assert _emails(owner, q="other.org") == {}  # a pending change is not searched either
    assert _emails(owner, q="maint") == {"maintainer": None}


def test_the_address_is_in_no_other_read(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    address = "maintainer-only@example.org"
    _settings(
        migrated, owner.id, address=address, address_normalized=address,
        address_status="verified", verified_at=clock.now(),
    )  # fmt: skip
    assert _emails(owner)["maintainer"] == address
    # Another human of the same project: the person view and the member list answer them.
    other = flow.human(make_client, migrated, "someone")
    with migrated.begin() as conn:
        project_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar_one()
    factory.membership(migrated, project_id, "coder", human_id=other.id)
    refused = other.get("/admin/users", params={"q": "maintainer-only"})
    assert refused.status_code == 403 and address not in refused.text
    agent = flow.agent(make_client, owner, agent={"handle": "agent-a", "display_name": "agent-a"})
    assert agent.get("/admin/users").status_code == 403
    # A runner, even the instance admin's own, is confined to its routes (§15.1).
    runner = paired(make_client, owner)
    by_runner = call(make_client(), runner, "GET", "/api/v1/admin/users")
    assert by_runner.status_code == 403 and address not in by_runner.text
    reads: list[tuple[flow.Human | flow.Agent, str, int]] = [
        (agent, "/projects/maintainer/maity/members", 200),
        (owner, "/projects/maintainer/maity/members", 200),
        (other, "/projects/maintainer/maity/members", 200),
        (agent, "/me", 200),
        (other, "/me", 200),
        (other, "/people/maintainer", 200),
        (agent, "/people/maintainer", 403),  # an agent reads no person's page
    ]
    for reader, path, status in reads:
        response = reader.get(path)
        assert response.status_code == status, (path, response.text)
        assert address not in response.text, path
    assert other.get("/people/maintainer").json()["handle"] == "maintainer"


def test_the_list_costs_the_same_for_3_users_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    def add(first: int, last: int) -> None:
        for n in range(first, last):
            human_id = factory.human(migrated, f"user-{n:02d}")
            if n % 2:
                address = f"user-{n:02d}@example.org"
                _settings(
                    migrated, human_id, address=address, address_normalized=address,
                    address_status="verified", verified_at=clock.now(),
                )  # fmt: skip

    def cost(**params: str) -> int:
        return count_statements(migrated, lambda: _emails(owner, **params))

    add(0, 2)
    small = (cost(), cost(q="example"))
    add(2, 29)
    assert len(_emails(owner)) == 30
    assert (cost(), cost(q="example")) == small
