"""docs/api.md §6.26, "Transfer into and out of an organisation"."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_orgs import add_member, make_org, team


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def transfer(who: flow.Human, project: str, to: str) -> Any:
    return who.post(f"/projects/{project}/transfer", {"to": to})


def members(who: flow.Human, project: str) -> dict[str, dict[str, Any]]:
    got = who.get(f"/projects/{project}/members")
    assert got.status_code == 200, got.text
    return {m["handle"]: m for m in got.json()["items"]}


def consents(who: flow.Human, status: str = "open") -> list[dict[str, Any]]:
    got = who.get("/requests", params={"status": status})
    assert got.status_code == 200, got.text
    items: list[dict[str, Any]] = got.json()["items"]
    return items


def test_an_owner_of_the_organisation_moves_a_project_into_it_in_the_call(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, people = team(make_client, migrated, owner)
    flow.project(owner, "shop")
    moved = transfer(owner, "maintainer/shop", org["id"])
    assert moved.status_code == 200, moved.text
    assert (moved.json()["full_name"], moved.json()["owner"]["id"]) == ("oz-team/shop", org["id"])
    # the old name is an alias, the owners of the organisation are owners, nobody asked
    assert owner.get("/projects/maintainer/shop").json()["full_name"] == "oz-team/shop"
    found = members(owner, "oz-team/shop")
    assert {h: (m["trust"], m["org_owner"]) for h, m in found.items()} == {
        "maintainer": ("owner", True),
        "team-owner2": ("owner", True),
    }
    assert consents(people["owner2"]) == []
    assert moved.json()["repository"] is None or not moved.json().get("owner_confirmed", False)


def test_an_admin_asks_every_owner_and_the_first_go_moves_it(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    boss = flow.human(make_client, migrated, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    second = flow.human(make_client, migrated, "second")
    add_member(migrated, org["id"], second.id, "owner")
    add_member(migrated, org["id"], owner.id, "admin")
    flow.project(owner, "shop")
    filed = transfer(owner, "maintainer/shop", org["id"])
    assert filed.status_code == 202, filed.text
    [for_boss] = consents(boss)
    [for_second] = consents(second)
    assert (for_boss["org"]["handle"], for_boss["project"]["full_name"]) == (
        "oz-team",
        "maintainer/shop",
    )
    assert for_boss["personal"] and for_boss["class"] == "consent"
    assert [r["id"] for r in for_boss["replies"]] == ["go", "no"]
    # one owner says no: theirs alone closes; the other can still say go
    assert boss.post(f"/requests/{for_boss['id']}/answer", {"reply_id": "no"}).status_code == 200
    assert [r["id"] for r in consents(second)] == [for_second["id"]]
    went = second.post(f"/requests/{for_second['id']}/answer", {"reply_id": "go"})
    assert went.status_code == 200, went.text
    assert owner.get("/projects/oz-team/shop").json()["owner"]["id"] == org["id"]
    kept = members(owner, "oz-team/shop")
    assert {h: m["trust"] for h, m in kept.items() if h in ("boss", "second")} == {
        "boss": "owner",
        "second": "owner",
    }


def test_the_one_who_started_it_withdraws_every_request(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    boss = flow.human(make_client, migrated, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    second = flow.human(make_client, migrated, "second")
    add_member(migrated, org["id"], second.id, "owner")
    add_member(migrated, org["id"], owner.id, "admin")
    flow.project(owner, "shop")
    assert transfer(owner, "maintainer/shop", org["id"]).status_code == 202
    [first] = consents(boss)
    consents(second)
    gone = owner.post(f"/projects/maintainer/shop/requests/{first['id']}/withdraw", {})
    assert gone.status_code == 200, gone.text
    assert consents(boss) == [] and consents(second) == []
    # an owner's own withdrawal counts as their no, and closes theirs alone
    assert transfer(owner, "maintainer/shop", org["id"]).status_code == 202
    [mine_to_boss] = consents(boss)
    assert boss.post(f"/requests/{mine_to_boss['id']}/withdraw", {}).status_code == 200
    assert len(consents(second)) == 1


def test_who_may_hand_a_project_to_an_organisation(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    boss = flow.human(make_client, migrated, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    flow.project(owner, "shop")
    stranger_target = transfer(owner, "maintainer/shop", org["id"])
    assert stranger_target.status_code == 400  # not a member: the organisation is unknown to them
    assert stranger_target.json()["error"]["details"]["fields"] == {"to": "unknown"}
    add_member(migrated, org["id"], owner.id, "member")
    refused = transfer(owner, "maintainer/shop", org["id"])
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "org_role"}
    unknown = transfer(owner, "maintainer/shop", "org-doesnotexist")
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["fields"] == {"to": "unknown"}


def test_a_stale_go_withdraws_the_request(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    boss = flow.human(make_client, migrated, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    add_member(migrated, org["id"], owner.id, "admin")
    flow.project(owner, "shop")
    assert transfer(owner, "maintainer/shop", org["id"]).status_code == 202
    [pending] = consents(boss)
    # the one who started it lost their role meanwhile
    with migrated.begin() as conn:
        conn.execute(
            update(t.org_member).where(t.org_member.c.human_id == owner.id).values(role="member")
        )
    stale = boss.post(f"/requests/{pending['id']}/answer", {"reply_id": "go"})
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["details"] == {"reason": "transfer_stale"}
    assert consents(boss) == []
    assert owner.get("/projects/maintainer/shop").json()["full_name"] == "maintainer/shop"


def test_out_of_an_organisation_to_a_human_who_is_an_owner_of_the_project(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, people = team(make_client, migrated, owner)
    made = owner.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"})
    assert made.status_code in (200, 201), made.text
    second = people["owner2"]
    # an owner hands it to themselves: their call is their word, no request
    back = transfer(second, "oz-team/shop", second.id)
    assert back.status_code == 200, back.text
    assert back.json()["full_name"] == "team-owner2/shop"
    found = members(second, "team-owner2/shop")
    # the receiving human keeps owner, the other owner's seat the hub kept ends
    assert found["team-owner2"]["trust"] == "owner" and found["team-owner2"]["org_owner"] is False
    assert "maintainer" not in found or found["maintainer"]["org_owner"] is False
    with migrated.connect() as conn:
        seat = conn.execute(
            select(t.membership.c.org_keep, t.membership.c.active).where(
                t.membership.c.human_id == owner.id
            )
        ).one()
    assert seat.active is None  # the creator's seat, kept for the organisation, ended with it
    assert org["id"]


def test_out_of_an_organisation_to_another_human_needs_their_go(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, people = team(make_client, migrated, owner)
    assert owner.post(
        "/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"}
    ).status_code in (200, 201)
    heir = flow.human(make_client, migrated, "heir")
    with migrated.begin() as conn:  # an owner of the project of their own
        pid = conn.execute(select(t.project.c.id)).scalar_one()
        conn.execute(
            t.membership.insert().values(
                project_id=pid,
                human_id=heir.id,
                trust="owner",
                role="coder",
                role_base="coder",
                areas=["/"],
                capabilities=[],
                joined_at=conn.execute(select(t.membership.c.joined_at)).scalars().first(),
                last_seen_at=conn.execute(select(t.membership.c.joined_at)).scalars().first(),
            )
        )
    filed = transfer(people["owner2"], "oz-team/shop", heir.id)
    assert filed.status_code == 202, filed.text
    pending = [r for r in heir.get("/projects/oz-team/shop/requests").json()["items"]]
    assert len(pending) == 1
    answered = heir.post(
        f"/projects/oz-team/shop/requests/{pending[0]['id']}/answer", {"reply_id": "go"}
    )
    assert answered.status_code == 200, answered.text
    found = members(heir, "heir/shop")
    assert found["heir"]["trust"] == "owner" and found["heir"]["org_owner"] is False
    assert all(not m["org_owner"] for m in found.values())
    assert org["id"]


def test_between_two_organisations_an_owner_of_both_keeps_their_seat(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    first = make_org(owner, "first-org", "First")
    second = make_org(owner, "second-org", "Second")
    only_first = flow.human(make_client, migrated, "only-first")
    only_second = flow.human(make_client, migrated, "only-second")
    add_member(migrated, first["id"], only_first.id, "owner")
    add_member(migrated, second["id"], only_second.id, "owner")
    made = owner.post("/projects", {"slug": "shop", "name": "Shop", "owner": "first-org"})
    assert made.status_code in (200, 201), made.text
    assert set(members(owner, "first-org/shop")) == {"maintainer", "only-first"}
    moved = transfer(owner, "first-org/shop", second["id"])
    assert moved.status_code == 200, moved.text
    after = members(owner, "second-org/shop")
    assert set(after) == {
        "maintainer",
        "only-second",
    }  # only-first's seat ended, only-second joined
    assert all(m["org_owner"] for m in after.values())


def test_deleting_the_organisation_withdraws_the_transfers_into_it(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    from tests.test_orgs import delete_org

    boss = flow.human(make_client, migrated, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    add_member(migrated, org["id"], owner.id, "admin")
    flow.project(owner, "shop")
    assert transfer(owner, "maintainer/shop", org["id"]).status_code == 202
    assert len(consents(boss)) == 1
    assert delete_org(boss, "oz-team", "oz-team").status_code == 204
    assert consents(boss) == []
    with migrated.connect() as conn:
        [closed] = conn.execute(select(t.request.c.status, t.request.c.withdraw_reason)).all()
    assert tuple(closed) == ("withdrawn", "org_deleted")
    assert owner.get("/projects/maintainer/shop").json()["owner"]["id"] == owner.id


def test_a_project_of_an_organisation_is_renamed_under_the_organisations_lock(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, _ = team(make_client, migrated, owner)
    flow.project(owner, "shop")
    assert transfer(owner, "maintainer/shop", org["id"]).status_code == 200
    renamed = owner.patch("/projects/oz-team/shop", {"slug": "store", "reason": "new name"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["full_name"] == "oz-team/store"


def test_a_rename_that_finds_the_project_moved_meanwhile_is_refused(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route locks the organisation it read, then the project; the project went to a human
    between the two: the organisation that owns it now is unlocked, so the call is to be made
    again (`project_moved`) and renames nothing."""
    from sqlalchemy import update

    from maity_hub import orgs

    org, _ = team(make_client, migrated, owner)
    flow.project(owner, "shop")
    assert transfer(owner, "maintainer/shop", org["id"]).status_code == 200
    real = orgs.lock

    def lock_then_move(conn: Any, org_id: str) -> Any:
        found = real(conn, org_id)
        conn.execute(
            update(t.project).values(owner_id=owner.id, owner_human_id=owner.id, owner_org_id=None)
        )
        return found

    monkeypatch.setattr(orgs, "lock", lock_then_move)
    refused = owner.patch("/projects/oz-team/shop", {"slug": "store", "reason": "new name"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"]["reason"] == "project_moved"
    monkeypatch.undo()
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.slug)).scalar_one() == "shop"
