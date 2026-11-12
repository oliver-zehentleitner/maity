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
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import count_statements
from tests.test_public_project_views import BASE, TASKS, World, pages, view
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
    assert "Human anna (anna)" in text
    notes = data(world, card_id).json()["data"]["notes"]
    assert [n["body"] for n in notes] == ["A *finding* <script>x</script>", "anna-note-words"]
    assert set(notes[0]) == {"id", "author", "body", "state", "created_at", "redacted", "edited"}
    assert notes[1]["author"]["handle"] == "anna" and notes[1]["state"] == "open"
    resolved = world.owner.post(
        f"{TASKS}/{card_id}/notes/{second.json()['id']}/resolve", {"state": "dismissed"}
    )
    assert resolved.status_code == 200, resolved.text
    assert data(world, card_id).json()["data"]["notes"][1]["state"] == "dismissed"
    assert "dismissed" in (page(world, card_id) or "")


def test_a_note_author_follows_their_name(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Noted by anna"}).json()["id"]
    world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "from anna"})
    assert data(world, card_id).json()["data"]["notes"][0]["author"]["handle"] == "anna"
    assert world.anna.patch("/me", {"handle": "anne"}).status_code == 200
    assert data(world, card_id).json()["data"]["notes"][0]["author"]["handle"] == "anne"
    assert "(anne)" in (page(world, card_id) or "")


def test_a_redacted_note_shows_as_removed_without_its_text_or_reason(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Leaky"}).json()["id"]
    note = world.owner.post(f"{TASKS}/{card_id}/notes", {"body": "canary-secret-words"}).json()
    assert "canary-secret-words" in (page(world, card_id) or "")
    redacted = world.owner.post(
        f"{TASKS}/{card_id}/notes/{note['id']}/redact",
        {"reason": "canary-reason-words", "base_version": note["version"]},
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
        {"body": "canary-new-words", "reason": "canary-reason-words", "base_version": 1},
    )
    assert edited.status_code == 200, edited.text
    text = page(world, card_id) or ""
    assert "canary-old-words" not in text and "canary-new-words" in text
    assert "edited by" in text and "canary-reason-words" in text
    got = data(world, card_id)
    assert "canary-old-words" not in got.text
    shown = got.json()["data"]["notes"][0]
    assert shown["body"] == "canary-new-words" and shown["author"]["handle"] == "anna"
    assert shown["edited"]["reason"] == "canary-reason-words" and shown["edited"]["at"]


def test_an_edit_renders_the_page_at_once_also_under_interval(world: World, settings: Any) -> None:
    card_id = world.owner.post(TASKS, {"title": "Edited on interval"}).json()["id"]
    note = world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "canary-old-words"}).json()
    assert "canary-old-words" in (page(world, card_id) or "")
    public_pages.configure(replace(settings, public_pages=True, public_pages_render="interval"))
    edited = world.anna.patch(
        f"{TASKS}/{card_id}/notes/{note['id']}", {"body": "canary-new", "base_version": 1}
    )
    assert edited.status_code == 200, edited.text
    text = page(world, card_id) or ""
    assert "canary-old-words" not in text and "canary-new" in text
    assert "canary-old-words" not in data(world, card_id).text


def test_the_editor_of_anothers_note_is_named_whatever_their_profile_and_a_hold_hides_them(
    world: World,
) -> None:
    card_id = world.owner.post(TASKS, {"title": "Edited by the owner"}).json()["id"]
    note = world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "from anna"}).json()
    world.owner.patch("/me", {"public_profile": False})  # off is not invisible (§16.9)
    edited = world.owner.patch(
        f"{TASKS}/{card_id}/notes/{note['id']}",
        {"body": "from anna, cleaned", "reason": "typo", "base_version": 1},
    )
    assert edited.status_code == 200, edited.text
    handle = edited.json()["edited"]["by"]["handle"]
    assert data(world, card_id).json()["data"]["notes"][0]["edited"]["by"]["handle"] == handle
    assert f"({handle})" in (page(world, card_id) or "")
    # The owner is neither the card's holder nor a note's author on it.
    made = report(world.anna, {"type": "profile", "id": world.owner.id}, "impersonation")
    assert made.status_code == 201, made.text
    resolved = world.owner.post(f"/admin/reports/{made.json()['id']}/resolve", {"action": "hide"})
    assert resolved.status_code == 200, resolved.text
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
    agent = world.bot.get("/me").json()["member"]
    assert holder["handle"] == agent["handle"]
    assert f"({agent['handle']})" in (page(world, card_id) or "")


