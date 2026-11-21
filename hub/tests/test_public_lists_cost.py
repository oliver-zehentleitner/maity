"""The public lists ask whether a project has a page once for all their projects
(`public_projects.served_among`) and read the full names once (`namespace.full_names`): `/explore`,
an organisation's page, a person's and an agent's projects and the landing page's counters cost
the same statements for 3 projects as for 30. `served` for one project judges the row it is
given, as a PATCH asks it of the project as it will be (§6.1, §6.2, §16.9)."""

from __future__ import annotations

from collections.abc import Callable, Sized
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import (
    clock,
    events,
    landing_stats,
    orgs,
    public_agents,
    public_orgs,
    public_pages,
    public_people,
    public_projects,
)
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.list_rows import same_for_3_and_30
from tests.statements import count_statements
from tests.test_agent_owners import PROJECT, _friend, _isolated, _project, _remove
from tests.test_public_project_views import World


@pytest.fixture
def hub(settings: Settings) -> Settings:
    public = replace(settings, public_pages=True)
    public_pages.configure(public)
    return public


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, hub: Settings) -> World:
    return World(make_client, migrated)


def _org(engine: Engine, owner_id: str, handle: str) -> str:
    with events.transaction(engine) as conn:
        made, _ = orgs.create(conn, owner_id, handle, handle.title(), None)
    with engine.begin() as conn:
        conn.execute(update(t.org).where(t.org.c.id == made.id).values(public_page="on"))
    return str(made.id)


def _hold(engine: Engine, reporter: str, target_type: str, target_id: str) -> None:
    report_id = f"rpt-{target_id[-12:]}"
    with engine.begin() as conn:
        conn.execute(
            insert(t.abuse_report).values(
                id=report_id, reporter=reporter, account_id=reporter, target_type=target_type,
                target_id=target_id, reason="spam", status="resolved", action="hide",
                created_at=clock.now(),
            )
        )  # fmt: skip
        conn.execute(
            insert(t.moderation_hold).values(
                report_id=report_id,
                target_type=target_type,
                target_id=target_id,
                action="hide",
                at=clock.now(),
            )
        )


