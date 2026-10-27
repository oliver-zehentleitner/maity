"""docs/api.md §6.25: projects in their owner's namespace, `/projects/{owner}/{slug}/…`, the
answers for the paths from before it, and the words a slug or a handle may not be."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, namespace
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
    assert body["id"].startswith("prj-") and body["legacy_slug"] is None
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


@pytest.mark.parametrize("slug", ["tasks", "members", "forge", "logo", "keep-the-why"])
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


@pytest.mark.parametrize(
    ("path", "outdated"),
    [
        ("/api/v1/projects/maity", True),
        ("/api/v1/projects/maity/tasks", True),
        ("/api/v1/projects/never-was/tasks/tsk-1", True),
        ("/api/v1/projects", False),
        ("/api/v1/projects/maintainer/maity", False),
        ("/api/v1/projects/maintainer/maity/tasks", False),
        ("/api/v1/me", False),
    ],
)
def test_an_old_path_is_told_apart_without_a_lookup(path: str, outdated: bool) -> None:
    assert namespace.outdated(path, frozenset({"tasks", "forge"})) is outdated


@pytest.mark.parametrize("slug", ["maity", "never-was"])
def test_an_old_path_answers_the_cli_with_an_upgrade_and_says_nothing_about_the_project(
    owner: flow.Human, slug: str
) -> None:
    flow.project(owner, "maity")
    old = owner.client.get(
        f"/api/v1/projects/{slug}/tasks", headers={"User-Agent": "maity-cli/0.1.0a1"}
    )
    assert old.status_code == 426
    error = old.json()["error"]
    assert error["code"] == "client_outdated"
    assert error["details"]["minimum"] == namespace.CLI_MINIMUM
    assert "install" in error["details"]
    other = owner.client.get(f"/api/v1/projects/{slug}", headers={"User-Agent": "curl/8"})
    assert other.status_code == 410
    assert other.json()["error"] == {
        "code": "project_path_outdated",
        "message": "projects are addressed as /projects/{owner}/{slug} (docs/api.md §6.25)",
        "details": {},
    }


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


@pytest.mark.parametrize("handle", sorted(namespace.DASHBOARD_WORDS))
def test_a_dashboard_route_word_is_no_handle(migrated: Engine, handle: str) -> None:
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


def test_the_badge_lives_under_the_full_name_and_the_old_address_moves_there(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    from sqlalchemy import update

    project = flow.project(owner, "maity")
    _public_badge(owner)
    public = make_client()
    assert public.get("/badge/maintainer/maity.svg").status_code == 200
    # A project from before the namespace keeps its old badge address, as a redirect.
    with migrated.begin() as conn:
        conn.execute(
            update(t.project).where(t.project.c.id == project["id"]).values(legacy_slug="maity")
        )
    moved = public.get("/badge/maity.svg", follow_redirects=False)
    assert moved.status_code == 301
    assert moved.headers["location"] == "/badge/maintainer/maity.svg"
    # An old address no project has answers as any badge not served.
    assert public.get("/badge/never-was.svg").status_code == 404


def test_the_old_badge_of_a_project_not_served_does_not_redirect(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    from sqlalchemy import update

    project = flow.project(owner, "maity")
    with migrated.begin() as conn:
        conn.execute(
            update(t.project).where(t.project.c.id == project["id"]).values(legacy_slug="maity")
        )
    assert make_client().get("/badge/maity.svg", follow_redirects=False).status_code == 404
