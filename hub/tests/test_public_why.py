"""docs/api.md §16.9 and §11.3: the public Why is a stored row of the reduced export of a public
repository, read with the instance's own token, and it does not outlive a change to private."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import forge, ktw, probe, public_pages, public_project_views
from maity_hub import tables as t
from tests.conftest import ClientFactory
from tests.test_public_project_views import World

READ = "/api/v1/public/pages/maintainer/maity/why"
URL = "https://github.com/maintainer/maity"
BODY = "CANARY entry body"
OWN = frozenset({"maintainer"})  # MAITY_FORGE_INSTANCE_NAMESPACES


def snapshot() -> ktw.Snapshot:
    read = ktw.digest(
        {
            "state-json": "2.0.0",
            "generated": "2026-11-01T00:00:00Z",
            "entries": [
                {
                    "id": "a",
                    "title": "Open question",
                    "status": "open",
                    "body": BODY,
                    "author": BODY,
                }
            ],
        },
        "https://example.org/dash/",
    )
    member = ktw.Member(
        path=".", name="root", state_url="https://example.org/dash/state.json", read=read
    )
    return ktw.Snapshot("2026-11-01T00:00:00Z", [member], False)


@pytest.fixture
def settings(settings: Any) -> Any:
    """The instance token, serving the namespace of the project (§11.4)."""
    return replace(settings, forge_github_token="instance", forge_instance_namespaces=OWN)


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, settings: Any, monkeypatch: Any) -> World:
    # No app here runs the public-pages worker: it renders with the settings its app started
    # with, and a test below changes them through `configure` alone. Its start-up render,
    # late on a loaded runner, would write the page back as the old settings show it. The
    # renders these tests read come from the app's start and from `touch`.
    monkeypatch.setattr(public_pages.Worker, "start", lambda self: None)
    public_pages.configure(replace(settings, public_pages=True))
    world = World(make_client, migrated)
    fresh = ktw.Cache()
    monkeypatch.setattr(public_project_views, "WHY_CACHE", fresh)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(repository_url=URL, repository_public=True))
    fresh.entries[world.project_id] = ktw._Entry(snapshot(), 0.0, URL)
    world.touch()
    return world


def test_it_shows_counts_links_and_titles_and_no_entry_text(world: World) -> None:
    answer = world.anyone.get(READ).json()
    assert answer["kind"] == "why"
    data = answer["data"]
    assert (
        set(data) == {"readable", "observed_at", "summary", "family", "attention"}
        and data["readable"]
    )
    assert data["attention"][0]["title"] == "Open question"
    assert data["family"][0]["dashboard_url"]
    page = world.anyone.get("/maintainer/maity/why").text
    assert "Open question" in page
    assert BODY not in world.anyone.get(READ).text and BODY not in page


def test_a_repository_gone_private_takes_it_off_with_the_look_that_found_it(
    world: World, migrated: Engine
) -> None:
    class Private:
        def for_project(self, _: str) -> Any:
            return self

        def repository_public(self, _: str) -> bool:
            return False

    probe.observe_visibility(migrated, Private(), world.project_id)  # type: ignore[arg-type]
    assert world.anyone.get(READ).json()["data"] == {"readable": False}
    page = world.anyone.get("/maintainer/maity/why").text
    assert "Open question" not in page


def test_a_page_switched_off_takes_the_row_with_it(world: World) -> None:
    assert (
        world.owner.patch("/projects/maintainer/maity", {"public_page": "off"}).status_code == 200
    )
    assert world.anyone.get(READ).status_code == 404


def test_a_render_does_not_touch_the_network(world: World, monkeypatch: Any) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("a render read the network")

    monkeypatch.setattr(ktw, "walk", refuse)
    monkeypatch.setattr(public_project_views.WHY_CACHE, "get", refuse)
    world.touch()
    assert world.anyone.get(READ).json()["data"]["readable"] is True


def test_the_read_before_a_render_uses_the_instance_token_and_no_grant(
    world: World, migrated: Engine, settings: Any, monkeypatch: Any
) -> None:
    seen: list[tuple[Any, Any]] = []

    def get(reader: forge.Forge, *_: Any) -> None:
        seen.append((reader.token, reader.access))

    monkeypatch.setattr(public_project_views.WHY_CACHE, "get", get)
    public_project_views.prepare_why(
        migrated,
        replace(
            settings,
            forge_github_token="instance",
            forge_instance_namespaces=OWN,
        ),
    )
    assert seen == [("instance", None)]


def test_a_repository_not_found_public_is_not_read(
    world: World, migrated: Engine, settings: Any, monkeypatch: Any
) -> None:
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(repository_public=None))
    monkeypatch.setattr(
        public_project_views.WHY_CACHE, "get", lambda *_: pytest.fail("read a private repository")
    )
    public_project_views.prepare_why(migrated, settings)


def test_a_replica_with_no_read_or_an_older_one_keeps_the_stored_view(
    world: World, monkeypatch: Any
) -> None:
    stored = world.anyone.get(READ).json()["data"]
    empty = ktw.Cache()
    monkeypatch.setattr(public_project_views, "WHY_CACHE", empty)
    world.touch()
    assert world.anyone.get(READ).json()["data"] == stored
    older = ktw.Snapshot("2026-01-01T00:00:00Z", [], False)
    empty.entries[world.project_id] = ktw._Entry(older, 0.0, URL)
    world.touch()
    assert world.anyone.get(READ).json()["data"] == stored


def test_a_failed_read_keeps_the_view_and_a_removed_export_empties_it(
    world: World,
) -> None:
    stored = world.anyone.get(READ).json()["data"]
    failed = ktw.Snapshot("2026-12-01T00:00:00Z", [], False, {"reason": "forge_unavailable"})
    cache = public_project_views.WHY_CACHE
    cache.entries[world.project_id] = ktw._Entry(failed, 0.0, URL)
    world.touch()
    assert world.anyone.get(READ).json()["data"] == stored
    cache.entries[world.project_id] = ktw._Entry(None, 0.0, URL)
    world.touch()
    assert world.anyone.get(READ).json()["data"] == {"readable": False}


# --- only the operator's own namespaces (§11.4, §16.9) ---------------------------------------


def test_a_project_outside_the_operators_namespaces_is_not_read_for_why(
    world: World, migrated: Engine, settings: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        public_project_views.WHY_CACHE, "get", lambda *_: pytest.fail("read another's project")
    )
    others = frozenset({"someone-else"})
    public_project_views.prepare_why(
        migrated, replace(settings, forge_github_token="instance", forge_instance_namespaces=others)
    )
    unset = frozenset[str]()
    public_project_views.prepare_why(migrated, replace(settings, forge_instance_namespaces=unset))


def test_a_project_outside_the_operators_namespaces_shows_no_why_not_even_a_stored_one(
    world: World, settings: Any
) -> None:
    assert world.anyone.get(READ).json()["data"]["readable"] is True  # stored
    public_pages.configure(
        replace(
            settings,
            public_pages=True,
            forge_github_token="instance",
            forge_instance_namespaces=frozenset({"someone-else"}),
        )
    )
    world.touch()
    assert world.anyone.get(READ).json()["data"] == {"readable": False}
    assert "Open question" not in world.anyone.get("/maintainer/maity/why").text
