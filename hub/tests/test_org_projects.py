"""docs/api.md §6.26, "The organisation's projects" and "Organisation owners in its projects":
a project of an organisation, and the hub keeping every owner of it an owner of the project."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_orgs import delete_org, make_org, team

ORG = "/projects/oz-team"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def create(who: flow.Human, slug: str = "shop", **body: Any) -> Any:
    return who.post("/projects", {"slug": slug, "name": slug.title(), "owner": "oz-team", **body})


def members(who: flow.Human, slug: str = "shop") -> dict[str, dict[str, Any]]:
    got = who.get(f"{ORG}/{slug}/members")
    assert got.status_code == 200, got.text
    return {m["handle"]: m for m in got.json()["items"]}


def archive(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))


def test_a_project_is_created_in_the_organisation_and_every_owner_is_an_owner_of_it(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, people = team(make_client, migrated, owner)
    made = create(owner)
    assert made.status_code == 200 or made.status_code == 201, made.text
    project = made.json()
    assert (project["full_name"], project["owner"]) == (
        "oz-team/shop",
        {"id": org["id"], "handle": "oz-team"},
    )
    found = members(owner)
    assert {h: (m["trust"], m["org_owner"]) for h, m in found.items()} == {
        "maintainer": ("owner", True),  # the creator, an owner of the organisation
        "team-owner2": ("owner", True),  # joined by the hub
    }
    with migrated.connect() as conn:
        kept = {
            r.human_id: r.org_keep
            for r in conn.execute(select(t.membership.c.human_id, t.membership.c.org_keep)).all()
        }
    assert kept == {owner.id: "created", people["owner2"].id: "created"}
    assert owner.get("/projects/oz-team/shop").status_code == 200
    # admins and members get no membership from their role
    assert "team-admin" not in found and "team-member" not in found
    # the same slug is free in another namespace
    other = owner.post("/projects", {"slug": "shop", "name": "Shop"})
    assert other.status_code in (200, 201) and other.json()["full_name"] == "maintainer/shop"
    taken = create(owner)
    assert taken.status_code == 400
    assert taken.json()["error"]["details"]["fields"] == {"slug": "taken"}


def test_who_may_create_in_an_organisation(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    admin, member = people["admin"], people["member"]
    assert create(admin, "by-admin").status_code in (200, 201)
    refused = create(member, "by-member")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "org_role"}
    assert owner.patch("/orgs/oz-team", {"members_create_projects": True}).status_code == 200
    assert create(member, "by-member").status_code in (200, 201)
    # a creator who is no owner holds an ordinary membership; the owners join by the hub's rule
    found = members(member, "by-member")
    assert {h: m["org_owner"] for h, m in found.items()} == {
        "team-member": False,
        "maintainer": True,
        "team-owner2": True,
    }
    with migrated.connect() as conn:
        creator = conn.execute(
            select(t.membership.c.org_keep).where(t.membership.c.human_id == member.id)
        ).scalar_one()
    assert creator is None
    # an organisation the caller is not in, and one that does not exist: one answer
    stranger = flow.human(make_client, migrated, "stranger")
    answers = {
        h: stranger.post("/projects", {"slug": "xx", "name": "X", "owner": h})
        for h in ("oz-team", "never-made")
    }
    assert {a.status_code for a in answers.values()} == {400}
    assert {str(a.json()["error"]["details"]) for a in answers.values()} == {
        str({"fields": {"owner": "unknown"}})
    }
    own = stranger.post("/projects", {"slug": "mine", "name": "Mine", "owner": "stranger"})
    assert own.status_code in (200, 201) and own.json()["full_name"] == "stranger/mine"


def test_an_owner_made_later_joins_every_project_archived_ones_included(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    assert create(owner, "live").status_code in (200, 201)
    assert create(owner, "old").status_code in (200, 201)
    with migrated.begin() as conn:
        conn.execute(update(t.project).where(t.project.c.slug == "old").values(state="archived"))
    admin, member = people["admin"], people["member"]
    # the admin is a member of one of them already, with a lower trust
    joined = owner_joined(migrated)
    with migrated.begin() as conn:
        pid = conn.execute(select(t.project.c.id).where(t.project.c.slug == "live")).scalar_one()
        conn.execute(
            t.membership.insert().values(
                project_id=pid,
                human_id=admin.id,
                trust="member",
                role="coder",
                areas=["/"],
                capabilities=[],
                joined_at=joined,
                last_seen_at=joined,
            )
        )
    promoted = owner.patch(f"/orgs/oz-team/members/{admin.id}", {"role": "owner"})
    assert promoted.status_code == 200
    for slug in ("live", "old"):
        shown = members(owner, slug)["team-admin"]
        assert (shown["trust"], shown["org_owner"]) == ("owner", True), slug
    with migrated.connect() as conn:
        rows = {
            (r.project_id, r.org_keep, r.org_keep_trust)
            for r in conn.execute(
                select(t.membership).where(t.membership.c.human_id == admin.id)
            ).all()
        }
    assert {(keep, before) for _, keep, before in rows} == {("raised", "member"), ("created", None)}
    # demoted again: the raised one falls back, the one the hub made ends
    demoted = owner.patch(f"/orgs/oz-team/members/{admin.id}", {"role": "member"})
    assert demoted.status_code == 200
    live = members(owner, "live")["team-admin"]
    assert (live["trust"], live["org_owner"]) == ("member", False)
    assert "team-admin" not in members(owner, "old")
    assert member.get(f"{ORG}/live").status_code in (200, 403, 404)


def owner_joined(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.membership.c.joined_at)).scalars().first()


def test_an_organisations_owner_stays_an_owner_of_its_projects(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    assert create(owner).status_code in (200, 201)
    second = people["owner2"]
    found = members(owner)["team-owner2"]
    demoted = owner.patch(f"{ORG}/shop/members/{found['id']}", {"trust": "admin"})
    assert demoted.status_code == 409, demoted.text
    assert demoted.json()["error"]["code"] == "namespace_owner"
    assert demoted.json()["error"]["details"] == {"projects": ["oz-team/shop"]}
    removed = owner.delete(f"{ORG}/shop/members/{found['id']}")
    assert (removed.status_code, removed.json()["error"]["code"]) == (409, "namespace_owner")
    assert second.get(f"{ORG}/shop/members").status_code == 200
    # they stop being an owner of the organisation first, and then they may go
    assert owner.patch(f"/orgs/oz-team/members/{second.id}", {"role": "admin"}).status_code == 200
    assert "team-owner2" not in members(owner)


def test_an_organisation_with_an_open_project_cannot_be_deleted(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    assert create(owner).status_code in (200, 201)
    refused = delete_org(owner, "oz-team", "oz-team")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "namespace_owner"
    assert refused.json()["error"]["details"] == {"projects": ["oz-team/shop"]}
    assert owner.get("/orgs/oz-team").status_code == 200
    archive(migrated)
    done = delete_org(owner, "oz-team", "oz-team")
    assert done.status_code == 204, done.text
    # the archived project stays under its name, and nobody keeps a seat in it
    assert owner.get("/projects/oz-team/shop").status_code in (200, 403, 404)
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert (project.state, project.owner_org_id is not None) == ("archived", True)
        seats = conn.execute(
            select(t.membership.c.active).where(t.membership.c.project_id == project.id)
        ).all()
        assert all(r.active is None for r in seats)


def test_the_invited_owner_joins_the_projects_with_their_go(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    assert create(owner).status_code in (200, 201)
    guest = flow.human(make_client, migrated, "guest")
    url = "/orgs/oz-team/members/invitations"
    assert owner.post(url, {"handle": "guest", "role": "owner"}).status_code == 202
    [pending] = guest.get("/requests").json()["items"]
    assert guest.post(f"/requests/{pending['id']}/answer", {"reply_id": "go"}).status_code == 200
    assert members(owner)["guest"]["trust"] == "owner"
    assert members(owner)["guest"]["org_owner"] is True
