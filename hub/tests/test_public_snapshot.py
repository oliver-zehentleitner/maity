"""docs/api.md §16.9, "A project's page": the snapshot of what is happening, the ticker entries
a visitor may read and who is online, rendered with the page and again by its own worker."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, events, public_pages, public_snapshot
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


def test_only_a_label_or_a_security_card_s_status_may_take_a_ticker_entry_off(
    world: World,
) -> None:
    """The rule `emit` renders the project's page by: `public_cards.shown` reads the label and
    the status. `security` is a label the API does not set (an import may hold one), and `done`
    has no way out through the API, so this guards the imported card and a later rule."""
    secret = world.card(title="Hole", label="security", status="review")
    plain = world.card(title="Plain", label="fix", status="review")
    hides = events._hides_ticker_entries
    with world.migrated.connect() as conn:
        assert hides(conn, "task_updated", {"fields": ["status"]}, secret)
        assert hides(conn, "task_updated", {"fields": ["label"]}, plain)
        assert not hides(conn, "task_updated", {"fields": ["status"]}, plain)
        assert not hides(conn, "task_updated", {"fields": ["title", "body"]}, secret)
        moved = {"status_before": "in_progress", "status_after": "review"}
        assert hides(conn, "task_reported", moved, secret)
        assert not hides(conn, "task_reported", moved, plain)
        same = {"status_before": "review", "status_after": "review"}
        assert not hides(conn, "task_reported", same, secret)
        for kind in ("task_claimed", "task_released", "task_assigned", "task_merged"):
            assert not hides(conn, kind, {"fields": ["status", "label"]}, secret)


def test_a_card_event_renders_no_other_card_s_page_under_the_project_lock(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`emit` holds the project row: one card's event renders the Board and that card's page,
    never every card page through the project page's dependents (prod, 2026-11-03: a render of
    every card of a public project per `task_updated` held the row for seconds)."""
    others = [world.card(title=f"Card {n}") for n in range(12)]
    edited = world.card(title="Edited", label="fix")
    rendered: list[tuple[str, str]] = []
    real = public_pages.refresh

    def counted(conn: Any, hub: Any, kind: str, target_id: str) -> None:
        rendered.append((kind, target_id))
        real(conn, hub, kind, target_id)

    monkeypatch.setattr(public_pages, "refresh", counted)
    board = [("card", edited), ("project_views", world.project_id)]
    for change, own_page in (
        ({"title": "Edited again"}, []),
        ({"status": "proposed"}, []),
        ({"label": "chore"}, [("project", world.project_id)]),  # its own page, no dependents
    ):
        rendered.clear()
        got = world.owner.patch(f"{TASKS}/{edited}", change)
        assert got.status_code == 200, got.text
        assert sorted(rendered) == sorted(board + own_page), change
    assert not {target for _, target in rendered} & set(others)


