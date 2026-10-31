"""docs/api.md §6.27: `GET /people/{handle}`, a person or an organisation as the dashboard shows
them to a signed-in human, and every branch of what the caller may see."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import avatars, clock, moderation, public_pages
from maity_hub import tables as t
from maity_hub.routes import people as people_routes
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_avatars import image, put_human
from tests.test_orgs import add_member, make_org

P = "/people"


def pages(make_client: ClientFactory) -> ClientFactory:
    """A client factory for a hub that serves public pages."""
    return lambda **kw: make_client(public_pages=True, **kw)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(pages(make_client), migrated)
    flow.project(human)
    return human


@pytest.fixture
def stranger(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(pages(make_client), migrated, "stranger")


def _project_id(engine: Engine, slug: str) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(select(t.project.c.id).where(t.project.c.slug == slug)).scalar_one()
        )


def _serve(engine: Engine, kind: str, target_id: str, path: str) -> None:
    """A page in the store, as the hub keeps it while it serves the page (§16.9)."""
    with engine.begin() as conn:
        public_pages.put(
            conn,
            path=path,
            kind=kind,
            target_id=target_id,
            body="<html></html>",
            inputs="x",
            lastmod=clock.now(),
        )


def _set_human(engine: Engine, human_id: str, **values: Any) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.human).where(t.human.c.id == human_id).values(**values))


def _with_picture(human: flow.Human) -> None:
    assert put_human(human, "/me/avatar", image()).status_code == 200


def _reads(engine: Engine, human: flow.Human, owner_id: str) -> bool:
    """Whether the human may read the image of `owner_id` (§6.10)."""
    reader = SimpleNamespace(kind="human", human_id=human.id)
    with engine.connect() as conn:
        return avatars.may_read(conn, reader, owner_id)


def _not_found(response: Any) -> Any:
    assert response.status_code == 404, response.text
    return response.json()


# --- who may ask -----------------------------------------------------------------------------


def test_only_a_signed_in_human_reads_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    refused = agent.get(f"{P}/maintainer")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    assert make_client().get(f"/api/v1{P}/maintainer").status_code == 401


# --- the caller's own handle -------------------------------------------------------------------


def test_the_callers_own_handle_shows_everything_of_its_own(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "second")
    _with_picture(owner)
    owner.patch("/me", {"public_bio": "my own words"})  # not public: still the owner's to see
    got = owner.get(f"{P}/maintainer")
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == "private, no-store"
    body = got.json()
    assert (body["kind"], body["handle"], body["page_served"]) == ("human", "maintainer", False)
    assert body["public_bio"] == "my own words"
    assert body["avatar_url"] is not None
    assert body["projects"] == [
        {"full_name": "maintainer/maity", "name": "Maity", "shared": True},
        {"full_name": "maintainer/second", "name": "Second", "shared": True},
    ]
    assert body["projects_total"] == 2
    assert "members" not in body and "website" not in body and "social" not in body  # none set


# --- one answer for everything the caller may not see ----------------------------------------


def test_every_hidden_case_is_the_same_not_found(
    owner: flow.Human, stranger: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent_handle = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["handle"]
    nobody = _not_found(stranger.get(f"{P}/no-such-name"))
    assert _not_found(stranger.get(f"{P}/{agent_handle}")) == nobody  # an agent's handle
    assert _not_found(stranger.get(f"{P}/maintainer")) == nobody  # shows the caller nothing
    for column, value in (
        ("deleted_at", clock.now()),
        ("suspended_at", clock.now()),
        ("account_status", "pending"),
    ):
        shared = factory.human(migrated, f"gone-{column.replace('_', '-')}")
        factory.membership(migrated, _project_id(migrated, "maity"), "coder", human_id=shared)
        assert owner.get(f"{P}/gone-{column.replace('_', '-')}").status_code == 200
        _set_human(migrated, shared, **{column: value})
        assert _not_found(owner.get(f"{P}/gone-{column.replace('_', '-')}")) == nobody, column


# --- a person -------------------------------------------------------------------------------


def test_a_public_page_shows_a_stranger_the_bio_but_no_picture(
    owner: flow.Human, stranger: flow.Human
) -> None:
    _with_picture(owner)
    owner.patch("/me", {"public_profile": True, "public_bio": "I build agents."})
    body = stranger.get(f"{P}/maintainer").json()
    assert (body["page_served"], body["public_bio"]) == (True, "I build agents.")
    assert body["avatar_url"] is None  # a public page grants no image (§6.10)
    assert (body["projects"], body["projects_total"]) == ([], 0)


def test_a_shared_project_shows_the_person_without_a_bio(
    owner: flow.Human, stranger: flow.Human, migrated: Engine
) -> None:
    _with_picture(owner)
    owner.patch("/me", {"public_bio": "not public"})
    factory.membership(migrated, _project_id(migrated, "maity"), "coder", human_id=stranger.id)
    body = stranger.get(f"{P}/maintainer").json()
    assert body["page_served"] is False and "public_bio" not in body
    assert body["avatar_url"] is not None  # a shared project lets the caller see it
    assert body["projects"] == [{"full_name": "maintainer/maity", "name": "Maity", "shared": True}]


def test_a_served_project_page_lists_the_project_unshared_and_archived_ones_only_shared(
    owner: flow.Human, stranger: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "open-one")
    flow.project(owner, "old-one")
    _serve(migrated, "project", _project_id(migrated, "open-one"), "/maintainer/open-one")
    _serve(migrated, "project", _project_id(migrated, "old-one"), "/maintainer/old-one")
    with migrated.begin() as conn:
        conn.execute(
            update(t.project).where(t.project.c.slug == "old-one").values(state="archived")
        )
    body = stranger.get(f"{P}/maintainer").json()
    assert body["projects"] == [
        {"full_name": "maintainer/open-one", "name": "Open-One", "shared": False}
    ]
    assert body["projects_total"] == 1
    factory.membership(migrated, _project_id(migrated, "old-one"), "coder", human_id=stranger.id)
    names = [p["full_name"] for p in stranger.get(f"{P}/maintainer").json()["projects"]]
    assert names == ["maintainer/old-one", "maintainer/open-one"]  # archived, shared: listed


def test_without_public_pages_nothing_counts_as_served(
    owner: flow.Human, stranger: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner.patch("/me", {"public_profile": True, "public_bio": "I build agents."})
    _serve(migrated, "project", _project_id(migrated, "maity"), "/maintainer/maity")
    off = flow.human(make_client, migrated, "reader")  # a hub with public pages off
    _not_found(off.get(f"{P}/maintainer"))


def test_a_hold_takes_the_page_and_the_bio_away(
    owner: flow.Human, stranger: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner.patch("/me", {"public_profile": True, "public_bio": "I build agents."})
    factory.membership(migrated, _project_id(migrated, "maity"), "coder", human_id=stranger.id)
    held = SimpleNamespace(action="hide", at=clock.now(), report_id="rep-1")
    real = moderation.hold
    monkeypatch.setattr(
        moderation,
        "hold",
        lambda conn, kind, target: held if target == owner.id else real(conn, kind, target),
    )
    body = stranger.get(f"{P}/maintainer").json()
    assert body["page_served"] is False and "public_bio" not in body
    assert body["projects_total"] == 1  # still a colleague


def test_the_list_is_cut_at_its_limit_and_says_how_many(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    for slug in ("b-one", "c-one"):
        flow.project(owner, slug)
    monkeypatch.setattr(people_routes, "PROJECTS_SHOWN", 2)
    body = owner.get(f"{P}/maintainer").json()
    assert [p["full_name"] for p in body["projects"]] == ["maintainer/b-one", "maintainer/c-one"]
    assert body["projects_total"] == 3


def _links(who: flow.Human, visible: str) -> None:
    done = who.patch(
        "/me",
        {"website": "https://example.org", "social": {"github": "oz"}, "links_visible": visible},
    )
    assert done.status_code == 200, done.text


def test_links_show_exactly_where_links_visible_admits_the_caller(
    owner: flow.Human, stranger: flow.Human, migrated: Engine
) -> None:
    _links(owner, "colleagues")
    mine = owner.get(f"{P}/maintainer").json()  # one's own, always
    assert mine["website"] == "https://example.org" and mine["social"]["github"]
    _not_found(stranger.get(f"{P}/maintainer"))  # a link not admitted shows nothing
    _links(owner, "everyone")
    body = stranger.get(f"{P}/maintainer").json()  # a link admitted is enough to be seen
    assert (body["website"], body["projects_total"], body["page_served"]) == (
        "https://example.org",
        0,
        False,
    )
    _links(owner, "colleagues")
    factory.membership(migrated, _project_id(migrated, "maity"), "coder", human_id=stranger.id)
    assert stranger.get(f"{P}/maintainer").json()["website"] == "https://example.org"
    _links(owner, "private")
    assert "website" not in stranger.get(f"{P}/maintainer").json()


def test_a_hold_makes_everyone_count_as_colleagues(
    owner: flow.Human, stranger: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _links(owner, "everyone")
    assert stranger.get(f"{P}/maintainer").status_code == 200
    held = SimpleNamespace(action="hide", at=clock.now(), report_id="rep-1")
    real = moderation.hold
    monkeypatch.setattr(
        moderation,
        "hold",
        lambda conn, kind, target: held if target == owner.id else real(conn, kind, target),
    )
    _not_found(stranger.get(f"{P}/maintainer"))  # a stranger is no colleague
    factory.membership(migrated, _project_id(migrated, "maity"), "coder", human_id=stranger.id)
    assert stranger.get(f"{P}/maintainer").json()["website"] == "https://example.org"


# --- an organisation ---------------------------------------------------------------------------


def test_a_member_of_the_organisation_sees_its_members_and_projects(
    owner: flow.Human, stranger: flow.Human, migrated: Engine
) -> None:
    org = make_org(owner)
    add_member(migrated, org["id"], stranger.id, "member")
    made = owner.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"})
    assert made.status_code == 201, made.text
    _with_picture(owner)
    body = stranger.get(f"{P}/oz-team").json()
    assert (body["kind"], body["handle"], body["page_served"]) == ("organisation", "oz-team", False)
    assert _reads(migrated, stranger, org["id"])  # its members read its picture (§6.10)
    # Its projects only where their page is served or the caller is in them (§6.27).
    assert (body["projects"], body["projects_total"]) == ([], 0)
    roles = {m["handle"]: m["role"] for m in body["members"]}
    assert roles == {"maintainer": "owner", "stranger": "member"}
    assert "public_bio" not in body and "website" not in body
    pictures = {m["handle"]: m["avatar_url"] for m in body["members"]}
    # A fellow member of the organisation reads its picture, not each other's (§6.10).
    assert pictures["maintainer"] is None
    factory.membership(migrated, _project_id(migrated, "maity"), "coder", human_id=stranger.id)
    pictures = {
        m["handle"]: m["avatar_url"] for m in stranger.get(f"{P}/oz-team").json()["members"]
    }
    assert pictures["maintainer"] is not None  # now they share a project
    assert stranger.client.get(pictures["maintainer"]).status_code == 200


def test_an_outsider_sees_an_organisation_only_through_what_it_serves(
    owner: flow.Human, stranger: flow.Human, migrated: Engine
) -> None:
    org = make_org(owner)
    owner.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"})
    _not_found(stranger.get(f"{P}/oz-team"))
    _serve(migrated, "project", _project_id(migrated, "shop"), "/oz-team/shop")
    body = stranger.get(f"{P}/oz-team").json()
    assert body["projects"] == [{"full_name": "oz-team/shop", "name": "Shop", "shared": False}]
    assert "members" not in body and body["avatar_url"] is None
    assert not _reads(migrated, stranger, org["id"])
    _serve(migrated, "organisation", org["id"], "/oz-team")
    assert stranger.get(f"{P}/oz-team").json()["page_served"] is True


def test_a_deleted_organisation_is_not_found(owner: flow.Human, migrated: Engine) -> None:
    org = make_org(owner)
    with migrated.begin() as conn:
        conn.execute(update(t.org).where(t.org.c.id == org["id"]).values(deleted_at=clock.now()))
    _not_found(owner.get(f"{P}/oz-team"))


def test_a_member_of_one_of_its_projects_reads_the_organisations_picture(
    owner: flow.Human, stranger: flow.Human, migrated: Engine
) -> None:
    org = make_org(owner)
    owner.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"})
    factory.membership(migrated, _project_id(migrated, "shop"), "coder", human_id=stranger.id)
    body = stranger.get(f"{P}/oz-team").json()
    assert "members" not in body
    assert body["projects"] == [{"full_name": "oz-team/shop", "name": "Shop", "shared": True}]
    assert _reads(migrated, stranger, org["id"])  # a member of one of its projects (§6.10)


def test_a_project_page_the_owner_turns_on_and_off_is_what_the_view_lists(
    owner: flow.Human, stranger: flow.Human
) -> None:
    flow.project(owner, "open-one")
    assert owner.patch("/projects/maintainer/open-one", {"public_page": "on"}).status_code == 200
    body = stranger.get(f"{P}/maintainer").json()
    assert body["projects"] == [
        {"full_name": "maintainer/open-one", "name": "Open-One", "shared": False}
    ]
    assert owner.patch("/projects/maintainer/open-one", {"public_page": "off"}).status_code == 200
    _not_found(stranger.get(f"{P}/maintainer"))  # nothing left to show a stranger
