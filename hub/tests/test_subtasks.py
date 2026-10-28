"""Resulting-graph rules and the subtask proposal gate (§6.4)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import cards, db, events, policy
from maity_hub import tables as t
from maity_hub.errors import ApiError
from tests import factory, flow
from tests.concurrency import finished, race, waiting
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity/tasks"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    person = flow.human(make_client, migrated)
    flow.project(person, "maity")
    return person


def create(who: Any, **fields: Any) -> dict[str, Any]:
    response = who.post(BASE, {"title": "A card", **fields})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def path(card: dict[str, Any]) -> str:
    return f"{BASE}/{card['id']}"


def invalid(response: Any, field: str, reason: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"][field] == reason


def proposed(response: Any) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"
    assert response.json()["error"]["details"]["reason"] == "subtasks_proposed"


@pytest.mark.parametrize("preset", policy.PRESETS)
def test_default_and_preset_preservation(owner: flow.Human, preset: str) -> None:
    assert owner.get("/projects/maintainer/maity").json()["policy"]["subtasks"] == "proposed"
    assert (
        flow.project(owner, f"p-{preset}", policy={"preset": preset})["policy"]["subtasks"]
        == "proposed"
    )
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"subtasks": "direct"}, "reason": "trusted team"}
    )
    assert response.status_code == 200
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"preset": preset}, "reason": "preset"}
    )
    assert response.json()["policy"]["subtasks"] == "direct"


def test_proposal_gate_covers_creation_and_every_attach_open_bypass(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    member = flow.agent(make_client, owner)
    parent = create(owner)
    child = create(member, parent=parent["id"])
    assert child["status"] == "proposed"
    proposed(member.post(BASE, {"title": "bypass", "parent": parent["id"], "status": "open"}))
    proposed(member.patch(path(child), {"status": "open"}))
    opened = create(member)
    proposed(member.patch(path(opened), {"parent": parent["id"]}))
    waiting = create(member, status="proposed")
    proposed(member.patch(path(waiting), {"parent": parent["id"], "status": "open"}))
    unchanged = member.get(path(waiting)).json()
    assert unchanged["parent"] is None and unchanged["status"] == "proposed"
    assert owner.patch(path(child), {"status": "open"}).status_code == 200
    # Detaching is free to the editor, including detaching and opening atomically.
    detached = member.patch(path(child), {"parent": None})
    assert detached.status_code == 200 and detached.json()["parent"] is None
    another = create(member, parent=parent["id"])
    assert member.patch(path(another), {"parent": None, "status": "open"}).status_code == 200


def test_direct_policy_uses_ordinary_card_rights(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    member = flow.agent(make_client, owner)
    assert (
        owner.patch(
            "/projects/maintainer/maity", {"policy": {"subtasks": "direct"}, "reason": "trusted"}
        ).status_code
        == 200
    )
    parent = create(owner)
    child = create(member, parent=parent["id"], status="open")
    assert child["status"] == "open"
    unparented = create(member)
    assert member.patch(path(unparented), {"parent": parent["id"]}).status_code == 200
    waiting = create(member, parent=parent["id"], status="proposed")
    assert member.patch(path(waiting), {"status": "open"}).status_code == 200
    stranger = flow.agent(make_client, owner)
    assert stranger.patch(path(child), {"parent": None}).status_code == 403


def test_depth_self_and_cards_with_children(owner: flow.Human) -> None:
    parent = create(owner)
    child = create(owner, parent=parent["id"])
    other = create(owner)
    invalid(owner.post(BASE, {"title": "third level", "parent": child["id"]}), "parent", "too_deep")
    invalid(owner.patch(path(parent), {"parent": parent["id"]}), "parent", "self")
    invalid(owner.patch(path(parent), {"parent": other["id"]}), "parent", "has_children")


@pytest.mark.parametrize("release_is_parent", [True, False])
def test_release_is_neither_parent_nor_child(owner: flow.Human, release_is_parent: bool) -> None:
    release = create(owner, kind="release", release={"version": "1.0.0"})
    ordinary = create(owner)
    parent, child = (release, ordinary) if release_is_parent else (ordinary, release)
    invalid(owner.patch(path(child), {"parent": parent["id"]}), "parent", "release_card")


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_closed_parent_takes_no_new_child_but_keeps_existing_children(
    owner: flow.Human, migrated: Engine, status: str
) -> None:
    parent = create(owner)
    existing = create(owner, parent=parent["id"])
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == parent["id"]).values(status=status))
    invalid(owner.post(BASE, {"title": "late", "parent": parent["id"]}), "parent", "parent_closed")
    moving = create(owner)
    invalid(owner.patch(path(moving), {"parent": parent["id"]}), "parent", "parent_closed")
    assert owner.patch(path(existing), {"body": "still editable"}).status_code == 200
    assert owner.patch(path(existing), {"parent": None}).status_code == 200


def test_parent_and_related_stay_inside_the_project(owner: flow.Human) -> None:
    flow.project(owner, "other")
    foreign = owner.post("/projects/maintainer/other/tasks", {"title": "foreign"}).json()["id"]
    for field, value in (("parent", foreign), ("related", [foreign])):
        invalid(owner.post(BASE, {"title": "no", field: value}), field, "unknown_task")


def test_parent_and_dependencies_form_one_gate_graph(owner: flow.Human) -> None:
    parent = create(owner)
    child = create(owner, parent=parent["id"])
    invalid(owner.patch(path(child), {"depends_on": [parent["id"]]}), "depends_on", "cycle")
    assert owner.patch(path(parent), {"depends_on": [child["id"]]}).status_code == 200
    # This combined write is valid: the old implicit gate is removed in the same write.
    assert owner.patch(path(parent), {"depends_on": []}).status_code == 200
    result = owner.patch(path(child), {"parent": None, "depends_on": [parent["id"]]})
    assert result.status_code == 200, result.text
    invalid(owner.patch(path(child), {"parent": parent["id"]}), "parent", "cycle")
    # This combined write is also valid: remove the old explicit edge while attaching.
    result = owner.patch(path(child), {"parent": parent["id"], "depends_on": []})
    assert result.status_code == 200, result.text


def test_long_cycle_through_another_dependency_is_atomic(owner: flow.Human) -> None:
    parent, middle, child = create(owner), create(owner), create(owner)
    assert owner.patch(path(middle), {"depends_on": [parent["id"]]}).status_code == 200
    assert owner.patch(path(child), {"depends_on": [middle["id"]]}).status_code == 200
    refused = owner.patch(path(child), {"parent": parent["id"], "title": "must roll back"})
    invalid(refused, "parent", "cycle")
    current = owner.get(path(child)).json()
    assert current["parent"] is None and current["title"] == "A card"


def test_related_is_symmetric_accepts_releases_and_records_only_the_authored_history(
    owner: flow.Human,
) -> None:
    ordinary = create(owner)
    release = create(owner, kind="release", release={"version": "1.0.0"})
    response = owner.patch(path(ordinary), {"related": [release["id"], release["id"]]})
    assert response.status_code == 200 and response.json()["related"] == [release["id"]]
    assert owner.get(path(release)).json()["related"] == [ordinary["id"]]
    history = owner.get(path(ordinary) + "/history").json()["items"]
    assert any(item["field"] == "related" and item["after"] == [release["id"]] for item in history)
    mirrored = owner.get(path(release) + "/history").json()["items"]
    assert not any(item["field"] == "related" for item in mirrored)
    assert owner.patch(path(release), {"related": []}).status_code == 200
    assert owner.get(path(ordinary)).json()["related"] == []


def test_filter_counts_and_parent_events(owner: flow.Human, migrated: Engine) -> None:
    old, new = create(owner), create(owner)
    child = create(owner, parent=old["id"])
    assert owner.get(path(old)).json()["children"] == {"open": 1, "total": 1}
    filtered = owner.get(BASE + f"?parent={old['id']}").json()["items"]
    assert [item["id"] for item in filtered] == [child["id"]]
    with migrated.connect() as conn:
        before = conn.execute(
            select(t.event.c.seq).order_by(t.event.c.seq.desc()).limit(1)
        ).scalar_one()
    assert owner.patch(path(child), {"parent": new["id"]}).status_code == 200
    events = owner.get(f"/projects/maintainer/maity/events?after={before}").json()["items"]
    updates = [e for e in events if e["kind"] == "task_updated"]
    counts = {
        e["payload"]["id"]: e["payload"]["children"]
        for e in updates
        if e["payload"]["fields"] == ["children"]
    }
    assert counts == {old["id"]: {"open": 0, "total": 0}, new["id"]: {"open": 1, "total": 1}}
    assert owner.patch(path(child), {"status": "cancelled"}).status_code == 200
    assert owner.get(path(new)).json()["children"] == {"open": 0, "total": 1}
    history = owner.get(path(child) + "/history").json()["items"]
    assert any(
        item["field"] == "parent" and item["before"] == old["id"] and item["after"] == new["id"]
        for item in history
    )
    parent_history = owner.get(path(new) + "/history").json()["items"]
    assert not any(item["field"] == "children" for item in parent_history)


def test_done_gate_unions_children_and_dependencies_and_deduplicates(owner: flow.Human) -> None:
    parent = create(owner)
    child = create(owner, parent=parent["id"])
    dependency = create(owner)
    assert (
        owner.patch(path(parent), {"depends_on": [child["id"], dependency["id"]]}).status_code
        == 200
    )
    assert owner.post(path(parent) + "/claim", {}).status_code == 200
    report = {"summary": "ready", "code": False, "pr_status": "none", "done": False}
    assert owner.post(path(parent) + "/report", report).status_code == 200
    refused = owner.patch(path(parent), {"status": "done"})
    assert refused.status_code == 409
    assert refused.json()["error"]["details"] == {
        "open": sorted([child["id"], dependency["id"]]),
        "children": [child["id"]],
    }
    for card in (child, dependency):
        assert owner.patch(path(card), {"status": "cancelled"}).status_code == 200
    assert owner.patch(path(parent), {"status": "done"}).status_code == 200


def test_migration_preserves_existing_projects_with_proposed_policy(engine: Engine) -> None:
    db.migrate(engine, "0027")
    project_id = factory.project(engine)
    human_id = factory.human(engine)
    membership_id = factory.membership(engine, project_id, human_id=human_id)
    card_id = factory.card(engine, project_id, membership_id)
    db.migrate(engine)
    with engine.connect() as conn:
        row = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
        assert row.subtasks == "proposed"
        legacy = dict(row._mapping)
        del legacy["subtasks"]
        assert policy.of(SimpleNamespace(**legacy))["subtasks"] == "proposed"
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
        assert card.parent is None and card.title == "A card"


def test_report_done_has_the_child_gate_and_announces_parent_counts(owner: flow.Human) -> None:
    assert (
        owner.patch(
            "/projects/maintainer/maity", {"policy": {"done_authority": "holder"}, "reason": "test"}
        ).status_code
        == 200
    )
    parent = create(owner)
    child = create(owner, parent=parent["id"])
    report = {"summary": "ready", "code": False, "pr_status": "none", "done": True}
    assert owner.post(path(parent) + "/claim", {}).status_code == 200
    refused = owner.post(path(parent) + "/report", report)
    assert refused.status_code == 409 and refused.json()["error"]["details"]["children"] == [
        child["id"]
    ]
    assert owner.get(path(parent)).json()["status"] == "in_progress"
    assert owner.post(path(child) + "/claim", {}).status_code == 200
    assert owner.post(path(child) + "/report", report).status_code == 200
    assert owner.get(path(parent)).json()["children"] == {"open": 0, "total": 1}
    assert owner.post(path(parent) + "/report", report).status_code == 200


def test_cancelling_parent_leaves_children_and_related_does_not_gate_done(
    owner: flow.Human,
) -> None:
    parent = create(owner)
    child = create(owner, parent=parent["id"])
    assert owner.patch(path(parent), {"status": "cancelled"}).status_code == 200
    assert owner.get(path(child)).json()["parent"] == parent["id"]
    assert owner.get(path(child)).json()["status"] == "open"
    related = create(owner, related=[child["id"]])
    assert owner.post(path(related) + "/claim", {}).status_code == 200
    report = {"summary": "ready", "code": False, "pr_status": "none"}
    assert owner.post(path(related) + "/report", report).status_code == 200
    assert owner.patch(path(related), {"status": "done"}).status_code == 200


def test_related_mirror_events_and_computed_children_are_read_only(
    owner: flow.Human, migrated: Engine
) -> None:
    first, second = create(owner), create(owner)
    with migrated.connect() as conn:
        before = conn.execute(
            select(t.event.c.seq).order_by(t.event.c.seq.desc()).limit(1)
        ).scalar_one()
    assert owner.patch(path(first), {"related": [second["id"]]}).status_code == 200
    items = owner.get(f"/projects/maintainer/maity/events?after={before}").json()["items"]
    mirrored = {
        e["payload"]["id"]: e["payload"]["related"]
        for e in items
        if e["kind"] == "task_updated" and e["payload"]["fields"] == ["related"]
    }
    assert mirrored == {first["id"]: [second["id"]], second["id"]: [first["id"]]}
    assert owner.post(BASE, {"title": "no", "children": {"total": 9, "open": 0}}).status_code == 400
    assert owner.patch(path(first), {"children": {"total": 9, "open": 0}}).status_code == 400


@pytest.mark.parametrize("operation", ["depth", "cycle"])
def test_project_lock_serialises_competing_graph_writes(
    owner: flow.Human, migrated: Engine, operation: str
) -> None:
    parent, child, third = create(owner), create(owner), create(owner)
    with migrated.connect() as conn:
        project_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar_one()
    with race(migrated) as racing:
        events.lock_project(racing.first, project_id)
        cards.check_subtask_graph(
            racing.first,
            project_id,
            child["id"],
            kind="task",
            parent=parent["id"],
            depends_on=None,
            fields={"parent"},
        )
        racing.first.execute(
            update(t.card).where(t.card.c.id == child["id"]).values(parent=parent["id"])
        )

        def second() -> None:
            events.lock_project(racing.second, project_id)
            if operation == "depth":
                cards.check_subtask_graph(
                    racing.second,
                    project_id,
                    third["id"],
                    kind="task",
                    parent=child["id"],
                    depends_on=None,
                    fields={"parent"},
                )
            else:
                current = racing.second.execute(
                    select(t.card).where(t.card.c.id == child["id"])
                ).one()
                cards.check_subtask_graph(
                    racing.second,
                    project_id,
                    child["id"],
                    kind="task",
                    parent=current.parent,
                    depends_on=[parent["id"]],
                    fields={"depends_on"},
                )

        step = racing.run(racing.second, second)
        assert waiting(step)
        racing.first.commit()
        with pytest.raises(ApiError) as error:
            finished(step)
        assert error.value.details["fields"] == (
            {"parent": "too_deep"} if operation == "depth" else {"depends_on": "cycle"}
        )