class Projects:
    """Public projects made one after the other, by turns in an organisation's namespace and in
    a human's of their own, and with each third shown one a project no list may show: under a
    hold, archived, or of a suspended owner."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.engine = world.migrated
        self.org = _org(self.engine, world.owner.id, "team-a")
        self.made = 0

    def __call__(self, n: int) -> None:
        self.make(n)

    def make(self, n: int) -> list[str]:
        """`n` more shown projects, and their ids."""
        shown: list[str] = []
        for _ in range(n):
            self.made += 1
            k = self.made
            owner = self.org if k % 2 else factory.human(self.engine, f"owner-{k}")
            shown.append(factory.project(self.engine, f"p-{k}", owner_id=owner, public_page="on"))
            if k % 3 == 0:
                self._hidden(k)
        return shown

    def _hidden(self, k: int) -> None:
        held = factory.project(self.engine, f"held-{k}", owner_id=self.org, public_page="on")
        _hold(self.engine, self.world.anna.id, "project", held)
        factory.project(
            self.engine, f"old-{k}", owner_id=self.org, public_page="on", state="archived"
        )
        gone = factory.human(self.engine, f"gone-{k}")
        with self.engine.begin() as conn:
            conn.execute(
                update(t.human).where(t.human.c.id == gone).values(suspended_at=clock.now())
            )
        factory.project(self.engine, f"sus-{k}", owner_id=gone, public_page="on")


def _flat(engine: Engine, read: Callable[[], Sized], grow: Callable[[int], Any]) -> None:
    """`read` costs the same statements after `grow(3)` as after `grow(27)` more, and answers 27
    more entries the second time."""
    read()  # a first read of its own: caches and one-time writes are no row cost
    grow(3)
    few_rows: list[int] = []
    few = count_statements(engine, lambda: few_rows.append(len(read())), async_engines=False)
    grow(27)
    many_rows: list[int] = []
    many = count_statements(engine, lambda: many_rows.append(len(read())), async_engines=False)
    assert many_rows[0] - few_rows[0] == 27, (few_rows, many_rows)
    assert many == few, f"{few} statements for 3 projects, {many} for 30"


def test_explore_costs_the_same_for_3_projects_and_for_30(world: World, migrated: Engine) -> None:
    same_for_3_and_30(
        migrated,
        "/explore",
        lambda: world.anyone.get("/explore"),
        Projects(world),
        rows=lambda answer: answer.text.count('class="xcard"'),
        async_engines=True,
    )


def test_an_organisation_s_page_costs_the_same_for_3_projects_and_for_30(
    world: World, migrated: Engine, hub: Settings
) -> None:
    projects = Projects(world)

    def read() -> list[Any]:
        with migrated.begin() as conn:
            (page,) = public_orgs.render_org(conn, hub, projects.org)
        listed: list[Any] = page.data["projects"]
        return listed

    def grow(n: int) -> None:  # the organisation's own projects, with the hidden ones
        for _ in range(n):
            projects.made += 1
            factory.project(migrated, f"p-{projects.made}", owner_id=projects.org, public_page="on")
            projects._hidden(projects.made)

    _flat(migrated, read, grow)


def test_a_person_s_projects_cost_the_same_for_3_and_for_30(world: World, migrated: Engine) -> None:
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    projects = Projects(world)

    def read() -> list[Any]:
        with migrated.begin() as conn:
            human = conn.execute(select(t.human).where(t.human.c.id == world.owner.id)).one()
            return public_people._listed(conn, human)

    def grow(n: int) -> None:
        for project_id in projects.make(n):
            factory.membership(migrated, project_id, "member", human_id=world.owner.id)

    _flat(migrated, read, grow)


def test_an_agent_s_projects_cost_the_same_for_3_and_for_30(world: World, migrated: Engine) -> None:
    with migrated.connect() as conn:
        bot = conn.execute(select(t.agent_profile.c.id)).scalar_one()
    projects = Projects(world)

    def read() -> list[Any]:
        with migrated.begin() as conn:
            return public_agents.memberships(conn, bot)

    def grow(n: int) -> None:
        for project_id in projects.make(n):
            factory.membership(migrated, project_id, "member", agent_id=bot)

    _flat(migrated, read, grow)


def test_the_landing_page_s_count_costs_the_same_for_3_projects_and_for_30(
    world: World, migrated: Engine
) -> None:
    def read() -> range:
        with migrated.begin() as conn:
            return range(landing_stats.compute(conn)["public_projects"])

    _flat(migrated, read, Projects(world))


def test_served_judges_the_row_it_is_given_not_the_stored_one(
    world: World, migrated: Engine
) -> None:
    """A PATCH asks `served` of the project as it will be (`agent_owners.effective` in
    `routes.projects._refuse_outside_roles`): the `public_page` of the row given counts, not the
    one stored. `served_among` reads the stored one."""
    with migrated.connect() as conn:
        stored = conn.execute(select(t.project)).one()
        assert stored.public_page == "on"
        off = SimpleNamespace(**{**stored._mapping, "public_page": "off"})
        assert public_projects.served(conn, stored)
        assert not public_projects.served(conn, off)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(public_page="off"))
    with migrated.connect() as conn:
        stored = conn.execute(select(t.project)).one()
        on = SimpleNamespace(**{**stored._mapping, "public_page": "on"})
        assert public_projects.served(conn, on)
        assert not public_projects.served(conn, stored)
        assert public_projects.served_among(conn, [stored.id]) == set()


def test_a_patch_that_turns_the_page_on_checks_outside_roles_by_the_new_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§6.1, §6.2: with `agent_owners` unset, a PATCH that turns the page on makes the project
    read `anyone` after the call, so a narrower `outside_roles` in the same call is refused while
    an outsider's agent at work holds a role it leaves out, though the stored page is still off."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)  # private, `agent_owners` unset: it reads `members`
    friend = _friend(make_client, migrated)
    worker = factory.agent(migrated, _project(migrated), friend.id, "member").agent_id
    assert _remove(owner, migrated, friend.id).status_code == 200
    assert _isolated(migrated, worker)
    with migrated.begin() as conn:  # an outsider's agent at work, as under `anyone`
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == worker)
            .values(isolated_since=None, isolated_by=None, isolated_reason=None)
        )
    refused = owner.patch(
        PROJECT,
        {
            "public_page": "on",
            "policy": {"outside_roles": ["designer"]},
            "reason": "who may bring agents",
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"outside_roles": "outside_owner"}
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.public_page)).scalar_one() == "off"
