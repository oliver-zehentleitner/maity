"""docs/api.md §16.8 and §6.26: `suspend` on a report about a project of an organisation applies
to the organisation, never to a person."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_orgs import add_member, delete_org, make_org
from tests.test_reports import report
from tests.test_two_factor import Clock
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

PROJECT = "oz-team/shop"


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, moment: Clock) -> dict[str, Any]:
    """The instance admin `maintainer` (the earliest account); an organisation of `boss` and
    `second` with a project `oz-team/shop`; `pat`, a member of the project, reports it."""
    admin = flow.human(make_client, migrated)
    moment.move(seconds=1)
    boss = flow.human(make_client, migrated, "boss")
    second = flow.human(make_client, migrated, "second")
    org = make_org(boss, "oz-team", "OZ Team")
    add_member(migrated, org["id"], second.id, "owner")
    made = boss.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"})
    assert made.status_code in (200, 201), made.text
    pat = flow.human(make_client, migrated, "pat")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=pat.id)
    return {
        "admin": admin,
        "boss": boss,
        "second": second,
        "pat": pat,
        "org": org,
        "project_id": project_id,
    }


def resolve(world: dict[str, Any], report_id: str, action: str, note: str | None = None) -> Any:
    body: dict[str, Any] = {"action": action}
    if note is not None:
        body["note"] = note
    return world["admin"].post(f"/admin/reports/{report_id}/resolve", body)


def filed(world: dict[str, Any]) -> str:
    made = report(world["pat"], {"type": "project", "id": PROJECT}, "spam")
    assert made.status_code == 201, made.text
    found: str = made.json()["id"]
    return found


def held(response: Any) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["details"]["reason"] == "moderation_hold"


def test_a_suspension_marks_the_organisation_and_touches_no_person(
    world: dict[str, Any], migrated: Engine
) -> None:
    boss = world["boss"]
    id_ = filed(world)
    done = resolve(world, id_, "suspend", "a scam shop")
    assert done.status_code == 200, done.text
    shown = boss.get("/orgs/oz-team").json()
    assert shown["moderation"]["action"] == "suspend" and shown["moderation"]["report_id"] == id_
    assert shown["public_page"] == "off"
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.state)).scalar_one() == "archived"
        # nobody's account is suspended, and the members stay members
        assert conn.execute(select(t.human.c.suspended_at)).scalars().all() == [None] * 4
        assert len(conn.execute(select(t.org_member)).all()) == 2
        notices = conn.execute(
            select(t.account_record.c.human_id, t.account_record.c.data).where(
                t.account_record.c.type == "moderation_applied"
            )
        ).all()
    assert sorted(n.human_id for n in notices) == sorted([boss.id, world["second"].id])
    assert all(n.data["action"] == "suspend" and n.data["note"] == "a scam shop" for n in notices)


def test_while_suspended_the_organisation_takes_nothing_new(
    world: dict[str, Any], migrated: Engine
) -> None:
    boss = world["boss"]
    assert resolve(world, filed(world), "suspend").status_code == 200
    held(boss.post("/projects", {"slug": "again", "name": "Again", "owner": "oz-team"}))
    held(boss.post("/orgs/oz-team/members/invitations", {"handle": "pat", "role": "member"}))
    held(boss.patch("/orgs/oz-team", {"public_page": "on"}))
    # what stays allowed: its settings, its members and roles, its deletion
    assert boss.patch("/orgs/oz-team", {"display_name": "OZ Team II"}).status_code == 200
    assert boss.patch("/orgs/oz-team", {"public_page": "off"}).status_code == 200
    second = world["second"]
    assert boss.patch(f"/orgs/oz-team/members/{second.id}", {"role": "admin"}).status_code == 200
    assert delete_org(boss, "oz-team", "oz-team").status_code == 204  # its project is archived


def test_dismissing_the_report_lifts_the_hold_and_restores_nothing(
    world: dict[str, Any], migrated: Engine
) -> None:
    boss = world["boss"]
    id_ = filed(world)
    assert resolve(world, id_, "suspend").status_code == 200
    assert resolve(world, id_, "dismiss").status_code == 200
    assert "moderation" not in boss.get("/orgs/oz-team").json()
    with migrated.connect() as conn:  # the project stays archived: the owners reopen what they want
        assert conn.execute(select(t.project.c.state)).scalar_one() == "archived"
    assert boss.post(
        "/projects", {"slug": "again", "name": "Again", "owner": "oz-team"}
    ).status_code in (
        200,
        201,
    )
    assert boss.patch("/orgs/oz-team", {"public_page": "on"}).status_code == 200


def test_every_open_transfer_into_the_organisation_is_withdrawn(
    world: dict[str, Any], migrated: Engine
) -> None:
    with migrated.begin() as conn:
        asker = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == world["pat"].id)
        ).scalar_one()
        request_id = "req-transfer-into"
        conn.execute(
            insert(t.request).values(
                id=request_id,
                project_id=world["project_id"],
                org_id=world["org"]["id"],
                **{"class": "consent"},
                title="Take over a project into oz-team",
                options=[],
                priority="normal",
                to_kind="human",
                to_human=world["boss"].id,
                personal=True,
                asked_by=asker,
                while_open="wait",
                status="open",
                created_at=clock.now(),
                proposal={
                    "kind": "project_transfer",
                    "project_id": world["project_id"],
                    "owner_id": "hum-x",
                    "full_name": "x/y",
                    "to": world["org"]["id"],
                },
            )
        )
    assert resolve(world, filed(world), "suspend").status_code == 200
    with migrated.connect() as conn:
        status = conn.execute(
            select(t.request.c.status).where(t.request.c.id == request_id)
        ).scalar_one()
    assert status == "withdrawn"


def test_a_deleted_organisation_cannot_be_suspended(
    world: dict[str, Any], migrated: Engine
) -> None:
    id_ = filed(world)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
    assert delete_org(world["boss"], "oz-team", "oz-team").status_code == 204
    refused = resolve(world, id_, "suspend")
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["reason"] == "no_org"


def test_hide_and_remove_notify_every_owner_of_the_organisation(
    world: dict[str, Any], migrated: Engine
) -> None:
    assert resolve(world, filed(world), "remove", "gone").status_code == 200
    with migrated.connect() as conn:
        owners = sorted(
            r.human_id
            for r in conn.execute(
                select(t.account_record.c.human_id).where(
                    t.account_record.c.type == "moderation_applied"
                )
            ).all()
        )
    assert owners == sorted([world["boss"].id, world["second"].id])


def test_while_suspended_its_archived_projects_cannot_be_reopened_or_made_public(
    world: dict[str, Any], migrated: Engine
) -> None:
    boss = world["boss"]
    id_ = filed(world)
    assert resolve(world, id_, "suspend").status_code == 200
    reopen = boss.patch(f"/projects/{PROJECT}", {"state": "build", "reason": "back again"})
    held(reopen)
    held(boss.patch(f"/projects/{PROJECT}", {"policy": {"swarm_public": "on"}, "reason": "show"}))
    assert boss.get(f"/projects/{PROJECT}").json()["state"] == "archived"
    # lifted, the owners change what they want: nothing was restored by the lifting
    assert resolve(world, id_, "dismiss").status_code == 200
    assert boss.get(f"/projects/{PROJECT}").json()["state"] == "archived"
    again = boss.patch(f"/projects/{PROJECT}", {"state": "build", "reason": "back again"})
    assert again.status_code == 200, again.text
    assert boss.get(f"/projects/{PROJECT}").json()["state"] == "build"


def test_a_hide_of_the_project_does_not_hide_the_suspension_of_its_organisation(
    world: dict[str, Any], migrated: Engine
) -> None:
    boss = world["boss"]
    hidden = filed(world)
    assert resolve(world, hidden, "hide").status_code == 200
    assert boss.patch(f"/projects/{PROJECT}", {"state": "build", "reason": "up"}).status_code == 200
    assert (
        boss.patch(f"/projects/{PROJECT}", {"state": "archived", "reason": "down"}).status_code
        == 200
    )
    made = report(world["pat"], {"type": "project", "id": PROJECT}, "abuse")
    assert made.status_code == 201, made.text
    assert resolve(world, made.json()["id"], "suspend").status_code == 200
    held(boss.patch(f"/projects/{PROJECT}", {"state": "build", "reason": "back again"}))
    assert boss.get(f"/projects/{PROJECT}").json()["state"] == "archived"


def test_nothing_moves_into_a_suspended_organisation(
    world: dict[str, Any], migrated: Engine, make_client: ClientFactory
) -> None:
    second, boss = world["second"], world["boss"]
    adm = flow.human(make_client, migrated, "adm")
    add_member(migrated, world["org"]["id"], adm.id, "admin")
    flow.project(second, "mine")
    flow.project(adm, "theirs")
    org_id = world["org"]["id"]
    # an admin's request is open when the suspension comes: it is withdrawn with it
    filed_by_admin = adm.post("/projects/adm/theirs/transfer", {"to": org_id})
    assert filed_by_admin.status_code == 202, filed_by_admin.text
    assert resolve(world, filed(world), "suspend").status_code == 200
    held(second.post("/projects/second/mine/transfer", {"to": org_id}))
    held(adm.post("/projects/adm/theirs/transfer", {"to": org_id}))
    # a `go` on a request that is open nevertheless answers `forbidden`, and the request stays open
    with migrated.begin() as conn:
        conn.execute(
            update(t.request)
            .where(t.request.c.status == "withdrawn")
            .values(status="open", withdrawn_at=None, withdraw_reason=None)
        )
    [open_one] = [
        r for r in boss.get("/requests", params={"status": "open"}).json()["items"] if r["personal"]
    ]
    held(boss.post(f"/requests/{open_one['id']}/answer", {"reply_id": "go"}))
    assert adm.get("/projects/adm/theirs").json()["owner"]["id"] != org_id
