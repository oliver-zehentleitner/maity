"""docs/api.md §16.9: a person's public page, and `public_profile` and `public_bio` of
`PATCH /me`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, moderation, public_pages, public_people
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_account_deletion import admin_first, ask_deletion, person, press, token_of
from tests.test_moderation import resolve
from tests.test_reports import report  # noqa: F401  (the fixture)
from tests.test_reports import team as team
from tests.test_two_factor import Clock
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)


def pages(make_client: ClientFactory) -> ClientFactory:
    """A client factory for a hub that serves pages."""
    return lambda **kw: make_client(public_pages=True, **kw)


def visitor(make_client: ClientFactory) -> Any:
    return make_client(public_pages=True)


def shown(client: Any, handle: str = "maintainer") -> str | None:
    """The page's text, or None when the address is the app shell."""
    got = client.get(f"/{handle}")
    assert got.status_code == 200
    return None if "<title>dashboard</title>" in got.text else str(got.text)


def test_a_person_is_private_until_they_choose(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(pages(make_client), migrated)
    own = who.get("/me").json()["member"]
    assert (own["public_profile"], own["public_bio"]) == (False, None)
    assert shown(visitor(make_client)) is None


def test_turning_the_page_on_publishes_it_and_off_takes_it_away_at_once(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(pages(make_client), migrated)
    anyone = visitor(make_client)
    set_ = who.patch("/me", {"public_profile": True, "public_bio": "I build agents."})
    assert set_.status_code == 200, set_.text
    assert set_.json()["member"]["public_profile"] is True
    assert who.get("/me").json()["member"]["public_bio"] == "I build agents."
    text = shown(anyone)
    assert text is not None
    assert "<h1>" in text and "I build agents." in text and "maintainer" in text
    assert '<link rel="canonical" href="https://hub.example/maintainer">' in text
    assert "<title>" in text and "<script" not in text
    # off: the page is gone in the same call
    assert who.patch("/me", {"public_profile": False}).status_code == 200
    assert shown(anyone) is None
    # and a stored bio stays the person's own
    assert who.get("/me").json()["member"]["public_bio"] == "I build agents."


def test_editing_the_bio_renders_the_page_again(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(pages(make_client), migrated)
    anyone = visitor(make_client)
    who.patch("/me", {"public_profile": True, "public_bio": "first words"})
    first = anyone.get("/maintainer")
    who.patch("/me", {"public_bio": "second <b>words</b>"})
    second = anyone.get("/maintainer")
    assert "first words" not in second.text
    assert "second &lt;b&gt;words&lt;/b&gt;" in second.text  # text, never markup
    assert second.headers["etag"] != first.headers["etag"]
    who.patch("/me", {"public_bio": None})  # cleared
    assert "second" not in anyone.get("/maintainer").text
    assert who.get("/me").json()["member"]["public_bio"] is None


@pytest.mark.parametrize(
    ("bio", "problem"),
    [
        ("a" * 281, "too_long"),
        ("line\nbreak", "control_character"),
        ("tab\there", "control_character"),
        ("nul\x00", "control_character"),
        ("flip ‮ this", "control_character"),
        ("isolate ⁦ this", "control_character"),
    ],
)
def test_a_bio_the_contract_refuses_is_invalid(
    make_client: ClientFactory, migrated: Engine, bio: str, problem: str
) -> None:
    who = flow.human(make_client, migrated)
    refused = who.patch("/me", {"public_bio": bio})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"public_bio": problem}
    assert who.get("/me").json()["member"]["public_bio"] is None


def test_a_bio_of_280_characters_and_an_empty_text(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(make_client, migrated)
    assert who.patch("/me", {"public_bio": "ä" * 280}).status_code == 200
    assert who.patch("/me", {"public_bio": ""}).json()["member"]["public_bio"] is None


def test_a_patch_that_changes_nothing_is_refused_and_a_null_switch_too(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(make_client, migrated)
    assert who.patch("/me", {}).status_code == 400
    assert who.patch("/me", {"public_profile": None}).status_code == 400


def test_an_agent_sets_neither_field(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    bot = flow.agent(make_client, owner, role="admin")
    for body in ({"public_profile": True}, {"public_bio": "hello"}):
        refused = bot.patch("/me", body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"]["reason"] == "humans_only"


def test_a_suspended_person_has_no_page_and_gets_it_back_when_the_suspension_is_lifted(
    make_client: ClientFactory, migrated: Engine, settings: Any
) -> None:
    from dataclasses import replace

    who = flow.human(pages(make_client), migrated)
    anyone = visitor(make_client)
    who.patch("/me", {"public_profile": True, "public_bio": "here"})
    assert shown(anyone) is not None
    with migrated.begin() as conn:
        conn.execute(update(t.human).values(suspended_at=clock.now(), suspended_report="x"))
        public_pages.configure(replace(settings, public_pages=True))
        public_pages.touch(conn, "person", who.id)
    assert shown(anyone) is None
    with migrated.begin() as conn:
        assert moderation.unsuspend(conn, who.id) is True
    assert shown(anyone) is not None


def test_a_deleted_person_has_no_page(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(pages(make_client), migrated, moment)
    anyone = visitor(make_client)
    assert pat.patch("/me", {"public_profile": True, "public_bio": "hello"}).status_code == 200
    assert shown(anyone, "pat") is not None
    assert ask_deletion(pat).status_code == 202
    assert press(pat, token_of(migrated)).status_code == 200
    assert shown(anyone, "pat") is None
    with migrated.connect() as conn:
        assert conn.execute(select(t.public_page)).all() == []
        row = conn.execute(select(t.human).where(t.human.c.id == pat.id)).one()
        assert (row.public_profile, row.public_bio) == (
            False,
            None,
        )  # the text goes with the person
        assert public_people.targets(conn) == []


def test_a_person_waiting_for_approval_has_no_page(
    make_client: ClientFactory, migrated: Engine, settings: Any
) -> None:
    from dataclasses import replace

    who = flow.human(pages(make_client), migrated)
    anyone = visitor(make_client)
    who.patch("/me", {"public_profile": True})
    with migrated.begin() as conn:
        conn.execute(update(t.human).values(account_status="pending"))
        public_pages.configure(replace(settings, public_pages=True))
        public_pages.touch(conn, "person", who.id)
    assert shown(anyone) is None


def test_the_sitemap_lists_the_page_and_the_instance_switch_hides_it(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(pages(make_client), migrated)
    who.patch("/me", {"public_profile": True})
    listed = visitor(make_client).get("/sitemap.xml")
    assert "<loc>https://hub.example/maintainer</loc>" in listed.text
    # a hub without the switch serves nothing, whatever the person chose
    assert "dashboard" in make_client().get("/maintainer").text


def test_only_people_who_chose_are_targets(migrated: Engine) -> None:
    factory.human(migrated, "alice")
    bob = factory.human(migrated, "bob")
    with migrated.begin() as conn:
        conn.execute(update(t.human).where(t.human.c.id == bob).values(public_profile=True))
    with migrated.connect() as conn:
        assert public_people.targets(conn) == [bob]


def test_a_hidden_profile_cannot_be_made_public_again_until_the_hold_is_lifted(
    team: dict[str, Any], migrated: Engine
) -> None:
    pat = team["pat"]
    assert pat.patch("/me", {"public_profile": True}).status_code == 200
    made = report(team["owner"], {"type": "profile", "id": pat.id}, "impersonation").json()
    assert resolve(team, made["id"], "hide").status_code == 200
    assert pat.patch("/me", {"public_profile": False}).status_code == 200  # off is the person's
    refused = pat.patch("/me", {"public_profile": True})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "moderation_hold"
    assert (
        pat.patch("/me", {"public_bio": "still mine"}).status_code == 200
    )  # the text is not the switch
    assert resolve(team, made["id"], "dismiss").status_code == 200
    assert pat.patch("/me", {"public_profile": True}).status_code == 200
