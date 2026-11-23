"""The instance admin's lists and the organisations' lists cost the same statements for 3
rows as for 30 (tests/list_rows.py): the maintenance changes, the organisations, the pending
registrations, the reports; a human's organisations, an organisation's members and its open
invitations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, events, orgs
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.list_rows import flat_rows, same_for_3_and_30
from tests.test_orgs import add_member, make_org

_N = [0]


def _n() -> int:
    _N[0] += 1
    return _N[0]


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin (the earliest account), owner of a project."""
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _get(who: flow.Human, path: str) -> Any:
    return lambda: who.get(path)


def _org(engine: Engine, owner_id: str) -> Any:
    """An organisation made the way `POST /orgs` makes one, without the per-human limit."""
    n = _n()
    with events.transaction(engine) as conn:
        made, _ = orgs.create(conn, owner_id, f"team-{n:03d}", f"Team {n}", None)
    return made


@flat_rows("/admin/maintenance/changes")
def test_the_maintenance_changes_cost_the_same_for_3_and_for_30(
    admin: flow.Human, migrated: Engine
) -> None:
    now = clock.now()
    window = new_id("maintenance_window")
    with migrated.begin() as conn:
        conn.execute(
            insert(t.maintenance_window).values(
                id=window,
                starts_at=now + timedelta(days=1),
                ends_at=now + timedelta(days=1, hours=1),
                text="Upgrade",
                created_by=admin.id,
                created_at=now,
                updated_by=admin.id,
                updated_at=now,
            )
        )

    def grow(n: int) -> None:
        with migrated.begin() as conn:
            for _ in range(n):
                conn.execute(
                    insert(t.maintenance_change).values(
                        id=new_id("maintenance_change"),
                        window_id=window,
                        action="changed",
                        starts_at=now + timedelta(days=1),
                        ends_at=now + timedelta(days=1, hours=1),
                        text="Upgrade",
                        by=admin.id,
                        at=clock.now(),
                    )
                )

    route = "/admin/maintenance/changes"
    same_for_3_and_30(migrated, route, _get(admin, f"{route}?limit=200"), grow)


@flat_rows("/admin/orgs")
def test_the_instance_s_organisations_cost_the_same_for_3_and_for_30(
    admin: flow.Human, migrated: Engine
) -> None:
    owners = [factory.human(migrated, f"owner-{i}") for i in range(3)]

    def grow(n: int) -> None:
        for i in range(n):
            made = _org(migrated, owners[i % 3])
            add_member(migrated, made.id, owners[(i + 1) % 3], "owner")

    same_for_3_and_30(migrated, "/admin/orgs", _get(admin, "/admin/orgs?limit=200"), grow)


@flat_rows("/admin/registrations")
def test_the_pending_registrations_cost_the_same_for_3_and_for_30(
    admin: flow.Human, migrated: Engine
) -> None:
    def grow(n: int) -> None:
        for _ in range(n):
            handle = f"pending-{_n():03d}"
            human_id = factory.human(migrated, handle)
            now = clock.now()
            with migrated.begin() as conn:
                conn.execute(
                    insert(t.account_registration).values(
                        human_id=human_id,
                        address=f"{handle}@example.org",
                        address_normalized=f"{handle}@example.org",
                        source_ip="203.0.113.7",
                        created_at=now,
                        expires_at=now + timedelta(days=7),
                        status="pending",
                    )
                )

    route = "/admin/registrations"
    same_for_3_and_30(migrated, route, _get(admin, f"{route}?limit=200"), grow)


@flat_rows("/admin/reports")
def test_the_reports_cost_the_same_for_3_and_for_30(admin: flow.Human, migrated: Engine) -> None:
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == admin.id)
        ).scalar_one()
    reporters = [factory.human(migrated, f"reporter-{i}") for i in range(3)]

    def grow(n: int) -> None:
        for i in range(n):
            card = factory.card(migrated, project_id, member, title="Free tokens")
            reporter = reporters[i % 3]
            with migrated.begin() as conn:
                conn.execute(
                    insert(t.abuse_report).values(
                        id=new_id("abuse_report"),
                        reporter=reporter,
                        account_id=reporter,
                        target_type="card",
                        target_id=card,
                        project_id=project_id,
                        reason="spam",
                        text="spam",
                        snapshot={"title": "Free tokens"},
                        status="open" if i % 2 else "resolved",
                        created_at=clock.now(),
                    )
                )

    route = "/admin/reports"
    same_for_3_and_30(migrated, route, _get(admin, f"{route}?limit=200"), grow)


@flat_rows("/orgs")
def test_a_human_s_organisations_cost_the_same_for_3_and_for_30(
    admin: flow.Human, migrated: Engine
) -> None:
    other = factory.human(migrated, "other")

    def grow(n: int) -> None:
        for i in range(n):
            if i % 2:
                _org(migrated, admin.id)  # owned
            else:
                add_member(migrated, _org(migrated, other).id, admin.id, "member")

    same_for_3_and_30(migrated, "/orgs", _get(admin, "/orgs"), grow)


@flat_rows("/orgs/{}/members")
def test_an_organisation_s_members_cost_the_same_for_3_and_for_30(
    admin: flow.Human, migrated: Engine
) -> None:
    org = make_org(admin)
    roles = ("member", "admin", "owner")

    def grow(n: int) -> None:
        for i in range(n):
            human_id = factory.human(migrated, f"member-{_n():03d}")
            add_member(migrated, org["id"], human_id, roles[i % 3])

    route = "/orgs/{}/members"
    same_for_3_and_30(migrated, route, _get(admin, f"/orgs/{org['handle']}/members"), grow)


@flat_rows("/orgs/{}/members/invitations")
def test_an_organisation_s_invitations_cost_the_same_for_3_and_for_30(
    admin: flow.Human, migrated: Engine
) -> None:
    """Stored as `POST …/members/invitations` stores them (its limiter allows fewer than 30
    a test), by two inviters."""
    org = make_org(admin)
    second = factory.human(migrated, "second")
    add_member(migrated, org["id"], second, "owner")

    def grow(n: int) -> None:
        now = clock.now()
        with migrated.begin() as conn:
            for i in range(n):
                conn.execute(
                    insert(t.org_invitation).values(
                        id=new_id("org_invitation"),
                        org_id=org["id"],
                        handle=f"invitee-{_n():03d}",
                        role="member",
                        invited_by=(admin.id, second)[i % 2],
                        created_at=now,
                        expires_at=now + timedelta(days=14),
                        live=True,
                    )
                )

    path = f"/orgs/{org['handle']}/members/invitations"
    same_for_3_and_30(migrated, "/orgs/{}/members/invitations", _get(admin, path), grow)
