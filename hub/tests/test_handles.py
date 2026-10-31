"""Renameable handles with aliases (docs/api.md §6.24)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_mentions import second_owners_agent


def _fields(response: Any) -> dict[str, str]:
    result: dict[str, str] = response.json()["error"]["details"]["fields"]
    return result


def test_a_human_renames_and_keeps_the_old_handle_as_an_alias(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    assert owner.get("/me").json()["member"]["aliases"] == []
    response = owner.patch("/me", {"handle": "boss"})
    assert response.status_code == 200, response.text
    member = response.json()["member"]
    assert (member["handle"], member["aliases"]) == ("boss", ["maintainer"])
    # A rename to the same handle is a no-op: 200, nothing changes.
    again = owner.patch("/me", {"handle": "boss"})
    assert again.status_code == 200 and again.json()["member"]["aliases"] == ["maintainer"]
    # Taking an own alias back leaves the list and gives up the current handle.
    back = owner.patch("/me", {"handle": "maintainer"}).json()["member"]
    assert (back["handle"], back["aliases"]) == ("maintainer", ["boss"])


def test_a_handle_or_alias_of_another_is_taken(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    factory.human(migrated, "other")
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    taken = owner.patch("/me", {"handle": "other"})
    assert taken.status_code == 400 and _fields(taken) == {"handle": "taken"}
    # Nobody else can take the alias the maintainer gave up.
    third = flow.human(make_client, migrated, "third")
    assert _fields(third.patch("/me", {"handle": "maintainer"})) == {"handle": "taken"}
    assert _fields(owner.patch("/me", {"handle": "Bad_Handle"})) == {"handle": "format"}
    assert _fields(owner.patch("/me", {"handle": "account"})) == {"handle": "reserved"}


def test_the_ninth_alias_and_the_fourth_rename_are_refused(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    for i in range(3):
        assert owner.patch("/me", {"handle": f"name-{i}"}).status_code == 200
    limited = owner.patch("/me", {"handle": "name-3"})
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
    # Fill the alias list straight in the database, to meet the cap without three days of renames.
    with migrated.begin() as conn:
        from maity_hub import clock

        conn.execute(t.handle_change.delete())
        for i in range(6):
            conn.execute(
                t.handle_alias.insert().values(
                    human_id=owner.id, scope="human", handle=f"old-{i}", created_at=clock.now()
                )
            )
    full = owner.patch("/me", {"handle": "name-9"})
    assert full.status_code == 409 and full.json()["error"]["code"] == "alias_limit"
    assert full.json()["error"]["details"]["limit"] == 8
    # Taking an alias back is still possible at the cap.
    assert owner.patch("/me", {"handle": "old-3"}).status_code == 200


def test_an_owner_renames_an_agent_and_an_agent_cannot(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, agent={"handle": "bee", "display_name": "Bee"})
    forbidden = agent.patch("/me", {"handle": "wasp"})
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["details"]["reason"] == "humans_only"
    response = owner.patch(f"/agents/{agent.id}", {"handle": "wasp"})
    assert response.status_code == 200, response.text
    assert response.json()["aliases"] == ["bee"] and response.json()["name"] == "maintainer/wasp"
    other = owner.post("/agents", {"handle": "bee", "display_name": "Another"})
    assert other.status_code == 400 and _fields(other) == {"handle": "taken"}
    mine = agent.get("/me").json()["member"]
    assert (mine["handle"], mine["aliases"]) == ("wasp", ["bee"])
    # Another owner may use the handle: the scope is one owner's profiles.
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.post("/agents", {"handle": "bee", "display_name": "Mine"}).status_code == 201
    assert stranger.patch(f"/agents/{agent.id}", {"handle": "x1"}).status_code == 404


def test_a_rename_is_an_event_and_a_ticker_item(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, agent={"handle": "bee", "display_name": "Bee"})
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    with migrated.connect() as conn:
        rows = conn.execute(select(t.event.c.kind, t.event.c.payload).order_by(t.event.c.seq)).all()
    updates = [
        r.payload["changed"] for r in rows if r.kind == "member_updated" and "changed" in r.payload
    ]
    assert ["handle"] in updates and ["name"] in updates
    texts = [
        r.payload["text"] for r in rows if r.kind == "ticker" and r.payload["type"] == "rename"
    ]
    assert "maintainer is now boss" in texts and "maintainer/bee is now boss/bee" in texts
    assert agent.id


# --- resolution (§6.24, §8.6, §6.25) -------------------------------------------------------


def _say(owner: flow.Human, body: str) -> Any:
    return owner.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": body},
    )


def test_a_mention_of_an_alias_reaches_the_member_with_the_current_handle(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, agent={"handle": "bee", "display_name": "Bee"})
    assert owner.patch(f"/agents/{agent.id}", {"handle": "wasp"}).status_code == 200
    sent = _say(owner, "ping @bee and @maintainer/bee")
    assert sent.status_code == 201, sent.text
    assert [
        (m["member_id"], m["handle"], m["name"]) for m in sent.json()["payload"]["mentions"]
    ] == [(agent.id, "wasp", "maintainer/wasp")] * 2
    # After the owner's rename either owner part names the same profile.
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    again = _say(owner, "@maintainer/wasp and @boss/bee")
    assert [m["member_id"] for m in again.json()["payload"]["mentions"]] == [agent.id] * 2


def test_an_alias_that_is_another_members_handle_is_ambiguous(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    old = flow.agent(make_client, owner, agent={"handle": "builder", "display_name": "Old"})
    assert owner.patch(f"/agents/{old.id}", {"handle": "builder-2"}).status_code == 200
    # Another owner's agent in the project now carries the handle the first one gave up.
    second_owners_agent(migrated, "anna", "builder")
    refused = _say(owner, "@builder?")
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"body": "ambiguous_mention"}
    assert refused.json()["error"]["details"]["mentions"] == {
        "builder": ["anna/builder", "maintainer/builder-2"]
    }
    # The long form says which one is meant, by the alias as much as by the current handle.
    assert _say(owner, "@maintainer/builder").status_code == 201
    assert _say(owner, "@anna/builder").status_code == 201


def test_a_human_whose_current_handle_it_is_comes_first_but_not_through_an_alias(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    second_owners_agent(migrated, "anna", "maintainer")
    first = _say(owner, "@maintainer")
    assert first.status_code == 201
    assert [m["member_id"] for m in first.json()["payload"]["mentions"]] == [owner.id]
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    through_alias = _say(owner, "@maintainer")  # an alias of the human and the agent's handle
    assert through_alias.status_code == 400
    assert through_alias.json()["error"]["details"]["mentions"] == {
        "maintainer": ["anna/maintainer", "boss"]
    }


def test_login_and_the_owner_part_of_a_project_address_follow_aliases(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    # The old handle still opens the project, on every route under it.
    for path in ("", "/members", "/tasks", "/rules"):
        old = owner.get(f"/projects/maintainer/maity{path}")
        new = owner.get(f"/projects/boss/maity{path}")
        assert old.status_code == new.status_code == 200, (path, old.text)
    # The public badge keeps its old address as well.
    policy = {"policy": {"badge": "members"}, "reason": "show"}
    assert owner.patch("/projects/boss/maity", policy).status_code == 200
    public = make_client()
    for prefix in ("/badge/{}/maity.svg",):
        assert public.get(prefix.format("boss")).status_code == 200
        assert public.get(prefix.format("maintainer")).status_code == 200, prefix
    # And signs in: a handle, or an alias of it.
    for name in ("boss", "maintainer"):
        client = make_client()
        login = client.post(
            "/api/v1/auth/login", json={"handle": name, "password": factory.PASSWORD}
        )
        assert login.status_code == 200 and login.json()["member"]["handle"] == "boss"
    # A new project cannot take a slug under the alias either: it is the same namespace.
    clash = owner.post("/projects", {"slug": "maity", "name": "Again"})
    assert clash.status_code in (400, 409)


# --- every path that gives a handle (§6.24) ------------------------------------------------


def test_a_join_a_registration_and_the_operator_refuse_a_taken_handle_or_alias(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.registration_accounts import check_names

    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, agent={"handle": "bee", "display_name": "Bee"})
    assert owner.patch(f"/agents/{agent.id}", {"handle": "wasp"}).status_code == 200
    joined = owner.post(
        "/projects/maintainer/maity/joins", {"agent": {"handle": "bee", "display_name": "Again"}}
    )
    assert joined.status_code == 400 and _fields(joined) == {"handle": "taken"}
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    with migrated.connect() as conn:  # registration: the human's old handle is an alias now
        assert check_names(conn, "maintainer", "Someone") == {"handle": "taken"}
        assert check_names(conn, "boss", "Someone") == {"handle": "taken"}
        assert check_names(conn, "fresh-one", "Someone") == {}


def test_a_deleted_profile_frees_its_handle_and_its_aliases_for_its_owner(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    profile = owner.post("/agents", {"handle": "bee", "display_name": "Bee"}).json()
    assert owner.patch(f"/agents/{profile['id']}", {"handle": "wasp"}).status_code == 200
    assert _fields(owner.post("/agents", {"handle": "bee", "display_name": "x"})) == {
        "handle": "taken"
    }
    assert owner.delete(f"/agents/{profile['id']}").status_code in (200, 204)
    for handle in ("bee", "wasp"):
        assert owner.post("/agents", {"handle": handle, "display_name": "New"}).status_code == 201


def test_a_rename_of_a_profile_deleted_meanwhile_is_not_found(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import events, handles
    from maity_hub.errors import ApiError

    owner = flow.human(make_client, migrated)
    profile = owner.post("/agents", {"handle": "bee", "display_name": "Bee"}).json()
    with migrated.begin() as conn:  # the delete, as it stands once it has the profile's lock
        conn.execute(
            t.agent_profile.update()
            .where(t.agent_profile.c.id == profile["id"])
            .values(deleted_at=clock.now(), live=None)
        )
        owner_id = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == profile["id"])
        ).scalar_one()
    with events.transaction(migrated) as conn:
        try:
            handles.rename(conn, profile["id"], owner_id, "wasp")
        except ApiError as error:
            assert error.status == 404 and error.code == "not_found"
        else:
            raise AssertionError("a deleted profile was renamed")
    assert owner.post("/agents", {"handle": "wasp", "display_name": "New"}).status_code == 201


def test_two_renames_to_one_handle_leave_one_winner(
    make_client: ClientFactory, migrated: Engine
) -> None:
    import threading

    from maity_hub import events, handles
    from maity_hub.errors import ApiError

    first = factory.human(migrated, "first")
    second = factory.human(migrated, "second")
    outcomes: list[str] = []
    ready = threading.Barrier(2)

    def go(human_id: str) -> None:
        ready.wait()
        try:
            with events.transaction(migrated) as conn:
                handles.rename(conn, human_id, None, "wanted")
            outcomes.append("renamed")
        except ApiError as error:
            outcomes.append(error.details["fields"]["handle"])

    threads = [threading.Thread(target=go, args=(i,)) for i in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["renamed", "taken"]
    with migrated.connect() as conn:
        holders = conn.execute(select(t.human.c.handle).where(t.human.c.handle == "wanted")).all()
        assert len(holders) == 1


def test_the_admin_search_finds_an_account_by_an_alias_and_login_is_limited_per_account(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.routes import auth

    admin = flow.human(make_client, migrated)  # the earliest human: the instance admin
    assert admin.patch("/me", {"handle": "boss"}).status_code == 200
    found = admin.get("/admin/users", params={"q": "maintainer"})
    assert [u["handle"] for u in found.json()["items"]] == ["boss"]
    auth.LOGIN_BY_HANDLE.reset()
    wrong = make_client()
    codes = []
    for name in ("boss", "maintainer") * 5:
        codes.append(
            wrong.post("/api/v1/auth/login", json={"handle": name, "password": "wrong"}).status_code
        )
    assert 429 in codes  # alias and handle share one account's limit
    auth.LOGIN_BY_HANDLE.reset()


def test_an_agent_naming_a_handle_is_forbidden_even_when_it_is_null_and_a_human_needs_a_field(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, agent={"handle": "bee", "display_name": "Bee"})
    for value in ("wasp", None):
        refused = agent.patch("/me", {"handle": value})
        assert refused.status_code == 403
        assert refused.json()["error"]["details"]["reason"] == "humans_only"
    nothing = owner.patch("/me", {})
    assert nothing.status_code == 400
    assert _fields(nothing) == {"handle": "required", "meat_proxy": "required"}


def test_the_register_follows_a_rename_and_organisations_share_the_namespace(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    org = owner.post("/orgs", {"handle": "oz-team", "display_name": "Team"})
    assert org.status_code == 201, org.text
    # A human cannot take an organisation's handle, as a rename or as a first handle.
    assert _fields(owner.patch("/me", {"handle": "oz-team"})) == {"handle": "taken"}
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    with migrated.connect() as conn:
        register = dict(
            conn.execute(select(t.handle_register.c.owner_id, t.handle_register.c.handle)).all()
        )
    assert register[owner.id] == "boss"
    # The handle given up is an alias: an organisation cannot be created under it either.
    clash = owner.post("/orgs", {"handle": "maintainer", "display_name": "Old"})
    assert clash.status_code == 400 and _fields(clash) == {"handle": "taken"}
    assert _fields(owner.patch("/me", {"handle": "admin"})) == {"handle": "reserved"}


def test_lookups_by_handle_follow_aliases_where_a_person_is_named(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import org_invitations, reports
    from maity_hub.errors import ApiError

    owner = flow.human(make_client, migrated)
    profile = owner.post("/agents", {"handle": "bee", "display_name": "Bee"}).json()
    assert owner.patch(f"/agents/{profile['id']}", {"handle": "wasp"}).status_code == 200
    assert owner.patch("/me", {"handle": "boss"}).status_code == 200
    with migrated.begin() as conn:
        # An invitation by the handle given up still finds the account (§6.24).
        assert org_invitations._invitee(conn, "maintainer") == owner.id
        assert org_invitations._invitee(conn, "boss") == owner.id
        # A global name takes the owner's alias and the profile's alias alike.
        assert reports._agent_by_name(conn, "maintainer/bee") == profile["id"]
        assert reports._agent_by_name(conn, "boss/wasp") == profile["id"]
        with pytest.raises(ApiError):
            reports._agent_by_name(conn, "nobody/wasp")
    # A project may be created under the namespace of one's own alias.
    created = owner.post("/projects", {"slug": "shop", "name": "Shop", "owner": "maintainer"})
    assert created.status_code == 201, created.text
    assert created.json()["full_name"] == "boss/shop"


def test_a_null_handle_renames_nothing(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    profile = owner.post("/agents", {"handle": "bee", "display_name": "Bee"}).json()
    refused = owner.patch(f"/agents/{profile['id']}", {"handle": None})
    assert refused.status_code == 400 and _fields(refused) == {"handle": "required"}


def test_a_tombstone_keeps_listing_its_aliases_though_they_are_free(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    profile = owner.post("/agents", {"handle": "bee", "display_name": "Bee"}).json()
    assert owner.patch(f"/agents/{profile['id']}", {"handle": "wasp"}).status_code == 200
    assert owner.delete(f"/agents/{profile['id']}").status_code in (200, 204)
    tomb = owner.get(f"/agents/{profile['id']}")
    assert tomb.status_code == 200 and tomb.json()["aliases"] == ["bee"]
    # The names are free for a new profile of the owner all the same (§6.3).
    assert owner.post("/agents", {"handle": "bee", "display_name": "New"}).status_code == 201
