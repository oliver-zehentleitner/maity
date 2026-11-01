"""docs/api.md §6.4: cards, the transition table, edges, routing, the board."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

TASK_KEYS = {
    "id",
    "assigned_instance",
    "kind",
    "title",
    "body",
    "label",
    "needs",
    "status",
    "rank",
    "watching",
    "area",
    "created_by",
    "assigned_to",
    "claim",
    "checkpoint",
    "depends_on",
    "ships_with",
    "parent",
    "related",
    "children",
    "blocked_by_request",
    "ktw_ref",
    "jour_fixe",
    "report",
    "release",
    "contract",
    "imported_from",  # §6.14: null unless imported
    "cover",  # §6.12: null unless a substitute holds it for someone
    "links",  # §6.13
    "notes",  # §6.16: the counts
    "created_at",
    "updated_at",
    "closed_at",
    "mentions",
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def task(who: Any, **body: Any) -> dict[str, Any]:
    response = who.post("/projects/maintainer/maity/tasks", {"title": "A card", **body})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _event(engine: Engine, kind: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq.desc())
        ).first()


def test_a_card_has_the_contract_shape(owner: flow.Human, migrated: Engine) -> None:
    card = task(owner, body="what and why", label="feature", area="hub/", ktw_ref="ctx-1")
    assert set(card) == TASK_KEYS
    assert card["id"].startswith("tsk-") and card["kind"] == "task" and card["status"] == "open"
    assert (card["created_by"], card["label"], card["claim"]) == (owner.id, "feature", None)
    event = _event(migrated, "task_created")
    assert event.payload["project_state"] == "build" and event.payload["reason"] is None


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"label": "bug"}, {"label": "unknown"}),
        ({"needs": "plumber"}, {"needs": "unknown"}),
        ({"needs": "proxy"}, {"needs": "unknown"}),
        ({"needs": "manager"}, {"needs": "unknown"}),
        ({"kind": "epic"}, {"kind": "unknown"}),
        ({"kind": "release"}, {"release.version": "required"}),
        ({"release": {"version": "1.0.0"}}, {"release": "releases_only"}),
        ({"status": "in_progress"}, {"status": "proposed_or_open"}),
        ({"area": "hub/`x"}, {"area": "invalid_path"}),
        ({"depends_on": ["tsk-nope"]}, {"depends_on": "unknown_task"}),
    ],
)
def test_card_fields_are_checked(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    response = owner.post("/projects/maintainer/maity/tasks", {"title": "x", **body})
    assert response.json()["error"]["details"]["fields"] == fields


def test_a_finding_goes_to_the_owner_of_the_narrowest_area(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    hub = flow.agent(make_client, owner, areas=["hub/"])
    deep = flow.agent(make_client, owner, areas=["hub/src/maity_hub/routes/"])
    assert task(owner, area="hub/README.md")["assigned_to"] == hub.id
    assert task(owner, area="hub/src/maity_hub/routes/tasks.py")["assigned_to"] == deep.id
    assert task(owner, area="docs/")["assigned_to"] == owner.id  # "/" is the owner's
    assert task(owner)["assigned_to"] is None


def test_assigning_at_creation_needs_tasks_admin(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    member = flow.agent(make_client, owner)
    response = member.post(
        "/projects/maintainer/maity/tasks", {"title": "x", "assigned_to": owner.id}
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"] == {"scope": "tasks:admin"}
    assert task(owner, assigned_to=member.id)["assigned_to"] == member.id


@pytest.mark.parametrize("state", ["plan", "review"])
def test_a_closed_project_takes_no_card_and_one_in_plan_or_review_wants_a_reason(
    owner: flow.Human, migrated: Engine, state: str
) -> None:
    owner.patch("/projects/maintainer/maity", {"state": state, "reason": "release"})
    without = owner.post("/projects/maintainer/maity/tasks", {"title": "x"})
    assert without.json()["error"]["details"]["fields"] == {"reason": "required"}
    task(owner, reason="hotfix for 0.1.0")
    payload = _event(migrated, "task_created").payload
    assert (payload["project_state"], payload["reason"]) == (state, "hotfix for 0.1.0")
    owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "done"})
    closed = owner.post("/projects/maintainer/maity/tasks", {"title": "x", "reason": "y"})
    assert closed.status_code == 409 and closed.headers["Maity-Error"] == "project_closed"


def test_ships_with_is_mirrored_and_depends_on_refuses_a_cycle(owner: flow.Human) -> None:
    a, b = task(owner), task(owner)
    c = task(owner, ships_with=[a["id"]], depends_on=[b["id"]])
    assert owner.get(f"/projects/maintainer/maity/tasks/{a['id']}").json()["ships_with"] == [
        c["id"]
    ]
    assert c["depends_on"] == [b["id"]]
    cycle = owner.patch(f"/projects/maintainer/maity/tasks/{b['id']}", {"depends_on": [c["id"]]})
    assert cycle.json()["error"]["details"]["fields"] == {"depends_on": "cycle"}
    self_edge = owner.patch(
        f"/projects/maintainer/maity/tasks/{a['id']}", {"depends_on": [a["id"]]}
    )
    assert self_edge.json()["error"]["details"]["fields"] == {"depends_on": "self"}
    owner.patch(f"/projects/maintainer/maity/tasks/{c['id']}", {"ships_with": []})
    assert owner.get(f"/projects/maintainer/maity/tasks/{a['id']}").json()["ships_with"] == []


def test_edges_stay_inside_the_project(owner: flow.Human) -> None:
    flow.project(owner, "other")
    foreign = owner.post("/projects/maintainer/other/tasks", {"title": "x"}).json()
    response = owner.post(
        "/projects/maintainer/maity/tasks", {"title": "y", "ships_with": [foreign["id"]]}
    )
    assert response.json()["error"]["details"]["fields"] == {"ships_with": "unknown_task"}
    assert (
        owner.get(f"/projects/maintainer/maity/tasks/{foreign['id']}").headers["Maity-Error"]
        == "not_found"
    )


@pytest.mark.parametrize(
    ("start", "to", "ok"),
    [
        ("open", "proposed", True),
        ("proposed", "open", True),
        ("open", "cancelled", True),
        ("open", "review", False),
        ("open", "in_progress", False),
        ("open", "blocked", False),
        ("open", "done", False),
    ],
)
def test_the_transition_table_for_unclaimed_cards(
    owner: flow.Human, start: str, to: str, ok: bool
) -> None:
    card = task(owner, status="proposed" if start == "proposed" else "open")
    response = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": to})
    if ok:
        assert response.status_code == 200 and response.json()["status"] == to
    else:
        assert response.status_code == 409
        assert response.json()["error"]["details"] == {"from": start, "to": to}


def test_closing_sets_closed_at(owner: flow.Human) -> None:
    card = task(owner)
    cancelled = owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "cancelled"}
    ).json()
    assert cancelled["closed_at"] is not None


def test_only_holder_creator_or_admin_edit_a_card(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    card = task(owner)
    stranger = flow.agent(make_client, owner)
    response = stranger.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"title": "mine"})
    assert response.status_code == 403
    mine = task(stranger)
    assert (
        stranger.patch(
            f"/projects/maintainer/maity/tasks/{mine['id']}", {"title": "renamed"}
        ).json()["title"]
        == "renamed"
    )
    cancel = stranger.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "cancelled"}
    )
    assert cancel.status_code == 403


def test_done_is_refused_while_a_dependency_is_open(owner: flow.Human) -> None:
    owner.patch(
        "/projects/maintainer/maity", {"policy": {"done_authority": "admin"}, "reason": "test"}
    )
    dep = task(owner)
    card = task(owner, depends_on=[dep["id"]])
    owner.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    owner.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", _report())
    refused = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "done"})
    assert refused.status_code == 409
    assert refused.json()["error"]["details"] == {"open": [dep["id"]]}
    owner.patch(f"/projects/maintainer/maity/tasks/{dep['id']}", {"status": "cancelled"})
    done = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "done"})
    assert done.json()["status"] == "done" and done.json()["closed_at"]


def test_the_board_filters_orders_and_pages(owner: flow.Human) -> None:
    ids = [task(owner, label="fix" if i % 2 else "chore")["id"] for i in range(5)]
    owner.patch(f"/projects/maintainer/maity/tasks/{ids[0]}", {"status": "cancelled"})
    page = owner.get("/projects/maintainer/maity/tasks?limit=2").json()
    # The board's order (§6.4): columns in board order, unranked cards by creation, the
    # closed column last.
    assert [c["id"] for c in page["items"]] == [ids[1], ids[2]]
    updated = owner.get("/projects/maintainer/maity/tasks?limit=2&order=updated").json()
    assert [c["id"] for c in updated["items"]] == [ids[0], ids[4]]  # updated_at desc
    seen = [c["id"] for c in page["items"]]
    cursor = page["next_cursor"]
    while cursor:
        page = owner.get(f"/projects/maintainer/maity/tasks?limit=2&cursor={cursor}").json()
        seen += [c["id"] for c in page["items"]]
        cursor = page["next_cursor"]
    assert seen == [ids[1], ids[2], ids[3], ids[4], ids[0]]
    fixes = owner.get("/projects/maintainer/maity/tasks?label=fix").json()["items"]
    assert {c["id"] for c in fixes} == {ids[1], ids[3]}
    open_only = owner.get("/projects/maintainer/maity/tasks?status=open").json()["items"]
    assert ids[0] not in {c["id"] for c in open_only}
    recent = owner.get("/projects/maintainer/maity/tasks?closed_after=2999-01-01T00:00:00Z").json()[
        "items"
    ]
    assert ids[0] not in {c["id"] for c in recent} and len(recent) == 4  # open cards always
    assert (
        owner.get("/projects/maintainer/maity/tasks?status=lost").headers["Maity-Error"]
        == "invalid"
    )


def _report(**overrides: Any) -> dict[str, Any]:
    sha = "d91e294c" + "0" * 32
    body = {
        "summary": "Adds the lease.",
        "head": sha,
        "branch": "agent-b/lease",
        "upstream": "origin/agent-b/lease",
        "remote_head": sha,
        "pr": None,
        "pr_status": "none",
        "pr_unknown_reason": None,
        "why": {"none": "a test report, nothing to keep"},  # §6.23: a new project requires it
    }
    return {**body, **overrides}


def test_a_mirrored_edge_announces_the_other_card(owner: flow.Human, migrated: Engine) -> None:
    a = task(owner)
    before = owner.get(f"/projects/maintainer/maity/tasks/{a['id']}").json()["updated_at"]
    b = task(owner, ships_with=[a["id"]])
    with migrated.connect() as conn:
        updated = conn.execute(
            select(t.event).where(t.event.c.kind == "task_updated", t.event.c.subject_id == a["id"])
        ).one()
    assert updated.payload["ships_with"] == [b["id"]]
    assert owner.get(f"/projects/maintainer/maity/tasks/{a['id']}").json()["updated_at"] >= before


def test_an_edge_patch_that_changes_nothing_says_nothing(
    owner: flow.Human, migrated: Engine
) -> None:
    a, b = task(owner), task(owner)
    owner.patch(f"/projects/maintainer/maity/tasks/{a['id']}", {"depends_on": [b["id"]]})
    owner.patch(f"/projects/maintainer/maity/tasks/{a['id']}", {"depends_on": [b["id"]]})
    with migrated.connect() as conn:
        updates = conn.execute(
            select(t.event).where(t.event.c.kind == "task_updated", t.event.c.subject_id == a["id"])
        ).all()
    assert len(updates) == 1


def test_needs_is_set_changed_shown_and_filtered_and_routes_nothing(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """§6.4: which role the card is for; a member of another role may still claim it."""
    path = "/projects/maintainer/maity/tasks"
    plain = task(owner)
    assert plain["needs"] is None
    card = task(owner, needs="reviewer")
    assert card["needs"] == "reviewer"
    assert [c["id"] for c in owner.get(f"{path}?needs=reviewer").json()["items"]] == [card["id"]]
    changed = owner.patch(f"{path}/{card['id']}", {"needs": "tester"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["needs"] == "tester"
    history = owner.get(f"{path}/{card['id']}/history").json()["items"]
    assert any(e["field"] == "needs" and e["after"] == "tester" for e in history)
    refused = owner.patch(f"{path}/{card['id']}", {"needs": "plumber"})
    assert refused.status_code == 400, refused.text
    coder = flow.agent(make_client, owner)
    claimed = coder.post(f"{path}/{card['id']}/claim", {})
    assert claimed.status_code == 200, claimed.text
    cleared = owner.patch(f"{path}/{card['id']}", {"needs": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["needs"] is None
