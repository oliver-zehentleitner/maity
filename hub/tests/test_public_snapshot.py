"""docs/api.md §16.9, "A project's page": the snapshot of what is happening, the ticker entries
a visitor may read and who is online, rendered with the page and again by its own worker."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import clock, public_pages, public_snapshot
from maity_hub import tables as t
from tests.conftest import ClientFactory
from tests.test_public_project_views import BASE, TASKS, World
from tests.test_reports import report


@pytest.fixture
def hub(settings: Any) -> Any:
    return replace(settings, public_pages=True)


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, hub: Any) -> World:
    public_pages.configure(hub)
    found = World(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == found.project_id)
            .values(repository_url="https://github.com/o/r", repository_public=True)
        )
        public_pages.touch(conn, "project", found.project_id)
    return found


def item(world: World, payload: dict[str, Any], *, days: int = 0, redacted: bool = False) -> None:
    """A ticker event as the hub stores one, then what its write does to the page."""
    with world.migrated.begin() as conn:
        conn.execute(
            t.event.insert().values(
                project_id=world.project_id,
                kind="ticker",
                at=clock.now() - timedelta(days=days),
                audience=["all"],
                payload={"text": "", "url": None, **payload},
                redacted=redacted,
            )
        )
        public_pages.touch(conn, "project", world.project_id)


def merge(text: str, *tasks: str, public: bool = True) -> dict[str, Any]:
    return {
        "type": "merge",
        "text": text,
        "url": "https://github.com/o/r/pull/1",
        "merge": {"public": public},
        "tasks": list(tasks),
        "reasons": [{"member_id": "agt-secret-reason", "why": ["x"]}],
        "paths": ["secret/path.py"],
    }


def decision(card_id: str | None) -> dict[str, Any]:
    return {
        "type": "decision",
        "text": f"Decided: {card_id or 'req-1'}",
        "request": {"id": "req-1", "class": "decision", "task_id": card_id},
        "tasks": [card_id] if card_id else [],
    }


def snapshot(world: World) -> Any:
    got = world.anyone.get(f"/api/v1/public/pages{BASE}")
    assert got.status_code == 200, got.text
    return got.json()["data"]


def texts(world: World) -> list[str]:
    return [e["text"] for e in snapshot(world)["ticker"]]


def test_a_public_merge_and_a_decision_on_a_public_card_are_shown(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Public card"}).json()["id"]
    item(world, merge("#1 merged <b>x</b>", card_id))
    item(world, decision(card_id))
    entries = snapshot(world)["ticker"]
    assert [e["type"] for e in entries] == ["decision", "merge"]
    assert set(entries[0]) == {"type", "text", "url", "at"}
    assert entries[1]["url"] == "https://github.com/o/r/pull/1" and entries[0]["url"] is None
    text = world.anyone.get(BASE).text
    assert "<h2>Recently</h2>" in text and "#1 merged &lt;b&gt;x&lt;/b&gt;" in text
    raw = world.anyone.get(f"/api/v1/public/pages{BASE}").text
    assert "agt-secret-reason" not in raw and "secret/path.py" not in raw


def test_every_other_entry_stays_off(world: World) -> None:
    secret = world.card(title="Hole", label="security")
    item(world, merge("private repo merge", public=False))
    item(world, merge("merge of a security fix", secret))
    item(world, decision(None))
    item(world, decision(secret))
    for kind in ("deploy", "release", "note", "rename", "jour_fixe"):
        item(world, {"type": kind, "text": f"a {kind}"})
    item(world, merge("too old"), days=8)
    item(world, merge("redacted"), redacted=True)
    assert texts(world) == []


def test_no_merge_while_the_repository_is_not_seen_public(world: World) -> None:
    item(world, merge("a merge"))
    assert texts(world) == ["a merge"]
    with world.migrated.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == world.project_id)
            .values(repository_public=False)
        )
        public_pages.touch(conn, "project", world.project_id)
    assert texts(world) == []


def test_a_held_card_takes_its_decision_off_at_once_and_back_on_dismiss(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Spammy"}).json()["id"]
    item(world, decision(card_id))
    assert texts(world) == [f"Decided: {card_id}"]
    got = report(world.anna, {"type": "card", "id": card_id, "project": "maintainer/maity"}, "spam")
    assert got.status_code == 201, got.text

    def resolved(action: str) -> None:
        done = world.owner.post(f"/admin/reports/{got.json()['id']}/resolve", {"action": action})
        assert done.status_code == 200, done.text

    resolved("hide")
    assert texts(world) == []
    resolved("dismiss")
    assert texts(world) == [f"Decided: {card_id}"]


def test_a_card_change_renders_the_page_at_once(world: World) -> None:
    card_id = world.card(title="Becomes secret", label="fix")
    item(world, decision(card_id))
    assert texts(world) == [f"Decided: {card_id}"]
    with world.migrated.begin() as conn:  # a label the API does not set, as an import may hold
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(label="security"))
    edited = world.owner.patch(f"{TASKS}/{card_id}", {"title": "Becomes secret, edited"})
    assert edited.status_code == 200, edited.text
    assert texts(world) == []


def seen(world: World, membership_id: int, when: Any) -> None:
    with world.migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == membership_id).values(last_seen_at=when)
        )


def test_who_is_online_is_counted_and_named_as_the_board_names_them(world: World, hub: Any) -> None:
    seen(world, world.anna_member, clock.now())
    worker = public_snapshot.Worker(world.migrated, hub)
    worker.run_once()
    up = snapshot(world)["online"]
    assert up["humans"] >= 1 and "as_of" in up
    assert all(p["handle"] != "anna" for p in up["named"])  # her profile is not public
    world.anna.patch("/me", {"public_profile": True})
    worker.run_once()
    assert any(p["handle"] == "anna" for p in snapshot(world)["online"]["named"])
    seen(world, world.anna_member, clock.now() - timedelta(days=1))
    worker.run_once()
    assert all(p["handle"] != "anna" for p in snapshot(world)["online"]["named"])