def test_the_holder_on_a_card_page_follows_their_name_and_a_hold(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Held by anna"}).json()["id"]
    with world.migrated.begin() as conn:
        conn.execute(
            t.card.update()
            .where(t.card.c.id == card_id)
            .values(claim_holder=world.anna_member, status="in_progress")
        )
        public_pages.touch(conn, "card", card_id)
    assert data(world, card_id).json()["data"]["holder"]["handle"] == "anna"
    assert world.anna.patch("/me", {"handle": "anne"}).status_code == 200
    assert data(world, card_id).json()["data"]["holder"]["handle"] == "anne"
    made = report(world.owner, {"type": "profile", "id": world.anna.id}, "impersonation")
    assert made.status_code == 201, made.text
    path = f"/admin/reports/{made.json()['id']}/resolve"
    assert world.owner.post(path, {"action": "hide"}).status_code == 200
    assert data(world, card_id).json()["data"]["holder"] == "member"
    assert "(anna)" not in (page(world, card_id) or "")


def test_every_kind_reads_one_target_by_the_rule_of_its_whole_list(world: World) -> None:
    """`targets(conn, among)` is the list's own query narrowed to the ids: the cleanup of
    `render_all` decides each candidate by it (tsk-ay4htr4s4w88), so a kind must answer one id
    exactly as its whole list does, before and after the project goes off."""
    world.card(status="open", title="Public while the page is")

    def check(known: dict[str, list[str]]) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        with world.migrated.connect() as conn:
            for name, kind in public_pages.KINDS.items():
                every = found[name] = kind.targets(conn)
                assert kind.targets(conn, every) == every, name
                for target_id in sorted({*known.get(name, []), *every}):
                    expected = [target_id] if target_id in every else []
                    assert kind.targets(conn, [target_id]) == expected, (name, target_id)
                assert kind.targets(conn, ["nothing-by-this-id"]) == [], name
                assert kind.targets(conn, []) == [], name
        return found

    before = check({})
    assert all(before[name] for name in ("project", "card", "person", "agent")), before
    world.owner.patch("/projects/maintainer/maity", {"public_page": "off"})
    after = check(before)
    assert not after["project"] and not after["card"], after


def _remove_agent(world: World) -> None:
    gone = world.owner.client.delete(
        f"/api/v1/agents/{world.bot.id}?cascade=true", headers={"X-CSRF-Token": world.owner.csrf}
    )
    assert gone.status_code == 200, gone.text


def test_a_removed_member_is_off_every_card_page_that_named_them(world: World) -> None:
    """A member's removal takes their name off the card pages that named them, as holder or
    as a note's author, and leaves the others as they were (hub/context/public-pages.md
    fe966f9c)."""
    held = world.owner.post(TASKS, {"title": "Held by the bot"}).json()["id"]
    assert world.bot.post(f"{TASKS}/{held}/claim", {}).status_code == 200
    noted = world.owner.post(TASKS, {"title": "Noted by the bot"}).json()["id"]
    assert world.bot.post(f"{TASKS}/{noted}/notes", {"body": "bot-words"}).status_code == 201
    other = world.owner.post(TASKS, {"title": "Nothing of the bot"}).json()["id"]
    handle = world.bot.get("/me").json()["member"]["handle"]
    assert all(f"({handle})" in (page(world, c) or "") for c in (held, noted))
    with world.migrated.connect() as conn:
        before = conn.execute(
            select(t.public_page.c.path, t.public_page.c.body).where(
                t.public_page.c.path.like(f"%/tasks/{other}%")
            )
        ).all()
    assert before
    _remove_agent(world)
    assert all(f"({handle})" not in (page(world, c) or "") for c in (held, noted))
    assert "bot-words" in (page(world, noted) or "")  # the note stays, its author unnamed
    with world.migrated.connect() as conn:
        after = conn.execute(
            select(t.public_page.c.path, t.public_page.c.body).where(
                t.public_page.c.path.like(f"%/tasks/{other}%")
            )
        ).all()
    assert after == before


@pytest.mark.parametrize("way", ["removed", "isolated"])
def test_a_card_held_in_review_or_blocked_loses_its_holder_when_they_go(
    make_client: ClientFactory, world: World, way: str
) -> None:
    """A removal or an isolation gives the member's cards back before its event, which then
    no longer finds them by their holder; a card in `review` or `blocked` keeps its status, so
    no card event renders it either. Its page is touched with the release (`tell_released`)
    and names no holder after it (fp3y on #1700)."""
    agent = flow.agent(pages(make_client), world.owner, role="coder")
    handle = agent.get("/me").json()["member"]["handle"]
    held = {}
    for status in ("review", "blocked"):
        card_id = world.owner.post(TASKS, {"title": f"Held in {status}"}).json()["id"]
        assert agent.post(f"{TASKS}/{card_id}/claim", {}).status_code == 200
        with world.migrated.begin() as conn:
            conn.execute(t.card.update().where(t.card.c.id == card_id).values(status=status))
            public_pages.touch(conn, "card", card_id)
        assert data(world, card_id).json()["data"]["holder"]["handle"] == handle
        held[status] = card_id
    path = f"/projects/maintainer/maity/members/{agent.id}"
    gone = (
        world.owner.delete(path)
        if way == "removed"
        else world.owner.post(f"{path}/isolate", {"reason": "it broke main"})
    )
    assert gone.status_code == 200, gone.text
    for status, card_id in held.items():
        shown = data(world, card_id).json()["data"]
        assert shown["status"] == status and shown["holder"] is None, shown
        assert f"({handle})" not in (page(world, card_id) or "")


def test_a_removed_member_is_off_the_page_of_a_done_card_they_held(world: World) -> None:
    """A done card keeps its holder (`cards.open_claims` leaves it out of the release), so
    only `public_cards.naming` finds its page by the holder after a removal."""
    card_id = world.owner.post(TASKS, {"title": "Done by the bot"}).json()["id"]
    assert world.bot.post(f"{TASKS}/{card_id}/claim", {}).status_code == 200
    with world.migrated.begin() as conn:
        conn.execute(t.card.update().where(t.card.c.id == card_id).values(status="done"))
        public_pages.touch(conn, "card", card_id)
    handle = world.bot.get("/me").json()["member"]["handle"]
    assert f"({handle})" in (page(world, card_id) or "")
    _remove_agent(world)
    assert f"({handle})" not in (page(world, card_id) or "")


def test_a_removed_editor_is_off_the_card_page_of_the_note_they_edited(
    make_client: ClientFactory, world: World
) -> None:
    ben = flow.human(pages(make_client), world.migrated, "ben")
    factory.membership(world.migrated, world.project_id, "admin", human_id=ben.id)
    card_id = world.owner.post(TASKS, {"title": "Edited by ben"}).json()["id"]
    note = world.anna.post(f"{TASKS}/{card_id}/notes", {"body": "from anna"}).json()
    edited = ben.patch(
        f"{TASKS}/{card_id}/notes/{note['id']}",
        {"body": "from anna, cleaned", "reason": "typo", "base_version": 1},
    )
    assert edited.status_code == 200, edited.text
    assert "(ben)" in (page(world, card_id) or "")
    removed = world.owner.delete(f"/projects/maintainer/maity/members/{ben.id}")
    assert removed.status_code == 200, removed.text
    assert "(ben)" not in (page(world, card_id) or "")


def test_a_member_s_removal_does_not_grow_with_the_project_s_cards(
    make_client: ClientFactory, world: World
) -> None:
    """A public project's card pages are not all removed and rendered again for one member
    (tsk-m65g76c979jk: 31,871 statements on a project with many cards). Three removals in a
    row, each with one more deleted profile behind it: nine cards more before the third add
    nothing to what the second added to the first."""
    agents = [flow.agent(pages(make_client), world.owner, role="coder") for _ in range(3)]

    def removal(agent: flow.Agent, cards: int) -> int:
        for n in range(cards):
            world.card(status="open", title=f"Card {n}")
        world.touch()
        return count_statements(
            world.migrated,
            lambda: world.owner.client.delete(
                f"/api/v1/agents/{agent.id}?cascade=true",
                headers={"X-CSRF-Token": world.owner.csrf},
            ),
        )

    first, second, third = removal(agents[0], 3), removal(agents[1], 0), removal(agents[2], 9)
    assert third - second == second - first, (first, second, third)
