"""docs/api.md §5.1 "Start tabs", §5.3, §2.9: the projects a browser with no tabs of its own
opens, kept on the account as project ids, and every later membership put at the end."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select, update

from maity_hub import clock, start_tabs
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_invitations import accept, issue, token_of


def _ids(human: flow.Human) -> dict[str, str]:
    """slug → project id, from `/me`."""
    return {p["slug"]: p["id"] for p in human.get("/me").json()["projects"]}


def _tabs(human: flow.Human) -> Any:
    return human.get("/me").json()["member"]["start_tabs"]


def _field(response: Any) -> Any:
    return response.json()["error"]["details"]["fields"]["start_tabs"]


def test_every_project_carries_its_id_and_the_list_starts_null(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        fixed = conn.execute(select(t.project.c.id)).scalar_one()
    assert _ids(owner) == {"maity": fixed} and fixed.startswith("prj-")
    assert _tabs(owner) is None
    seen = agent.get("/me").json()
    assert seen["projects"][0]["id"] == fixed  # an agent's one project carries it too
    assert "start_tabs" not in seen["member"]


def test_a_human_sets_the_whole_list_in_order_and_null_goes_back(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    for slug in ("alpha", "beta", "gamma"):
        flow.project(owner, slug)
    ids = _ids(owner)
    chosen = [ids["gamma"], ids["alpha"]]
    done = owner.patch("/me", {"start_tabs": chosen})
    assert done.status_code == 200, done.text
    assert done.json()["member"]["start_tabs"] == chosen  # the answer is `/me` as it is now
    assert _tabs(owner) == chosen
    assert owner.patch("/me", {"start_tabs": []}).status_code == 200
    assert _tabs(owner) == []
    assert owner.patch("/me", {"start_tabs": None}).status_code == 200
    assert _tabs(owner) is None


def test_the_list_names_projects_of_the_caller_once_and_only_a_human_sets_it(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    other = flow.human(make_client, migrated, "other")
    flow.project(other, "theirs")
    agent = flow.agent(make_client, owner)
    mine, theirs = _ids(owner)["maity"], _ids(other)["theirs"]
    twice = owner.patch("/me", {"start_tabs": [mine, mine]})
    assert twice.status_code == 400 and _field(twice) == "duplicate"
    foreign = owner.patch("/me", {"start_tabs": [mine, theirs]})
    assert foreign.status_code == 400 and _field(foreign) == "not_a_member"
    unknown = owner.patch("/me", {"start_tabs": ["prj-nothere"]})
    assert unknown.status_code == 400 and _field(unknown) == "not_a_member"
    refused = agent.patch("/me", {"start_tabs": [mine]})
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    assert _tabs(owner) is None  # nothing refused was stored


def test_a_project_made_or_joined_later_goes_to_the_end(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    guest = flow.human(make_client, migrated, "guest")
    flow.project(guest, "first")
    flow.project(guest, "second")
    ids = _ids(guest)
    assert guest.patch("/me", {"start_tabs": [ids["second"]]}).status_code == 200
    flow.project(guest, "third")
    joined = accept(guest, token_of(issue(owner)))
    assert joined.status_code in (200, 201), joined.text
    now = _ids(guest)
    assert _tabs(guest) == [ids["second"], now["third"], now["maity"]]


def test_null_stays_null_when_a_membership_is_added(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    flow.project(owner, "more")
    assert _tabs(owner) is None  # null already opens every membership


def test_a_membership_made_again_drops_its_earlier_place(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "alpha")
    flow.project(owner, "beta")
    ids = _ids(owner)
    assert owner.patch("/me", {"start_tabs": [ids["alpha"], ids["beta"]]}).status_code == 200
    with migrated.begin() as conn:
        start_tabs.append(conn, owner.id, ids["alpha"])
    assert _tabs(owner) == [ids["beta"], ids["alpha"]]


def test_a_project_the_human_left_drops_out_of_the_read(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "alpha")
    flow.project(owner, "beta")
    ids = _ids(owner)
    assert owner.patch("/me", {"start_tabs": [ids["alpha"], ids["beta"]]}).status_code == 200
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == owner.id, t.membership.c.project_id == ids["alpha"])
            .values(removed_at=clock.now())
        )
    assert _tabs(owner) == [ids["beta"]]


def test_the_export_holds_the_list_with_full_names(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "alpha")
    flow.project(owner, "beta")
    ids = _ids(owner)
    assert owner.patch("/me", {"start_tabs": [ids["beta"], ids["alpha"]]}).status_code == 200
    exported = owner.get("/me/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["account"]["start_tabs"] == [
        {"id": ids["beta"], "full_name": "maintainer/beta"},
        {"id": ids["alpha"], "full_name": "maintainer/alpha"},
    ]
