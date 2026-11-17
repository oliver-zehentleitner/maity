"""docs/api.md §6.31 and §16.5.1: the instance admin's limits for one project or one account,
the ceilings they set, and the quota details of a refusal."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
ADMIN_PROJECT = "/admin/projects/maintainer/maity/limits"


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin, owner of `maintainer/maity`."""
    who = flow.human(make_client, migrated)
    flow.project(who, "maity")
    return who


def error(response: Any) -> tuple[int, str, dict[str, Any]]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["details"]


def policy(who: flow.Human, **change: Any) -> Any:
    return who.patch(PROJECT, {"policy": change, "reason": "test"})


def test_without_an_override_every_ceiling_is_its_default(admin: flow.Human) -> None:
    view = admin.get(ADMIN_PROJECT).json()
    empty = {"override": None, "updated_by": None, "updated_at": None}
    assert view["max_placements"] == {**empty, "value": 1000, "source": "default"}
    assert view["member_agents_max"] == {**empty, "value": 20, "source": "default"}
    assert view["max_open_claims"] == {**empty, "value": 1000, "source": "default"}
    assert view["max_instances"] == {**empty, "value": 16, "source": "default"}
    storage = view["max_attachment_storage_per_project"]
    assert (storage["override"], storage["value"], storage["source"]) == (
        None,
        1024**3,
        "default",
    )
    account = admin.get(f"/admin/users/{admin.id}/limits").json()
    assert account["member_agents_max"]["value"] == 20
    assert account["max_agents_per_human"] == {**empty, "value": 100, "source": "default"}


def test_a_project_override_sets_the_ceiling_and_unlimited_is_the_bound(
    admin: flow.Human,
) -> None:
    set_ = admin.patch(ADMIN_PROJECT, {"member_agents_max": 50})
    assert set_.status_code == 200, set_.text
    row = set_.json()["member_agents_max"]
    assert (row["override"], row["value"], row["source"]) == (50, 50, "project_override")
    assert row["updated_by"] == {"kind": "human", "id": admin.id, "handle": "maintainer"}
    assert policy(admin, member_agents_max=50).status_code == 200
    assert error(policy(admin, member_agents_max=51)) == (
        400,
        "invalid",
        {"fields": {"policy.member_agents_max": "above_ceiling"}, "ceiling": 50},
    )
    lifted = admin.patch(ADMIN_PROJECT, {"member_agents_max": "unlimited"}).json()
    assert (lifted["member_agents_max"]["override"], lifted["member_agents_max"]["value"]) == (
        "unlimited",
        1000,
    )
    assert policy(admin, member_agents_max=1000).status_code == 200
    gone = admin.patch(ADMIN_PROJECT, {"member_agents_max": None}).json()
    assert (gone["member_agents_max"]["override"], gone["member_agents_max"]["value"]) == (
        None,
        20,
    )


def test_a_lowered_ceiling_holds_the_value_and_names_the_operator(admin: flow.Human) -> None:
    assert admin.patch(ADMIN_PROJECT, {"max_placements": 0}).status_code == 200
    # The stored value stays 8; the ceiling of 0 is the value in effect.
    assert admin.get(PROJECT).json()["policy"]["max_placements"] == 8


def test_an_account_override_reaches_the_projects_the_human_owns(admin: flow.Human) -> None:
    account = f"/admin/users/{admin.id}/limits"
    assert admin.patch(account, {"member_agents_max": 30}).status_code == 200
    assert policy(admin, member_agents_max=30).status_code == 200
    # The project's own override comes first.
    assert admin.patch(ADMIN_PROJECT, {"member_agents_max": 25}).status_code == 200
    view = admin.get(ADMIN_PROJECT).json()["member_agents_max"]
    assert (view["value"], view["source"]) == (25, "project_override")
    assert admin.patch(ADMIN_PROJECT, {"member_agents_max": None}).status_code == 200
    view = admin.get(ADMIN_PROJECT).json()["member_agents_max"]
    assert (view["value"], view["source"]) == (30, "account_override")


def test_an_account_override_comes_before_the_instance_value(admin: flow.Human) -> None:
    assert admin.patch("/admin/settings/limits", {"max_agents_per_human": 1}).status_code == 200
    first = admin.post("/agents", {"handle": "one", "display_name": "One"})
    assert first.status_code == 201, first.text
    refused = admin.post("/agents", {"handle": "two", "display_name": "Two"})
    assert error(refused) == (
        409,
        "agent_limit",
        {"limit": 1, "count": 1, "source": "instance"},
    )
    account = f"/admin/users/{admin.id}/limits"
    view = admin.patch(account, {"max_agents_per_human": 2}).json()["max_agents_per_human"]
    assert (view["value"], view["source"]) == (2, "account_override")
    assert admin.post("/agents", {"handle": "two", "display_name": "Two"}).status_code == 201
    refused = admin.post("/agents", {"handle": "three", "display_name": "Three"})
    assert error(refused) == (
        409,
        "agent_limit",
        {"limit": 2, "count": 2, "source": "account_override"},
    )


def test_the_project_storage_override_comes_before_the_environment(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(
        lambda **kw: make_client(max_attachment_storage_per_project=2 * 1024**2, **kw), migrated
    )
    flow.project(who, "maity")
    storage = who.get(ADMIN_PROJECT).json()["max_attachment_storage_per_project"]
    assert (storage["value"], storage["source"]) == (2 * 1024**2, "env")
    set_ = who.patch(ADMIN_PROJECT, {"max_attachment_storage_per_project": 4 * 1024**2})
    storage = set_.json()["max_attachment_storage_per_project"]
    assert (storage["value"], storage["source"]) == (4 * 1024**2, "project_override")
    assert who.get(PROJECT).json()["attachments"]["quota"] == 4 * 1024**2


def test_a_value_out_of_range_or_unknown_changes_nothing(admin: flow.Human) -> None:
    refused = admin.patch(
        ADMIN_PROJECT,
        {
            "max_placements": 1001,
            "max_open_claims": 0,
            "max_agents_per_human": 5,
            "member_agents_max": 30,
        },
    )
    assert error(refused) == (
        400,
        "invalid",
        {
            "fields": {
                "max_placements": "out_of_range",
                "max_open_claims": "out_of_range",
                "max_agents_per_human": "extra_forbidden",
            }
        },
    )
    assert admin.get(ADMIN_PROJECT).json()["member_agents_max"]["override"] is None
    account = f"/admin/users/{admin.id}/limits"
    refused = admin.patch(account, {"max_attachment_storage_per_project": 1024**3})
    assert error(refused)[2] == {
        "fields": {"max_attachment_storage_per_project": "extra_forbidden"}
    }


def test_only_the_instance_admin_reads_or_sets_them(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, handle="someone")
    for path in (ADMIN_PROJECT, f"/admin/users/{other.id}/limits"):
        assert error(other.get(path))[:2] == (403, "forbidden")
        assert error(other.patch(path, {"max_placements": 5}))[:2] == (403, "forbidden")
    assert admin.get("/admin/projects/maintainer/nothing/limits").status_code == 404
    assert admin.get("/admin/users/hum-nobody/limits").status_code == 404
