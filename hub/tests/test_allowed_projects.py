"""docs/api.md §6.3 "Allowed projects": the owner decides in advance where an agent may go
(tsk-0z357yddshfx)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_join_pickup import exchange, pick_up, setup  # noqa: F401  (the fixture)
from tests.test_placements import Setup, place

PROJECT = "/projects/maintainer/maity"
FULL = "maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def allow(who: flow.Human, agent_id: str, allowed: Any) -> Any:
    return who.patch(f"/agents/{agent_id}", {"allowed_projects": allowed})


def join(who: flow.Human, agent_id: str, **body: Any) -> Any:
    return who.post(f"{PROJECT}/joins", {"agent": {"id": agent_id}, **body})


def _room(engine: Engine, agent_id: str) -> None:
    """Room for more instances: what is tested is the list, not the team's quota."""
    with engine.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == agent_id).values(max_instances=9)
        )


def _fields(response: Any) -> dict[str, Any]:
    fields: dict[str, Any] = response.json()["error"]["details"]["fields"]
    return fields


# --- the list ---------------------------------------------------------------------------------


def test_the_list_defaults_to_any_project_and_the_owner_sets_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert owner.get(f"/agents/{agent.id}").json()["allowed_projects"] is None
    done = allow(owner, agent.id, ["maintainer/maity", "acme/not-yet-made"])
    assert done.status_code == 200, done.text
    assert done.json()["allowed_projects"] == ["maintainer/maity", "acme/not-yet-made"]
    assert owner.get("/agents").json()["items"][0]["allowed_projects"] == [
        "maintainer/maity",
        "acme/not-yet-made",
    ]
    assert allow(owner, agent.id, []).json()["allowed_projects"] == []  # allows nothing
    assert allow(owner, agent.id, None).json()["allowed_projects"] is None  # any project


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        (["x/" + "a" * 300], "format"),
        (["no-slash"], "format"),
        (["Upper/Case"], "format"),
        (["a/b/c"], "format"),
        ([1], "format"),
        ("maintainer/maity", "format"),
        (["acme/one", "acme/one"], "duplicate"),
        ([f"acme/p{n}" for n in range(201)], "too_many"),
    ],
)
def test_a_bad_list_is_invalid(
    owner: flow.Human, make_client: ClientFactory, value: Any, problem: str
) -> None:
    agent = flow.agent(make_client, owner)
    refused = allow(owner, agent.id, value)
    assert refused.status_code == 400, refused.text
    assert _fields(refused) == {"allowed_projects": problem}
    assert owner.get(f"/agents/{agent.id}").json()["allowed_projects"] is None


def test_two_hundred_names_are_fine(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    assert allow(owner, agent.id, [f"acme/p{n:03}" for n in range(200)]).status_code == 200


def test_an_agent_never_sets_it(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    response = agent.client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"allowed_projects": []},
        headers=agent.auth | agent.key(),
    )
    assert response.status_code in (401, 403), response.text
    assert owner.get(f"/agents/{agent.id}").json()["allowed_projects"] is None


# --- no membership and no instance outside the list ---------------------------------------------