def test_a_member_change_no_page_shows_renders_nothing_under_the_project_lock(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A language change emits a `member_updated` into every project of the person, each under
    its project's row (dzse at #1277): it renders no page. A change a page shows still renders
    the project with its dependents."""
    for n in range(5):
        world.card(title=f"Card {n}")
    rendered: list[tuple[str, str]] = []
    real = public_pages.refresh

    def counted(conn: Any, hub: Any, kind: str, target_id: str) -> None:
        rendered.append((kind, target_id))
        real(conn, hub, kind, target_id)

    monkeypatch.setattr(public_pages, "refresh", counted)
    got = world.owner.patch("/me/notification-settings", {"email": {"language": "de"}})
    assert got.status_code == 200, got.text
    assert rendered == []
    with world.migrated.connect() as conn:
        human_id = conn.execute(
            select(t.membership.c.human_id).where(t.membership.c.id == world.anna_member)
        ).scalar_one()
    for changed, renders in ((["availability_policy"], False), (["links"], True), (None, True)):
        rendered.clear()
        with events.transaction(world.migrated) as conn:
            payload: dict[str, Any] = {"id": human_id}
            if changed is not None:
                payload["changed"] = changed
            events.emit(
                conn,
                world.project_id,
                "member_updated",
                ["all"],
                payload,
                subject=("member", human_id),
            )
        assert (("project", world.project_id) in rendered) is renders, changed
        assert (len(rendered) > 1) is renders, changed  # with its dependents


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
    assert any(p["handle"] == "anna" for p in up["named"])
    world.anna.patch("/me", {"public_profile": False})  # off is not invisible (§16.9)
    worker.run_once()
    assert any(p["handle"] == "anna" for p in snapshot(world)["online"]["named"])
    seen(world, world.anna_member, clock.now() - timedelta(days=1))
    worker.run_once()
    assert all(p["handle"] != "anna" for p in snapshot(world)["online"]["named"])


def test_an_away_or_paused_member_is_not_counted_online(world: World, hub: Any) -> None:
    from maity_hub.views import ONLINE

    worker = public_snapshot.Worker(world.migrated, hub)
    seen(world, world.anna_member, clock.now())
    worker.run_once()
    before = snapshot(world)["online"]["humans"]
    seen(world, world.anna_member, clock.now() - ONLINE - timedelta(seconds=5))  # away
    worker.run_once()
    assert snapshot(world)["online"]["humans"] == before - 1
    seen(world, world.anna_member, clock.now())
    with world.migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == world.anna_member)
            .values(paused_since=clock.now())
        )
    worker.run_once()
    assert snapshot(world)["online"]["humans"] == before - 1


def online_section(world: World) -> str:
    text = world.anyone.get(BASE).text
    return text[text.index("<h2>Online</h2>") :]


def test_with_public_presence_off_a_person_is_neither_named_nor_counted(
    world: World, hub: Any
) -> None:
    seen(world, world.anna_member, clock.now())
    worker = public_snapshot.Worker(world.migrated, hub)
    worker.run_once()
    before = snapshot(world)["online"]
    assert any(p["handle"] == "anna" for p in before["named"])
    assert "(anna)" in online_section(world)
    switched = world.anna.patch("/me", {"public_presence": False})
    assert switched.status_code == 200, switched.text
    assert switched.json()["member"]["public_presence"] is False
    up = snapshot(world)["online"]  # at once, without the worker's run
    assert all(p["handle"] != "anna" for p in up["named"])
    assert up["humans"] == before["humans"] - 1  # a count beside the names would point at them
    assert "(anna)" not in online_section(world)
    worker.run_once()
    assert all(p["handle"] != "anna" for p in snapshot(world)["online"]["named"])
    assert world.anna.patch("/me", {"public_presence": True}).status_code == 200
    worker.run_once()
    assert any(p["handle"] == "anna" for p in snapshot(world)["online"]["named"])


def test_a_person_under_a_hold_is_neither_named_nor_counted_online(world: World, hub: Any) -> None:
    seen(world, world.anna_member, clock.now())
    worker = public_snapshot.Worker(world.migrated, hub)
    worker.run_once()
    before = snapshot(world)["online"]["humans"]
    made = report(world.owner, {"type": "profile", "id": world.anna.id}, "spam")
    assert made.status_code == 201, made.text
    path = f"/admin/reports/{made.json()['id']}/resolve"
    assert world.owner.post(path, {"action": "hide"}).status_code == 200
    worker.run_once()
    up = snapshot(world)["online"]
    assert all(p["handle"] != "anna" for p in up["named"])
    assert up["humans"] == before - 1
    assert world.owner.post(path, {"action": "dismiss"}).status_code == 200
    worker.run_once()
    assert snapshot(world)["online"]["humans"] == before


def test_public_presence_off_takes_the_name_off_at_once_also_under_interval(
    world: World, hub: Any
) -> None:
    seen(world, world.anna_member, clock.now())
    public_snapshot.Worker(world.migrated, hub).run_once()
    public_pages.configure(replace(hub, public_pages_render="interval"))
    assert world.anna.patch("/me", {"public_presence": False}).status_code == 200
    assert all(p["handle"] != "anna" for p in snapshot(world)["online"]["named"])


def test_public_presence_never_covers_the_person_s_agents(world: World, hub: Any) -> None:
    bot = world.bot.get("/me").json()["member"]
    resumed = world.bot.resume()  # a live session, called just now: online (§5.3)
    assert resumed.status_code == 200, resumed.text
    world.owner.patch("/me", {"public_presence": False})
    public_snapshot.Worker(world.migrated, hub).run_once()
    named = [p["handle"] for p in snapshot(world)["online"]["named"]]
    assert bot["handle"] in named


def test_a_merge_url_that_is_not_https_is_left_out(world: World) -> None:
    item(world, {**merge("a merge"), "url": "http://github.com/o/r/pull/1"})
    assert [e["url"] for e in snapshot(world)["ticker"]] == [None]
