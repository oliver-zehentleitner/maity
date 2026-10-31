"""docs/api.md §6.25: a project's rename and transfer, its aliases, and the namespace owner
who stays an owner."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, namespace
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


@pytest.fixture
def anna(make_client: ClientFactory, migrated: Engine, owner: flow.Human) -> flow.Human:
    """A second owner of maintainer/maity, in a namespace of her own."""
    human = flow.human(make_client, migrated, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "owner", human_id=human.id)
    return human


def rename(who: flow.Human, name: str, slug: str) -> Any:
    return who.patch(f"/projects/{name}", {"slug": slug})


def kinds(who: flow.Human, name: str, kind: str) -> list[dict[str, Any]]:
    items = who.get(f"/projects/{name}/events?after=0").json()["items"]
    return [e for e in items if e["kind"] == kind]


def error(response: Any) -> tuple[int, str, dict[str, Any]]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["details"]


# --- rename -------------------------------------------------------------------------------


def test_a_rename_keeps_the_old_name_as_an_alias(owner: flow.Human) -> None:
    renamed = rename(owner, "maintainer/maity", "maity-hub")
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert (body["full_name"], body["aliases"]) == ("maintainer/maity-hub", ["maintainer/maity"])
    # The old name still reaches the project, and answers with the current name.
    assert owner.get("/projects/maintainer/maity").json()["full_name"] == "maintainer/maity-hub"
    [updated] = kinds(owner, "maintainer/maity-hub", "project_updated")
    assert updated["payload"]["fields"] == {
        "slug": "maity-hub",
        "full_name": "maintainer/maity-hub",
    }
    [item] = kinds(owner, "maintainer/maity-hub", "ticker")
    assert item["payload"]["type"] == "rename"
    assert item["payload"]["text"] == "maintainer/maity is now maintainer/maity-hub"
    assert item["audience"] == ["all"]


def test_the_same_slug_is_no_change(owner: flow.Human) -> None:
    assert rename(owner, "maintainer/maity", "maity").json()["aliases"] == []
    assert kinds(owner, "maintainer/maity", "ticker") == []


def test_only_a_human_owner_renames(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    refused = agent.patch("/projects/maintainer/maity", {"slug": "other"})
    assert error(refused) == (403, "forbidden", {"reason": "humans_only"})
    admin = flow.human(make_client, migrated, "admin-human")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=admin.id)
    assert rename(admin, "maintainer/maity", "other").status_code == 403


def test_a_rename_needs_a_free_slug_that_is_no_route_word(owner: flow.Human) -> None:
    flow.project(owner, "other")
    taken = rename(owner, "maintainer/maity", "other")
    assert error(taken) == (400, "invalid", {"fields": {"slug": "taken"}})
    reserved = rename(owner, "maintainer/maity", "tasks")
    assert error(reserved) == (400, "invalid", {"fields": {"slug": "reserved"}})
    # Another project's alias is taken too: an old link never leads elsewhere.
    assert rename(owner, "maintainer/other", "other-two").status_code == 200
    again = rename(owner, "maintainer/maity", "other")
    assert error(again) == (400, "invalid", {"fields": {"slug": "taken"}})


def test_a_project_takes_its_own_alias_back(owner: flow.Human) -> None:
    rename(owner, "maintainer/maity", "maity-hub")
    back = rename(owner, "maintainer/maity-hub", "maity")
    assert back.status_code == 200, back.text
    assert (back.json()["full_name"], back.json()["aliases"]) == (
        "maintainer/maity",
        ["maintainer/maity-hub"],
    )


def test_three_changes_a_day(owner: flow.Human) -> None:
    for n, slug in enumerate(("one", "two", "three")):
        name = "maintainer/maity" if n == 0 else f"maintainer/{('one', 'two')[n - 1]}"
        assert rename(owner, name, slug).status_code == 200
    fourth = rename(owner, "maintainer/three", "four")
    assert fourth.status_code == 429 and int(fourth.headers["Retry-After"]) > 0
    assert owner.get("/projects/maintainer/three").json()["slug"] == "three"


def test_at_most_eight_aliases(owner: flow.Human, migrated: Engine) -> None:
    with migrated.begin() as conn:
        project = conn.execute(select(t.project)).one()
        for n in range(8):
            conn.execute(
                insert(t.project_alias).values(
                    project_id=project.id,
                    **namespace.owner_values(project.owner_id),
                    slug=f"old-{n}",
                    created_at=clock.now(),
                )
            )
    refused = rename(owner, "maintainer/maity", "maity-hub")
    status, code, details = error(refused)
    assert (status, code, details["limit"], len(details["aliases"])) == (
        409,
        "alias_limit",
        8,
        8,
    )
    # Taking an alias back adds none, so it stays possible.
    assert rename(owner, "maintainer/maity", "old-3").status_code == 200


# --- transfer -----------------------------------------------------------------------------


def transfer(who: flow.Human, to: str, name: str = "maintainer/maity") -> Any:
    return who.post(f"/projects/{name}/transfer", {"to": to})


def answer(who: flow.Human, name: str, request_id: str, reply: str = "go") -> Any:
    return who.post(f"/projects/{name}/requests/{request_id}/answer", {"reply_id": reply})


def status_of(who: flow.Human, name: str, request_id: str) -> str:
    return str(who.get(f"/projects/{name}/requests/{request_id}").json()["status"])


def test_a_transfer_moves_on_the_receivers_go(owner: flow.Human, anna: flow.Human) -> None:
    filed = transfer(owner, anna.id)
    assert filed.status_code == 202, filed.text
    request = filed.json()
    assert (request["class"], request["to"]) == ("consent", anna.id)
    # Only the receiver answers: nothing moves into a namespace without its owner's word.
    assert answer(owner, "maintainer/maity", request["id"]).status_code == 403
    done = answer(anna, "maintainer/maity", request["id"])
    assert done.status_code == 200, done.text
    body = anna.get("/projects/anna/maity").json()
    assert (body["owner"], body["aliases"]) == (
        {"id": anna.id, "handle": "anna"},
        ["maintainer/maity"],
    )
    assert owner.get("/projects/maintainer/maity").json()["full_name"] == "anna/maity"
    [updated] = kinds(anna, "anna/maity", "project_updated")
    assert updated["payload"]["fields"] == {
        "owner": {"id": anna.id, "handle": "anna"},
        "full_name": "anna/maity",
    }
    texts = [i["payload"]["text"] for i in kinds(anna, "anna/maity", "ticker")]
    assert texts == ["maintainer/maity is now anna/maity"]


def test_a_no_moves_nothing(owner: flow.Human, anna: flow.Human) -> None:
    request = transfer(owner, anna.id).json()
    assert answer(anna, "maintainer/maity", request["id"], "no").status_code == 200
    assert owner.get("/projects/maintainer/maity").json()["owner"]["handle"] == "maintainer"


def test_only_the_namespace_owner_transfers_to_an_owner(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human, anna: flow.Human
) -> None:
    assert transfer(anna, owner.id).status_code == 403
    stranger = flow.human(make_client, migrated, "stranger")
    refused = transfer(owner, stranger.id)
    assert error(refused) == (400, "invalid", {"fields": {"to": "not_an_owner"}})
    assert error(transfer(owner, owner.id)) == (400, "invalid", {"fields": {"to": "self"}})


def test_one_open_transfer_and_a_rename_withdraws_it(owner: flow.Human, anna: flow.Human) -> None:
    first = transfer(owner, anna.id).json()
    second = transfer(owner, anna.id).json()
    assert status_of(owner, "maintainer/maity", first["id"]) == "withdrawn"
    rename(owner, "maintainer/maity", "maity-hub")
    assert status_of(owner, "maintainer/maity-hub", second["id"]) == "withdrawn"


def test_a_go_after_the_receiver_stopped_being_owner_is_stale(
    owner: flow.Human, anna: flow.Human
) -> None:
    request = transfer(owner, anna.id).json()
    demoted = owner.patch(f"/projects/maintainer/maity/members/{anna.id}", {"trust": "admin"})
    assert demoted.status_code == 200, demoted.text
    stale = answer(anna, "maintainer/maity", request["id"])
    assert error(stale) == (409, "invalid_transition", {"reason": "transfer_stale"})
    assert status_of(owner, "maintainer/maity", request["id"]) == "withdrawn"
    assert owner.get("/projects/maintainer/maity").json()["full_name"] == "maintainer/maity"


def test_a_go_onto_a_taken_slug_withdraws_and_moves_nothing(
    owner: flow.Human, anna: flow.Human
) -> None:
    request = transfer(owner, anna.id).json()
    flow.project(anna, "maity")  # anna/maity, her own
    taken = answer(anna, "maintainer/maity", request["id"])
    assert error(taken) == (400, "invalid", {"fields": {"slug": "taken"}})
    assert status_of(owner, "maintainer/maity", request["id"]) == "withdrawn"
    assert owner.get("/projects/maintainer/maity").json()["full_name"] == "maintainer/maity"


# --- the namespace owner stays an owner ---------------------------------------------------


def test_the_namespace_owner_is_neither_demoted_nor_removed(
    owner: flow.Human, anna: flow.Human
) -> None:
    path = f"/projects/maintainer/maity/members/{owner.id}"
    demoted = anna.patch(path, {"trust": "admin"})
    assert error(demoted) == (409, "namespace_owner", {"projects": ["maintainer/maity"]})
    removed = anna.delete(path)
    assert error(removed) == (409, "namespace_owner", {"projects": ["maintainer/maity"]})
    # Another owner is: the last-owner rule alone holds for them.
    assert (
        owner.patch(f"/projects/maintainer/maity/members/{anna.id}", {"trust": "admin"}).status_code
        == 200
    )


def test_a_transfer_turns_the_page_off_and_isolates_the_agents_of_outsiders(
    owner: flow.Human, anna: flow.Human, migrated: Engine
) -> None:
    """§6.2: an unset `agent_owners` reads `members` once the page is off, and the transfer
    turns it off, so an agent whose owner is no member goes with it."""
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    lent = factory.agent(migrated, project_id, factory.human(migrated, "stranger")).agent_id
    assert owner.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
    with migrated.connect() as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == lent)).one()
    assert row.isolated_since is None  # `anyone` while the project has a page
    request = transfer(owner, anna.id).json()
    assert answer(anna, "maintainer/maity", request["id"]).status_code == 200
    with migrated.connect() as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == lent)).one()
    assert row.isolated_since is not None and row.isolated_by == "hub"
