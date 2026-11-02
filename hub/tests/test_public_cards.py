"""docs/api.md §16.9, "Card": a card's own public page at its dashboard address, with its text,
while the project's page is served; never its notes, never a held card, a `security` card only
once it is done."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, public_pages
from maity_hub import tables as t
from tests.conftest import ClientFactory
from tests.test_public_project_views import BASE, TASKS, World, view
from tests.test_reports import report


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, settings: Any) -> World:
    public_pages.configure(replace(settings, public_pages=True))
    return World(make_client, migrated)


def page(world: World, card_id: str) -> str | None:
    return view(world.anyone, f"tasks/{card_id}")


def data(world: World, card_id: str) -> Any:
    return world.anyone.get(f"/api/v1/public/pages{BASE}/tasks/{card_id}")


def test_a_card_has_a_page_with_its_text_at_the_dashboard_address(world: World) -> None:
    made = world.owner.post(TASKS, {"title": "Fix the *pager*", "body": "## Steps\n\n- one\n- two"})
    assert made.status_code == 201, made.text
    card_id = made.json()["id"]
    text = page(world, card_id)
    assert text is not None and "<script" not in text
    assert "<h1>Fix the *pager*</h1>" in text and "<h2>Steps</h2>" in text
    assert "<li>one</li>" in text
    assert f'<link rel="canonical" href="https://hub.example{BASE}/tasks/{card_id}">' in text
    got = data(world, card_id)
    assert got.status_code == 200, got.text
    assert got.json()["kind"] == "card"
    assert set(got.json()["data"]) == {"id", "title", "status", "label", "holder", "body", "notes"}
    assert got.json()["data"]["body"] == "## Steps\n\n- one\n- two"
    sitemap = world.anyone.get("/sitemap.xml").text
    assert f"https://hub.example{BASE}/tasks/{card_id}" in sitemap


def test_raw_html_in_the_text_stays_text(world: World) -> None:
    made = world.owner.post(
        TASKS, {"title": "<b>t</b>", "body": "<script>alert(1)</script> [x](javascript:alert(1))"}
    )
    text = page(world, made.json()["id"]) or ""
    assert "<script>alert" not in text and "&lt;script&gt;" in text
    assert 'href="javascript' not in text
    assert "<b>t</b>" not in text


def test_the_board_links_each_card_to_its_page(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Linked"}).json()["id"]
    board = view(world.anyone, "board") or ""
    assert f'href="{BASE}/tasks/{card_id}"' in board


def test_the_notes_are_on_the_page_with_their_authors_named_as_the_holder(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "With notes", "body": "public words"}).json()["id"]
    first = world.owner.post(f"{TASKS}/{card_id}/notes", {"body": "A *finding* <script>x</script>"})
    assert first.status_code == 201, first.text
    second = world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "anna-note-words"})
    assert second.status_code == 201, second.text
    text = page(world, card_id) or ""
    assert "<h2>Notes</h2>" in text and "<em>finding</em>" in text
    assert "<script>x" not in text and "anna-note-words" in text
    assert "Human anna (anna)" not in text and "a member" in text
    notes = data(world, card_id).json()["data"]["notes"]
    assert [n["body"] for n in notes] == ["A *finding* <script>x</script>", "anna-note-words"]
    assert set(notes[0]) == {"id", "author", "body", "state", "created_at", "redacted", "edited"}
    assert notes[1]["author"] == "member" and notes[1]["state"] == "open"
    resolved = world.owner.post(
        f"{TASKS}/{card_id}/notes/{second.json()['id']}/resolve", {"state": "dismissed"}
    )
    assert resolved.status_code == 200, resolved.text
    assert data(world, card_id).json()["data"]["notes"][1]["state"] == "dismissed"
    assert "dismissed" in (page(world, card_id) or "")


def test_a_note_author_follows_their_profile(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Noted by anna"}).json()["id"]
    world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "from anna"})
    world.anna.patch("/me", {"public_profile": True})
    assert data(world, card_id).json()["data"]["notes"][0]["author"]["handle"] == "anna"
    assert "Human anna (anna)" in (page(world, card_id) or "")
    world.anna.patch("/me", {"public_profile": False})
    assert data(world, card_id).json()["data"]["notes"][0]["author"] == "member"
    assert "(anna)" not in (page(world, card_id) or "")


def test_a_redacted_note_shows_as_removed_without_its_text_or_reason(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Leaky"}).json()["id"]
    note = world.owner.post(f"{TASKS}/{card_id}/notes", {"body": "canary-secret-words"}).json()
    assert "canary-secret-words" in (page(world, card_id) or "")
    redacted = world.owner.post(
        f"{TASKS}/{card_id}/notes/{note['id']}/redact", {"reason": "canary-reason-words"}
    )
    assert redacted.status_code == 200, redacted.text
    text = page(world, card_id) or ""
    assert "canary-secret-words" not in text and "canary-reason-words" not in text
    assert "Removed." in text
    got = data(world, card_id)
    assert "canary-secret-words" not in got.text and "canary-reason-words" not in got.text
    assert got.json()["data"]["notes"][0]["redacted"] is True
    assert got.json()["data"]["notes"][0]["body"] is None


def test_an_edited_note_shows_its_mark_and_reason_never_the_old_text(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Edited"}).json()["id"]
    note = world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "canary-old-words"}).json()
    assert "canary-old-words" in (page(world, card_id) or "")
    edited = world.owner.patch(
        f"{TASKS}/{card_id}/notes/{note['id']}",
        {"body": "canary-new-words", "reason": "canary-reason-words"},
    )
    assert edited.status_code == 200, edited.text
    text = page(world, card_id) or ""
    assert "canary-old-words" not in text and "canary-new-words" in text
    assert "edited by" in text and "canary-reason-words" in text
    got = data(world, card_id)
    assert "canary-old-words" not in got.text
    shown = got.json()["data"]["notes"][0]
    assert shown["body"] == "canary-new-words" and shown["author"] == "member"
    assert shown["edited"]["reason"] == "canary-reason-words" and shown["edited"]["at"]


def test_an_edit_renders_the_page_at_once_also_under_interval(world: World, settings: Any) -> None:
    card_id = world.owner.post(TASKS, {"title": "Edited on interval"}).json()["id"]
    note = world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "canary-old-words"}).json()
    assert "canary-old-words" in (page(world, card_id) or "")
    public_pages.configure(replace(settings, public_pages=True, public_pages_render="interval"))
    edited = world.anna.patch(f"{TASKS}/{card_id}/notes/{note['id']}", {"body": "canary-new"})
    assert edited.status_code == 200, edited.text
    text = page(world, card_id) or ""
    assert "canary-old-words" not in text and "canary-new" in text
    assert "canary-old-words" not in data(world, card_id).text


def test_the_editor_of_anothers_note_follows_their_profile(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Edited by the owner"}).json()["id"]
    note = world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "from anna"}).json()
    world.owner.patch("/me", {"public_profile": True})
    edited = world.owner.patch(
        f"{TASKS}/{card_id}/notes/{note['id']}", {"body": "from anna, cleaned", "reason": "typo"}
    )
    assert edited.status_code == 200, edited.text
    handle = edited.json()["edited"]["by"]["handle"]
    assert data(world, card_id).json()["data"]["notes"][0]["edited"]["by"]["handle"] == handle
    assert f"({handle})" in (page(world, card_id) or "")
    # The owner is neither the card's holder nor a note's author on it.
    world.owner.patch("/me", {"public_profile": False})
    assert data(world, card_id).json()["data"]["notes"][0]["edited"]["by"] == "member"
    assert f"({handle})" not in (page(world, card_id) or "")


def test_a_security_card_has_a_page_only_once_it_is_done(world: World) -> None:
    hidden = world.card(title="Secret hole", label="Security", body="the exploit")
    fixed = world.card(title="Fixed hole", label="security", status="done", closed_at=clock.now())
    with world.migrated.begin() as conn:
        public_pages.touch(conn, "card", hidden)
        public_pages.touch(conn, "card", fixed)
    assert page(world, hidden) is None and data(world, hidden).status_code == 404
    assert page(world, fixed) is not None


def test_a_held_card_has_no_page_and_comes_back_when_the_report_is_dismissed(
    world: World,
) -> None:
    card_id = world.owner.post(TASKS, {"title": "Spammy", "body": "spam words"}).json()["id"]
    got = report(world.anna, {"type": "card", "id": card_id, "project": "maintainer/maity"}, "spam")
    assert got.status_code == 201, got.text

    def resolved(action: str) -> None:
        done = world.owner.post(f"/admin/reports/{got.json()['id']}/resolve", {"action": action})
        assert done.status_code == 200, done.text

    resolved("hide")
    assert page(world, card_id) is None
    resolved("dismiss")
    assert "spam words" in (page(world, card_id) or "")


def test_the_card_pages_follow_the_project_page(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Follows"}).json()["id"]
    assert page(world, card_id) is not None
    world.owner.patch("/projects/maintainer/maity", {"public_page": "off"})
    assert page(world, card_id) is None
    with world.migrated.connect() as conn:
        assert (
            conn.execute(select(t.public_page.c.path).where(t.public_page.c.kind == "card")).first()
            is None
        )


def test_the_holder_is_named_as_the_board_names_them(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Held by a bot"}).json()["id"]
    claimed = world.bot.post(f"{TASKS}/{card_id}/claim", {})
    assert claimed.status_code == 200, claimed.text
    holder = data(world, card_id).json()["data"]["holder"]
    assert holder == "agent"  # the owner's profile is not public in this world
    assert "an agent" in (page(world, card_id) or "")


def test_the_holder_on_a_card_page_follows_their_profile(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Held by anna"}).json()["id"]
    with world.migrated.begin() as conn:
        conn.execute(
            t.card.update()
            .where(t.card.c.id == card_id)
            .values(claim_holder=world.anna_member, status="in_progress")
        )
        public_pages.touch(conn, "card", card_id)
    assert data(world, card_id).json()["data"]["holder"] == "member"
    world.anna.patch("/me", {"public_profile": True})
    assert data(world, card_id).json()["data"]["holder"]["handle"] == "anna"
    assert "Human anna (anna)" in (page(world, card_id) or "")
    world.anna.patch("/me", {"public_profile": False})
    assert data(world, card_id).json()["data"]["holder"] == "member"
    assert "(anna)" not in (page(world, card_id) or "")
