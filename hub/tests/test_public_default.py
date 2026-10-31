"""docs/api.md §6.1, §16.9: a new project is public by default for its namespace owner, and a
repository the hub does not see public keeps or turns the page off (tsk-es3adbcyvy4v)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import forge
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_orgs import team
from tests.test_probe import REPO, FakeGitHub, github, settings  # noqa: F401  (fixtures)

PROJECT = "/projects/maintainer/maity"
OTHER = {"url": "https://github.com/acme/other", "default_branch": "main"}
PUBLIC = {"full_name": "acme/maity", "private": False}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def create(who: flow.Human, slug: str = "maity", **body: Any) -> Any:
    return who.post("/projects", {"slug": slug, "name": slug.title(), **body})


def stored(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.project.c.public_page, t.project.c.repository_public)).one()


# --- creating -----------------------------------------------------------------------------------


def test_a_project_is_public_by_default_for_its_namespace_owner(
    owner: flow.Human, migrated: Engine
) -> None:
    made = create(owner)
    assert made.status_code == 201, made.text
    assert made.json()["public_page"] == "on"
    assert tuple(stored(migrated)) == ("on", None)  # no repository: nothing to look at


def test_off_is_taken_from_anyone(owner: flow.Human) -> None:
    made = create(owner, public_page="off")
    assert made.status_code == 201 and made.json()["public_page"] == "off"
    on = create(owner, "second", public_page="on")
    assert on.status_code == 201 and on.json()["public_page"] == "on"
    assert create(owner, "third", public_page="maybe").status_code == 400


def test_in_an_organisation_the_page_is_an_owners_to_give(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    admin, member = people["admin"], people["member"]
    by_owner = create(owner, "by-owner", owner="oz-team")
    assert by_owner.status_code == 201 and by_owner.json()["public_page"] == "on"
    by_admin = create(admin, "by-admin", owner="oz-team")  # an admin is no owner
    assert by_admin.status_code == 201 and by_admin.json()["public_page"] == "off"
    refused = create(admin, "asks-on", owner="oz-team", public_page="on")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "org_role"}
    asked_off = create(admin, "asks-off", owner="oz-team", public_page="off")
    assert asked_off.status_code == 201 and asked_off.json()["public_page"] == "off"
    owner.patch("/orgs/oz-team", {"members_create_projects": True})
    by_member = create(member, "by-member", owner="oz-team")
    assert by_member.status_code == 201 and by_member.json()["public_page"] == "off"


def test_a_repository_the_hub_sees_public_keeps_the_page_on(
    owner: flow.Human, migrated: Engine, github: FakeGitHub  # noqa: F811
) -> None:
    github.answers["/repos/acme/maity"] = PUBLIC
    made = create(owner, repository=REPO)
    assert made.status_code == 201, made.text
    assert made.json()["public_page"] == "on"
    assert tuple(stored(migrated)) == ("on", True)  # the first look is kept for the page


@pytest.mark.parametrize(
    "answer",
    [
        {"full_name": "acme/maity", "private": True},
        {"full_name": "acme/maity"},  # says nothing: counts as private
        forge.ForgeUnavailableError("down"),
        forge.NotCoveredError("no_grant"),
    ],
)
def test_a_private_or_unreadable_repository_creates_the_project_off(
    owner: flow.Human,
    migrated: Engine,
    github: FakeGitHub,  # noqa: F811
    answer: Any,
) -> None:
    github.answers["/repos/acme/maity"] = answer
    made = create(owner, repository=REPO)
    assert made.status_code == 201, made.text
    assert made.json()["public_page"] == "off"  # the 201 carries the value set
    assert tuple(stored(migrated)) == ("off", None)
    still = create(owner, "asked", repository=REPO, public_page="on")  # whatever was sent
    assert still.json()["public_page"] == "off"


def test_a_page_asked_off_needs_no_look_at_the_forge(
    owner: flow.Human, github: FakeGitHub  # noqa: F811
) -> None:
    made = create(owner, repository=REPO, public_page="off")
    assert made.status_code == 201 and made.json()["public_page"] == "off"
    assert github.calls == []


# --- the repository later -----------------------------------------------------------------------


def _agent_of_a_stranger(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    return factory.agent(engine, project_id, factory.human(engine, "stranger")).agent_id


def _isolated(engine: Engine, agent_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership.c.isolated_since, t.membership.c.isolated_by).where(
                t.membership.c.agent_id == agent_id
            )
        ).one()


def test_a_repository_the_hub_finds_private_turns_the_page_off_and_isolates_outsiders(
    owner: flow.Human, migrated: Engine, github: FakeGitHub  # noqa: F811
) -> None:
    assert create(owner).json()["public_page"] == "on"
    lent = _agent_of_a_stranger(migrated)
    assert _isolated(migrated, lent).isolated_since is None  # `anyone` while the page is on
    github.answers["/repos/acme/other"] = {"private": True}
    moved = owner.patch(PROJECT, {"repository": OTHER})
    assert moved.status_code == 200, moved.text
    assert moved.json()["public_page"] == "off"
    with migrated.connect() as conn:
        fields = [
            e.payload["fields"]
            for e in conn.execute(select(t.event).where(t.event.c.kind == "project_updated"))
        ]
    assert {"public_page": "off"} in fields  # project_updated, as for any change of the page
    again = _isolated(migrated, lent)
    assert again.isolated_since is not None and again.isolated_by == "hub"
    # the namespace owner turns it on again if they want
    assert owner.patch(PROJECT, {"public_page": "on"}).json()["public_page"] == "on"


def test_a_public_repository_leaves_the_page_as_it_is(
    owner: flow.Human, github: FakeGitHub  # noqa: F811
) -> None:
    assert create(owner).json()["public_page"] == "on"
    github.answers["/repos/acme/other"] = {"private": False}
    assert owner.patch(PROJECT, {"repository": OTHER}).json()["public_page"] == "on"


def test_a_page_that_is_off_stays_off_whatever_the_repository_is(
    owner: flow.Human, github: FakeGitHub  # noqa: F811
) -> None:
    assert create(owner, public_page="off").json()["public_page"] == "off"
    github.answers["/repos/acme/other"] = {"private": False}
    assert owner.patch(PROJECT, {"repository": OTHER}).json()["public_page"] == "off"


def test_the_same_call_that_turns_the_page_on_cannot_keep_a_private_repository_public(
    owner: flow.Human, github: FakeGitHub  # noqa: F811
) -> None:
    create(owner, public_page="off")
    github.answers["/repos/acme/other"] = {"private": True}
    both = owner.patch(PROJECT, {"public_page": "on", "repository": OTHER})
    assert both.status_code == 200 and both.json()["public_page"] == "off"


# --- every way the page stops being served -------------------------------------------------------


def test_archiving_isolates_the_agents_of_outsiders_and_restoring_lifts_nothing(
    owner: flow.Human, migrated: Engine
) -> None:
    assert create(owner).json()["public_page"] == "on"
    lent = _agent_of_a_stranger(migrated)
    assert _isolated(migrated, lent).isolated_since is None
    archived = owner.patch(PROJECT, {"state": "archived", "reason": "done here"})
    assert archived.status_code == 200, archived.text
    assert _isolated(migrated, lent).isolated_by == "hub"
    restored = owner.patch(PROJECT, {"state": "build", "reason": "back"})
    assert restored.status_code == 200, restored.text
    assert _isolated(migrated, lent).isolated_since is not None  # an admin lifts each one
