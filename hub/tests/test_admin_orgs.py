"""docs/api.md §16.10: `GET /admin/orgs`, the organisations of the instance for the admin."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_orgs import add_member, delete_org, make_org

PATH = "/admin/orgs"


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin: the earliest account."""
    return flow.human(make_client, migrated)


def handles(who: flow.Human, **query: Any) -> list[str]:
    got = who.get(PATH, params=query)
    assert got.status_code == 200, got.text
    return [item["handle"] for item in got.json()["items"]]


def test_the_list_is_by_handle_with_owners_projects_and_no_deleted_ones(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    ben = flow.human(make_client, migrated, "ben")
    zed = make_org(ben, "zed-team", "Zed Team")
    make_org(anna, "alpha-team", "Alpha Team")
    add_member(migrated, zed["id"], anna.id, "owner")
    add_member(migrated, zed["id"], admin.id, "admin")
    ben.post("/projects", {"slug": "shop", "name": "Shop", "owner": "zed-team"})
    ben.post("/projects", {"slug": "blog", "name": "Blog", "owner": "zed-team"})
    gone = make_org(anna, "gone-team", "Gone Team")
    assert delete_org(anna, "gone-team", "gone-team").status_code == 204
    assert gone["id"]
    got = admin.get(PATH)
    assert got.status_code == 200, got.text
    items = got.json()["items"]
    assert [i["handle"] for i in items] == ["alpha-team", "zed-team"]
    assert got.json()["next_cursor"] is None
    alpha, zed_item = items
    assert alpha["owners"] == ["anna"] and alpha["projects"] == 0
    # owners only, by current handle; admins and members are not listed
    assert zed_item["owners"] == ["anna", "ben"] and zed_item["projects"] == 2
    assert (zed_item["display_name"], zed_item["suspended"]) == ("Zed Team", False)
    assert zed_item["id"] == zed["id"] and zed_item["created_at"].endswith("Z")
    assert set(zed_item) == {
        "id",
        "handle",
        "display_name",
        "created_at",
        "owners",
        "projects",
        "suspended",
    }


def test_q_matches_the_handle_and_the_display_name_in_any_case(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    make_org(anna, "alpha-team", "Alpha Team")
    make_org(anna, "beta-crew", "The Rocket Crew")
    make_org(anna, "100pct", "Fully 100% Done")
    assert handles(admin, q="ALPHA") == ["alpha-team"]
    assert handles(admin, q="rocket") == ["beta-crew"]
    assert handles(admin, q="-t") == ["alpha-team"]
    assert handles(admin, q="100%") == ["100pct"]  # a `%` is a character, not a wildcard
    make_org(anna, "axb-crew", "Axb Crew")
    make_org(anna, "a-b-crew", "A_b Crew")
    assert handles(admin, q="a_b") == ["a-b-crew"]  # nor is a `_` one: it does not match `axb`
    assert handles(admin, q="nothing") == []
    for bad in ("", "x" * 65):
        got = admin.get(PATH, params={"q": bad})
        assert got.status_code == 400, got.text
        assert got.json()["error"]["details"]["fields"] == {"q": "invalid"}


def test_pages_follow_the_handle_and_a_cursor_belongs_to_its_filter(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    for handle in ("org-c", "org-a", "org-e", "org-b", "org-d"):
        make_org(anna, handle, handle)
    first = admin.get(PATH, params={"limit": 2}).json()
    assert [i["handle"] for i in first["items"]] == ["org-a", "org-b"]
    second = admin.get(PATH, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["handle"] for i in second["items"]] == ["org-c", "org-d"]
    third = admin.get(PATH, params={"limit": 2, "cursor": second["next_cursor"]}).json()
    assert [i["handle"] for i in third["items"]] == ["org-e"]
    assert third["next_cursor"] is None
    other = admin.get(PATH, params={"limit": 2, "q": "org", "cursor": first["next_cursor"]})
    assert other.status_code == 400, other.text
    assert admin.get(PATH, params={"limit": 0}).status_code == 400


def test_only_the_instance_admin_reads_it(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    make_org(anna, "alpha-team", "Alpha Team")
    assert anna.get(PATH).status_code == 403
    flow.project(admin, "maity")
    bot = flow.agent(make_client, admin, role="admin")
    assert bot.get(PATH).status_code in (403, 404)
    assert bot.get(PATH).status_code == bot.get("/admin/settings/sign-in").status_code
