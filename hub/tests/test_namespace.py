"""docs/api.md §6.25: projects in their owner's namespace, `/projects/{owner}/{slug}/…`, the
answers for the paths from before it, and the words a slug or a handle may not be."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, namespace
from maity_hub import paths as hub_paths
from maity_hub import tables as t
from maity_hub.registration_accounts import check_names
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def test_a_project_lives_in_its_creators_namespace(owner: flow.Human) -> None:
    body = flow.project(owner, "maity")
    assert body["full_name"] == "maintainer/maity"
    assert body["owner"] == {"id": owner.id, "handle": "maintainer"}
    assert body["id"].startswith("prj-") and "legacy_slug" not in body
    assert owner.get("/projects/maintainer/maity").json()["id"] == body["id"]
    listed = owner.get("/projects").json()["items"]
    assert [p["full_name"] for p in listed] == ["maintainer/maity"]


def test_two_owners_each_have_their_own_slug(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    mine = flow.project(owner, "shop")
    hers = flow.project(anna, "shop")
    assert mine["id"] != hers["id"]
    assert anna.get("/projects/anna/shop").json()["id"] == hers["id"]
    # Nobody else's namespace is reachable through a project of the same slug.
    assert anna.get("/projects/maintainer/shop").status_code == 404
    assert owner.get("/projects/anna/shop").status_code == 404


def test_a_slug_is_taken_once_per_owner(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    again = owner.post("/projects", {"slug": "maity", "name": "Again"})
    assert again.status_code == 400
    assert again.json()["error"]["details"]["fields"] == {"slug": "taken"}


def test_an_alias_keeps_its_slug_taken_and_resolves(owner: flow.Human, migrated: Engine) -> None:
    project = flow.project(owner, "maity")
    with migrated.begin() as conn:
        conn.execute(
            insert(t.project_alias).values(
                project_id=project["id"], owner_id=owner.id, slug="old", created_at=clock.now()
            )
        )
    assert owner.get("/projects/maintainer/old").json()["full_name"] == "maintainer/maity"
    taken = owner.post("/projects", {"slug": "old", "name": "Old"})
    assert taken.json()["error"]["details"]["fields"] == {"slug": "taken"}


@pytest.mark.parametrize("slug", ["tasks", "members", "forge", "logo", "keep-the-why", "transfer"])
def test_a_slug_is_never_a_route_word(owner: flow.Human, slug: str) -> None:
    refused = owner.post("/projects", {"slug": slug, "name": "X"})
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"slug": "reserved"}


def test_the_route_words_come_from_the_routes() -> None:
    paths = [
        "/api/v1/projects/{owner}/{slug}/tasks/{task_id}",
        "/api/v1/projects/{owner}/{slug}",
        "/api/v1/projects/{owner}/{slug}/{kind}",
        "/api/v1/me/preferences/projects/{owner}/{slug}",
    ]
    assert namespace.route_words(paths) == frozenset({"tasks"})


@pytest.mark.parametrize("slug", ["maity", "never-was"])
def test_an_old_path_is_not_found_and_says_nothing_about_the_project(
    owner: flow.Human, slug: str
) -> None:
    """The one-segment form from before the namespace is gone, not answered with an
    upgrade hint (§16.11, alpha): `not_found`, whether the slug ever existed or not."""
    flow.project(owner, "maity")
    for agent in ("maity-cli/0.1.0a1", "curl/8"):
        for path in (f"/api/v1/projects/{slug}", f"/api/v1/projects/{slug}/tasks"):
            old = owner.client.get(path, headers={"User-Agent": agent})
            assert old.status_code == 404, (agent, path)
            assert old.json()["error"]["code"] == "not_found"


def test_an_agent_reaches_its_own_project_only(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    flow.project(owner, "maity")
    flow.project(owner, "other")
    agent = flow.agent(make_client, owner, "maity")
    assert agent.get("/projects/maintainer/maity").status_code == 200
    assert agent.get("/projects/maintainer/other").status_code == 404


def test_the_resume_names_the_project_by_its_full_name(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner, "maity")
    packet = agent.resume().json()
    assert packet["project"]["full_name"] == "maintainer/maity"
    assert "GET /projects/maintainer/maity/tasks" in packet["operations"]


@pytest.mark.parametrize("handle", sorted(hub_paths.RESERVED_FIRST))
def test_a_reserved_first_segment_is_no_handle(migrated: Engine, handle: str) -> None:
    with migrated.connect() as conn:
        assert check_names(conn, handle, "Someone").get("handle") in ("reserved", "invalid")


def test_factory_projects_default_to_the_maintainers_namespace(migrated: Engine) -> None:
    project_id = factory.project(migrated, "widget")
    with migrated.connect() as conn:
        row = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
        assert namespace.full_name(conn, row) == "maintainer/widget"


def _public_badge(owner: flow.Human) -> None:
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "members"}, "reason": "README"}
    )
    assert response.status_code == 200, response.text


def test_the_badge_lives_under_the_full_name_and_the_one_segment_address_is_gone(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    flow.project(owner, "maity")
    _public_badge(owner)
    public = make_client()
    assert public.get("/badge/maintainer/maity.svg").status_code == 200
    # The address from before the namespace is not kept, not even as a redirect (§16.11).
    assert public.get("/badge/maity.svg", follow_redirects=False).status_code == 404
    assert public.get("/badge/never-was.svg").status_code == 404
