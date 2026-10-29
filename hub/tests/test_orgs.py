"""docs/api.md §6.26: organisations, their members and roles, and the one namespace of
handles that a human's and an organisation's share."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, handle_register, namespace, orgs, registration_accounts
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def make_org(who: flow.Human, handle: str = "oz-team", name: str = "OZ Team") -> dict[str, Any]:
    made = who.post("/orgs", {"handle": handle, "display_name": name})
    assert made.status_code == 201, made.text
    body: dict[str, Any] = made.json()
    return body


def delete_org(who: flow.Human, handle: str, confirm: str) -> Any:
    return who.client.request(
        "DELETE",
        f"/api/v1/orgs/{handle}",
        json={"confirm": confirm},
        headers={"X-CSRF-Token": who.csrf},
    )


def add_member(engine: Engine, org_id: str, human_id: str, role: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(t.org_member).values(
                org_id=org_id, human_id=human_id, role=role, joined_at=clock.now()
            )
        )


def team(
    make_client: ClientFactory, engine: Engine, owner: flow.Human
) -> tuple[dict[str, Any], dict[str, flow.Human]]:
    """An organisation of `owner` with an admin, a member and a second owner."""
    org = make_org(owner)
    people = {"owner": owner}
    for role in ("owner2", "admin", "member"):
        who = flow.human(make_client, engine, f"team-{role}")
        add_member(engine, org["id"], who.id, "owner" if role == "owner2" else role)
        people[role] = who
    return org, people


# --- creating and reading --------------------------------------------------------------------


def test_an_organisation_is_created_with_its_creator_as_first_owner(owner: flow.Human) -> None:
    org = make_org(owner)
    assert org["id"].startswith("org-")
    assert {k: org[k] for k in org if k not in ("id", "created_at")} == {
        "handle": "oz-team",
        "display_name": "OZ Team",
        "avatar_url": None,
        "aliases": [],
        "my_role": "owner",
        "members_create_projects": False,
        "public_page": "off",
    }
    assert owner.get("/orgs").json() == {"items": [org]}
    assert owner.get("/orgs/oz-team").json() == org
    [first] = owner.get("/orgs/oz-team/members").json()["items"]
    assert (first["id"], first["handle"], first["role"]) == (owner.id, "maintainer", "owner")


def test_a_handle_is_one_namespace_for_humans_and_organisations(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    cases = {
        "oz-team": "taken",  # another organisation's
        "maintainer": "taken",  # a human's
        "x": "invalid",  # too short
        "Upper": "invalid",
        sorted(namespace.DASHBOARD_WORDS)[0]: "reserved",
    }
    for handle, reason in cases.items():
        refused = owner.post("/orgs", {"handle": handle, "display_name": "Another"})
        assert refused.status_code == 400, (handle, refused.text)
        assert refused.json()["error"]["details"]["fields"] == {"handle": reason}, handle
    with migrated.begin() as conn:  # and a registration cannot take the organisation's
        assert registration_accounts.check_names(conn, "oz-team", "Someone") == {"handle": "taken"}
        assert registration_accounts.check_names(conn, "free-name", "Someone") == {}
    bad = owner.post("/orgs", {"handle": "fresh", "display_name": "bad\x07name"})
    assert bad.json()["error"]["details"]["fields"] == {"display_name": "invalid"}
    assert owner.post("/orgs", {"handle": "fresh"}).status_code == 400  # a field missing


def test_every_human_is_in_the_register_and_a_row_is_never_taken_twice(
    migrated: Engine, owner: flow.Human
) -> None:
    other = factory.human(migrated, "second")
    org = make_org(owner)
    with migrated.begin() as conn:
        rows = {
            r.handle: (r.kind, r.owner_id) for r in conn.execute(select(t.handle_register)).all()
        }
        assert rows["maintainer"] == ("human", owner.id)
        assert rows["second"] == ("human", other)
        assert rows["oz-team"] == ("org", org["id"])
        assert not handle_register.claim(conn, "oz-team", handle_register.HUMAN, "hum-impostor")
        assert conn.execute(select(t.handle_register.c.owner_id)).all()  # the transaction lives


def test_an_agent_has_no_organisation_and_a_stranger_sees_none(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner)
    refused = agent.get("/orgs")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    assert agent.post("/orgs", {"handle": "agents-org", "display_name": "No"}).status_code == 403
    make_org(owner)
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.get("/orgs").json() == {"items": []}
    nothing = stranger.get("/orgs/oz-team/members")
    unknown = stranger.get("/orgs/never-made/members")
    assert (nothing.status_code, nothing.json()) == (unknown.status_code, unknown.json())
    assert nothing.status_code == 404
    for call in (
        stranger.get("/orgs/oz-team"),
        stranger.patch("/orgs/oz-team", {"display_name": "Mine"}),
        delete_org(stranger, "oz-team", "oz-team"),
        stranger.delete(f"/orgs/oz-team/members/{owner.id}"),
    ):
        assert call.status_code == 404, call.text


def test_the_count_of_organisations_is_atomic_per_human(
    make_client: ClientFactory, migrated: Engine
) -> None:
    def client(**kw: object) -> Any:
        return make_client(max_orgs_per_human=2, **kw)

    who = flow.human(client, migrated)
    make_org(who, "first-org")
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda handle: who.post("/orgs", {"handle": handle, "display_name": handle}),
                ["second-org", "third-org"],
            )
        )
    assert sorted(r.status_code for r in results) == [201, 409]
    refused = next(r for r in results if r.status_code == 409)
    assert refused.json()["error"]["code"] == "org_limit"
    assert refused.json()["error"]["details"] == {"limit": 2, "count": 2}
    assert len(who.get("/orgs").json()["items"]) == 2


# --- changing --------------------------------------------------------------------------------


def test_only_an_owner_changes_the_settings_and_a_handle_cannot_yet(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, people = team(make_client, migrated, owner)
    for role in ("admin", "member"):
        denied = people[role].patch("/orgs/oz-team", {"display_name": "Mine"})
        assert (denied.status_code, denied.json()["error"]["details"]) == (
            403,
            {"reason": "org_role"},
        )
    changed = people["owner2"].patch(
        "/orgs/oz-team",
        {"display_name": "OZ", "members_create_projects": True, "public_page": "on"},
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["display_name"], changed.json()["members_create_projects"]) == (
        "OZ",
        True,
    )
    assert changed.json()["public_page"] == "on"
    assert changed.json()["my_role"] == "owner"
    assert people["member"].get("/orgs/oz-team").json()["my_role"] == "member"
    for body in ({"public_page": "maybe"}, {"display_name": ""}, {"handle": "renamed"}):
        refused = owner.patch("/orgs/oz-team", body)
        assert refused.status_code == 400, body
    assert owner.get("/orgs/oz-team").json()["handle"] == org["handle"]


def test_the_roles_decide_who_changes_whom(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, people = team(make_client, migrated, owner)
    url = "/orgs/oz-team/members"
    ids = {k: v.id for k, v in people.items()}
    listed = owner.get(url).json()["items"]
    assert [m["role"] for m in listed] == ["owner", "owner", "admin", "member"]
    admin, member = people["admin"], people["member"]
    # an admin moves a member up to admin and back, never an owner, never to owner
    assert admin.patch(f"{url}/{ids['member']}", {"role": "admin"}).json()["role"] == "admin"
    assert admin.patch(f"{url}/{ids['member']}", {"role": "member"}).json()["role"] == "member"
    for body, who in (
        ({"role": "owner"}, "member"),
        ({"role": "member"}, "owner2"),
    ):
        denied = admin.patch(f"{url}/{ids[who]}", body)
        assert denied.status_code == 403
        assert denied.json()["error"]["details"] == {"reason": "org_role"}
    assert member.patch(f"{url}/{ids['member']}", {"role": "owner"}).status_code == 403
    assert owner.patch(f"{url}/{ids['member']}", {"role": "bogus"}).status_code == 400
    assert owner.patch(f"{url}/hum-nobody", {"role": "member"}).status_code == 404
    # an owner changes any role, and an owner demoted is no owner any more
    assert owner.patch(f"{url}/{ids['owner2']}", {"role": "admin"}).json()["role"] == "admin"
    assert people["owner2"].patch("/orgs/oz-team", {"display_name": "No"}).status_code == 403
    assert org["id"] == owner.get("/orgs/oz-team").json()["id"]


def test_the_last_owner_stays(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org, people = team(make_client, migrated, owner)
    url = "/orgs/oz-team/members"
    assert owner.patch(f"{url}/{people['owner2'].id}", {"role": "member"}).status_code == 200
    for refused in (
        owner.patch(f"{url}/{owner.id}", {"role": "admin"}),
        owner.delete(f"{url}/{owner.id}"),
    ):
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "org_last_owner"
        assert refused.json()["error"]["details"] == {"orgs": ["oz-team"]}
    # promoted again, the owner may leave
    assert owner.patch(f"{url}/{people['owner2'].id}", {"role": "owner"}).status_code == 200
    assert owner.delete(f"{url}/{owner.id}").status_code == 204
    assert owner.get("/orgs/oz-team").status_code == 404
    assert people["owner2"].get("/orgs/oz-team").json()["my_role"] == "owner"
    assert org["id"]


def test_two_owners_who_demote_each_other_at_once_leave_one(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    url = "/orgs/oz-team/members"
    assert owner.patch(f"{url}/{people['admin'].id}", {"role": "member"}).status_code == 200
    other = people["owner2"]
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda call: call(),
                [
                    lambda: owner.patch(f"{url}/{other.id}", {"role": "admin"}),
                    lambda: other.patch(f"{url}/{owner.id}", {"role": "admin"}),
                ],
            )
        )
    # The second call runs under the lock, after the first: its caller is no owner any more.
    assert sorted(r.status_code for r in results) == [200, 403]
    survivor = owner if results[0].status_code == 200 else other
    assert survivor.get("/orgs/oz-team").json()["my_role"] == "owner"


def test_members_leave_and_are_removed_by_those_the_roles_allow(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    url = "/orgs/oz-team/members"
    ids = {k: v.id for k, v in people.items()}
    assert people["member"].delete(f"{url}/{ids['admin']}").status_code == 403
    assert people["admin"].delete(f"{url}/{ids['owner2']}").status_code == 403
    assert people["admin"].delete(f"{url}/{ids['member']}").status_code == 204
    assert people["member"].get("/orgs/oz-team").status_code == 404  # no longer a member
    assert people["admin"].delete(f"{url}/{ids['member']}").status_code == 404
    assert people["admin"].delete(f"{url}/{ids['admin']}").status_code == 204  # leaving
    assert owner.delete(f"{url}/{ids['owner2']}").status_code == 204
    assert [m["id"] for m in owner.get(url).json()["items"]] == [owner.id]


# --- deleting --------------------------------------------------------------------------------


def test_deleting_an_organisation_keeps_its_handle_taken(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    org_id = owner.get("/orgs/oz-team").json()["id"]
    with migrated.begin() as conn:  # an open invitation, to see it withdrawn
        conn.execute(
            insert(t.org_invitation).values(
                id="oiv-open",
                org_id=org_id,
                handle="somebody",
                role="member",
                invited_by=owner.id,
                created_at=clock.now(),
                expires_at=clock.now(),
                live=True,
            )
        )
    assert delete_org(people["admin"], "oz-team", "oz-team").status_code == 403
    wrong = delete_org(owner, "oz-team", "other")
    assert wrong.status_code == 400
    assert wrong.json()["error"]["details"]["fields"] == {"confirm": "mismatch"}
    gone = delete_org(owner, "oz-team", "oz-team")
    assert gone.status_code == 204, gone.text
    for who in people.values():
        assert who.get("/orgs/oz-team").status_code == 404
        assert who.get("/orgs").json() == {"items": []}
    with migrated.begin() as conn:
        row = conn.execute(select(t.org)).one()
        assert row.deleted_at is not None and row.handle == "oz-team"
        assert conn.execute(select(t.org_member)).all() == []
        invitation = conn.execute(select(t.org_invitation)).one()
        assert (invitation.live, invitation.closed_by) == (None, "org_deleted")
    again = owner.post("/orgs", {"handle": "oz-team", "display_name": "Back"})
    assert again.json()["error"]["details"]["fields"] == {"handle": "taken"}


def test_a_setting_that_is_sent_is_a_value(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    for body, field in (
        ({"display_name": None}, "display_name"),
        ({"members_create_projects": None}, "members_create_projects"),
        ({"public_page": None}, "public_page"),
    ):
        refused = owner.patch("/orgs/oz-team", body)
        assert refused.status_code == 400, (body, refused.text)
        assert field in refused.json()["error"]["details"]["fields"], body
    for wrong in ("off", 0, "true"):
        assert owner.patch("/orgs/oz-team", {"members_create_projects": wrong}).status_code == 400
    assert owner.patch("/orgs/oz-team", {}).status_code == 200  # nothing sent, nothing changed
    assert owner.get("/orgs/oz-team").json()["members_create_projects"] is False


def test_a_role_lost_while_waiting_for_the_lock_is_the_roles_at_the_lock(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    """The caller's role is read again under the organisation's lock: an owner demoted by
    a change that ran first changes nothing, however long it waited (§6.26)."""
    _, people = team(make_client, migrated, owner)
    second = people["owner2"]
    org_id = owner.get("/orgs/oz-team").json()["id"]
    with migrated.begin() as conn:  # the demotion has been decided and not yet committed
        orgs.lock(conn, org_id)
        results: list[Any] = []

        def second_changes() -> None:
            results.append(second.patch("/orgs/oz-team", {"display_name": "Second"}))

        thread = threading.Thread(target=second_changes)
        thread.start()
        thread.join(timeout=0.5)  # it waits for the lock when the database has row locks
        conn.execute(
            update(t.org_member).where(t.org_member.c.human_id == second.id).values(role="member")
        )
    thread.join(timeout=10)
    [answer] = results
    assert answer.status_code in (200, 403), answer.text
    if answer.status_code == 200:  # SQLite serialised the writes the other way round
        assert owner.get("/orgs/oz-team").json()["display_name"] == "Second"
    else:
        assert answer.json()["error"]["details"] == {"reason": "org_role"}
        assert owner.get("/orgs/oz-team").json()["display_name"] == "OZ Team"
