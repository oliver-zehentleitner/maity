"""docs/api.md §16.5: the caps on what one account may hold, and what they gate."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_orgs import make_org

PATH = "/admin/settings/limits"


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin: the earliest account."""
    return flow.human(make_client, migrated)


def agent(who: flow.Human, handle: str) -> Any:
    return who.post("/agents", {"handle": handle, "display_name": handle.title()})


def test_the_defaults_and_where_they_come_from(admin: flow.Human) -> None:
    got = admin.get(PATH)
    assert got.status_code == 200, got.text
    assert got.json() == {
        "max_agents_per_human": {"value": 100, "source": "default"},
        "humans_at_limit": 0,
        "max_orgs_per_human": {"value": 5, "source": "default"},
        "humans_at_org_limit": 0,
    }


def test_a_patch_sets_unlimited_and_null_restores_the_default(admin: flow.Human) -> None:
    got = admin.patch(PATH, {"max_agents_per_human": 3, "max_orgs_per_human": "unlimited"})
    assert got.status_code == 200, got.text
    assert got.json()["max_agents_per_human"] == {"value": 3, "source": "admin"}
    assert got.json()["max_orgs_per_human"] == {"value": "unlimited", "source": "admin"}
    back = admin.patch(PATH, {"max_agents_per_human": None, "max_orgs_per_human": None})
    assert back.json()["max_agents_per_human"] == {"value": 100, "source": "default"}
    assert back.json()["max_orgs_per_human"] == {"value": 5, "source": "default"}


def test_a_body_is_all_or_nothing_and_names_what_it_refuses(admin: flow.Human) -> None:
    refused = admin.patch(
        PATH,
        {
            "max_agents_per_human": 7,
            "max_orgs_per_human": 0,
            "humans_at_limit": 1,
            "humans_at_org_limit": 1,
            "max_something": 1,
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "max_orgs_per_human": "invalid",
        "humans_at_limit": "read_only",
        "humans_at_org_limit": "read_only",
        "max_something": "extra_forbidden",
    }
    assert admin.get(PATH).json()["max_agents_per_human"]["source"] == "default"
    for bad in (True, 10001, "many", 1.5, [1]):
        assert admin.patch(PATH, {"max_agents_per_human": bad}).status_code == 400


def test_only_the_instance_admin_reads_or_sets_them(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human
) -> None:
    other = flow.human(make_client, migrated, "other")
    assert other.get(PATH).status_code == 403
    assert other.patch(PATH, {"max_orgs_per_human": 9}).status_code == 403
    flow.project(admin, "maity")
    bot = flow.agent(make_client, admin, role="admin")
    # an agent is answered as it is for every other human-only admin route
    assert bot.get(PATH).status_code == bot.get("/admin/settings/sign-in").status_code
    assert bot.get(PATH).status_code in (403, 404)


def test_the_environment_wins_and_is_not_overwritten(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(lambda **kw: make_client(max_orgs_per_human=2, **kw), migrated)
    got = who.get(PATH).json()
    assert got["max_orgs_per_human"] == {"value": 2, "source": "env"}
    assert got["max_agents_per_human"]["source"] == "default"
    refused = who.patch(PATH, {"max_orgs_per_human": 9})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "max_orgs_per_human": "set_by_environment"
    }


def test_the_organisation_cap_is_the_admins_value_and_counts_humans_at_it(
    admin: flow.Human,
) -> None:
    assert admin.patch(PATH, {"max_orgs_per_human": 1}).status_code == 200
    make_org(admin, "first-org")
    refused = admin.post("/orgs", {"handle": "second-org", "display_name": "Second"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "org_limit"
    assert refused.json()["error"]["details"] == {"limit": 1, "count": 1}
    assert admin.get(PATH).json()["humans_at_org_limit"] == 1
    # lowering deletes nothing; unlimited lifts the cap and counts no one
    assert admin.patch(PATH, {"max_orgs_per_human": "unlimited"}).json()["humans_at_org_limit"] == 0
    assert (
        admin.post("/orgs", {"handle": "second-org", "display_name": "Second"}).status_code == 201
    )


def test_the_agent_cap_gates_the_creation_of_profiles(admin: flow.Human) -> None:
    assert admin.patch(PATH, {"max_agents_per_human": 2}).status_code == 200
    assert agent(admin, "first").status_code == 201
    assert agent(admin, "second").status_code == 201
    refused = agent(admin, "third")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "agent_limit"
    assert refused.json()["error"]["details"] == {"limit": 2, "count": 2}
    assert admin.get(PATH).json()["humans_at_limit"] == 1
    # a deleted profile does not count
    [first] = [a for a in admin.get("/agents").json()["items"] if a["handle"] == "first"]
    assert admin.delete(f"/agents/{first['id']}").status_code in (200, 204)
    assert agent(admin, "third").status_code == 201


def test_the_agent_cap_is_atomic_per_owner(make_client: ClientFactory, migrated: Engine) -> None:
    who = flow.human(lambda **kw: make_client(max_agents_per_human=1, **kw), migrated)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda handle: agent(who, handle), ["one", "two"]))
    assert sorted(r.status_code for r in results) == [201, 409]
    assert next(r for r in results if r.status_code == 409).json()["error"]["code"] == "agent_limit"


def test_a_join_that_creates_a_profile_is_gated_and_one_for_an_existing_profile_is_not(
    admin: flow.Human,
) -> None:
    flow.project(admin, "maity")
    assert admin.patch(PATH, {"max_agents_per_human": 1}).status_code == 200
    existing = agent(admin, "first").json()
    new = admin.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"handle": "second", "display_name": "Second"}},
    )
    assert new.status_code == 409, new.text
    assert new.json()["error"]["code"] == "agent_limit"
    old = admin.post("/projects/maintainer/maity/joins", {"agent": {"id": existing["id"]}})
    assert old.status_code in (200, 201), old.text