def test_a_join_for_a_project_not_on_the_list_is_forbidden(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _room(migrated, agent.id)
    allow(owner, agent.id, ["acme/elsewhere"])
    for body in ({"new_instance": True}, {"replaces": agent.instance}):
        refused = join(owner, agent.id, **body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "forbidden"
        assert refused.json()["error"]["details"]["reason"] == "project_not_allowed"
    allow(owner, agent.id, [FULL])
    assert join(owner, agent.id, new_instance=True).status_code == 201


def test_a_first_join_of_a_profile_not_allowed_here_is_forbidden(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.project(owner, "other")  # noqa: F841
    mine = flow.agent(make_client, owner, "other")
    allow(owner, mine.id, ["maintainer/other"])
    refused = join(owner, mine.id)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "project_not_allowed"
    allow(owner, mine.id, ["maintainer/other", FULL])
    assert join(owner, mine.id).status_code == 201


def test_a_join_handed_out_before_the_list_changed_is_void_at_the_exchange(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _room(migrated, agent.id)
    handed = join(owner, agent.id, new_instance=True)
    assert handed.status_code == 201, handed.text
    allow(owner, agent.id, ["acme/elsewhere"])
    voided = flow.exchange(make_client(), handed.json())
    assert voided.status_code == 404, voided.text  # as for any join that no longer holds
    allow(owner, agent.id, None)
    again = join(owner, agent.id, new_instance=True)
    assert flow.exchange(make_client(), again.json()).status_code == 201


def test_a_list_that_no_longer_names_the_project_ends_no_membership(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    allow(owner, agent.id, ["acme/elsewhere"])
    member = owner.get(f"{PROJECT}/members/{agent.id}")
    assert member.status_code == 200 and member.json()["role"]  # still a member
    with migrated.connect() as conn:
        active = conn.execute(
            select(t.membership.c.active).where(t.membership.c.agent_id == agent.id)
        ).scalar_one()
    assert active is True


# --- placements and pickups -------------------------------------------------------------------


def test_a_placement_for_a_profile_not_allowed_here_is_refused(setup: Setup) -> None:  # noqa: F811
    allow(setup.owner, setup.agent.id, ["acme/elsewhere"])
    refused = place(setup)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "project_not_allowed"
    allow(setup.owner, setup.agent.id, [FULL])
    assert place(setup).status_code == 201


def test_a_pickup_is_refused_once_the_list_no_longer_names_the_project(
    setup: Setup, make_client: ClientFactory  # noqa: F811
) -> None:
    created = place(setup)
    assert created.status_code == 201, created.text
    placement = created.json()
    allow(setup.owner, setup.agent.id, ["acme/elsewhere"])
    refused = pick_up(setup, placement)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "pickup_not_allowed"
    assert refused.json()["error"]["details"] == {"why": "project_not_allowed"}
    allow(setup.owner, setup.agent.id, None)
    assert pick_up(setup, placement).status_code == 201


def test_a_rejoin_is_refused_the_same_way(
    setup: Setup, make_client: ClientFactory  # noqa: F811
) -> None:
    created = place(setup)
    placement = created.json()
    picked = pick_up(setup, placement)
    joined = exchange(make_client(), picked.json())
    assert joined.status_code == 201, joined.text
    allow(setup.owner, setup.agent.id, [])
    with setup.engine.begin() as conn:  # a rejoin: the credential is gone, the placement stays
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == placement["id"])
            .values(rejoin=True, generation=placement["generation"] + 1)
        )
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == joined.headers["Maity-Credential-Id"])
            .values(revoked_at=t.credential.c.created_at)
        )
    refused = pick_up(setup, placement, generation=placement["generation"] + 1)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"] == {"why": "project_not_allowed"}


# --- how a project is matched ---------------------------------------------------------------------


def test_a_rename_of_the_project_or_of_its_owner_drops_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _room(migrated, agent.id)
    allow(owner, agent.id, [FULL])
    assert owner.patch(PROJECT, {"slug": "maity-hub"}).status_code == 200
    assert join(owner, agent.id, new_instance=True).status_code == 201  # by its alias
    renamed = owner.patch("/me", {"handle": "oliver"})
    assert renamed.status_code == 200, renamed.text
    assert join(owner, agent.id, new_instance=True).status_code == 201  # by the owner's alias
    allow(owner, agent.id, ["oliver/maity-hub"])  # the current full name as well
    assert join(owner, agent.id, new_instance=True).status_code == 201
    allow(owner, agent.id, ["oliver/other"])
    refused = join(owner, agent.id, new_instance=True)
    assert refused.status_code == 403


# --- what the dashboard offers --------------------------------------------------------------------


def test_the_list_of_agents_can_be_narrowed_to_those_a_project_is_allowed_for(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    anywhere = flow.agent(make_client, owner)
    here = flow.agent(make_client, owner)
    elsewhere = flow.agent(make_client, owner)
    nowhere = flow.agent(make_client, owner)
    allow(owner, here.id, [FULL])
    allow(owner, elsewhere.id, ["acme/elsewhere"])
    allow(owner, nowhere.id, [])

    def offered(name: str) -> set[str]:
        got = owner.get(f"/agents?allowed_in={name}")
        assert got.status_code == 200, got.text
        return {a["id"] for a in got.json()["items"]}

    assert offered(FULL) == {anywhere.id, here.id}
    assert offered("acme/elsewhere") == {anywhere.id, elsewhere.id}  # a project not yet made
    assert offered("acme/unknown") == {anywhere.id}
    assert {a["id"] for a in owner.get("/agents").json()["items"]} == {
        anywhere.id,
        here.id,
        elsewhere.id,
        nowhere.id,
    }


def test_allowed_in_is_a_full_name_and_a_tombstone_is_never_listed(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    gone = flow.agent(make_client, owner)
    assert owner.delete(f"/agents/{gone.id}?cascade=true").status_code == 200
    for bad in ("nope", "A/B", "a/b/c", ""):
        refused = owner.get(f"/agents?allowed_in={bad}")
        assert refused.status_code == 400, (bad, refused.text)
        assert _fields(refused) == {"allowed_in": "format"}
    assert gone.id not in {a["id"] for a in owner.get(f"/agents?allowed_in={FULL}").json()["items"]}
