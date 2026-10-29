"""docs/api.md §6.21: the setup options of a project and the cards made for them."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

REPOSITORY = {"url": "https://github.com/oliver-zehentleitner/maity"}
BASE = "/projects/maintainer/maity"
TITLES = {
    "keep_the_why_init": "Set up Keep the Why in the repository",
    "keep_the_why_badge": "Add the Keep the Why badge to the README",
    "maity_badge": "Add the Maity badge to the README",
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def _card(owner: flow.Human, card_id: str) -> dict[str, Any]:
    response = owner.get(f"{BASE}/tasks/{card_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_default_options_make_two_cards_in_order(owner: flow.Human) -> None:
    body = flow.project(owner, repository=REPOSITORY)
    setup = body["setup"]
    assert [setup[k] for k in ("keep_the_why_init", "keep_the_why_badge", "maity_badge")] == [
        True,
        True,
        False,
    ]
    cards = [_card(owner, i) for i in setup["cards"]]
    assert [c["title"] for c in cards] == [
        TITLES["keep_the_why_init"],
        TITLES["keep_the_why_badge"],
    ]
    first = cards[0]
    assert (first["kind"], first["label"], first["status"], first["area"]) == (
        "setup",
        "chore",
        "open",
        "/",
    )
    assert first["assigned_to"] is None
    assert first["created_by"] == owner.id
    assert "default branch, never a direct push" in first["body"]
    assert REPOSITORY["url"] in first["body"]
    assert body["policy"]["badge"] == "off"


def test_the_maity_badge_option_opens_the_badge_and_a_card_with_the_snippet(
    owner: flow.Human,
) -> None:
    body = flow.project(owner, repository=REPOSITORY, setup={"maity_badge": True})
    assert body["policy"]["badge"] == "members"
    cards = [_card(owner, i) for i in body["setup"]["cards"]]
    assert [c["title"] for c in cards][-1] == TITLES["maity_badge"]
    assert "/badge/maintainer/maity.svg" in cards[-1]["body"]
    assert "/#/maintainer/maity/overview" in cards[-1]["body"]


def test_the_badge_is_on_without_a_repository_and_no_card_exists_yet(owner: flow.Human) -> None:
    body = flow.project(owner, setup={"maity_badge": True})
    assert body["policy"]["badge"] == "members"
    assert body["setup"] == {
        "keep_the_why_init": True,
        "keep_the_why_badge": True,
        "maity_badge": True,
        "cards": None,
    }


def test_setting_the_repository_creates_the_cards_once_by_whoever_set_it(
    owner: flow.Human,
) -> None:
    flow.project(owner)
    response = owner.patch(BASE, {"repository": REPOSITORY})
    assert response.status_code == 200, response.text
    cards = response.json()["setup"]["cards"]
    assert len(cards) == 2 and _card(owner, cards[0])["created_by"] == owner.id
    owner.patch(BASE, {"repository": {**REPOSITORY, "default_branch": "dev"}})
    assert owner.get(BASE).json()["setup"]["cards"] == cards


def test_under_none_only_the_maity_badge_is_offered(owner: flow.Human) -> None:
    body = flow.project(
        owner,
        repository=REPOSITORY,
        memory={"provider": "none"},
        setup={"keep_the_why_init": True, "keep_the_why_badge": True, "maity_badge": True},
    )
    assert body["setup"]["keep_the_why_init"] is False
    assert body["setup"]["keep_the_why_badge"] is False
    assert [_card(owner, i)["title"] for i in body["setup"]["cards"]] == [TITLES["maity_badge"]]


def test_every_option_off_reads_an_empty_list(owner: flow.Human) -> None:
    body = flow.project(
        owner,
        repository=REPOSITORY,
        setup={"keep_the_why_init": False, "keep_the_why_badge": False},
    )
    assert body["setup"]["cards"] == []


def test_a_closed_project_gets_no_card_from_a_repository(owner: flow.Human) -> None:
    flow.project(owner)
    closed = owner.patch(BASE, {"state": "archived", "reason": "done"})
    assert closed.status_code == 200, closed.text
    after = owner.patch(BASE, {"repository": REPOSITORY})
    assert after.status_code == 200, after.text
    assert after.json()["setup"]["cards"] is None


def test_the_options_are_checked(owner: flow.Human) -> None:
    for setup, fields in (
        ({"maity_badge": "yes"}, {"setup.maity_badge": "not_a_boolean"}),
        ({"nope": True}, {"setup.nope": "unknown_field"}),
    ):
        response = owner.post("/projects", {"slug": "xx", "name": "XX", "setup": setup})
        assert response.status_code == 400
        assert response.json()["error"]["details"]["fields"] == fields


def test_setup_is_not_patchable_and_no_client_creates_a_setup_card(owner: flow.Human) -> None:
    flow.project(owner)
    patched = owner.patch(BASE, {"setup": {"maity_badge": True}})
    assert patched.status_code == 400
    assert patched.json()["error"]["details"]["fields"] == {"setup": "read_only"}
    created = owner.post(f"{BASE}/tasks", {"kind": "setup", "title": "x", "body": "y"})
    assert created.status_code == 400
    assert created.json()["error"]["details"]["fields"] == {"kind": "hub_only"}


def test_a_project_that_predates_the_field_reads_null_and_gets_no_card(
    owner: flow.Human, migrated: Engine
) -> None:
    from sqlalchemy import update

    from maity_hub import tables as t

    flow.project(owner)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(setup=None))
    response = owner.patch(BASE, {"repository": REPOSITORY})
    assert response.json()["setup"] is None


def test_the_packet_names_the_waiting_setup_cards(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    body = flow.project(owner, repository=REPOSITORY)
    agent = flow.agent(make_client, owner)
    first, second = body["setup"]["cards"]
    waiting = agent.resume().json()["setup"]
    assert waiting == [
        {"id": first, "title": TITLES["keep_the_why_init"], "status": "open", "holder": None},
        {"id": second, "title": TITLES["keep_the_why_badge"], "status": "open", "holder": None},
    ]
    claimed = agent.post(f"{BASE}/tasks/{first}/claim", {})
    assert claimed.status_code == 200, claimed.text
    assert agent.resume().json()["setup"][0]["holder"] == agent.id
    owner.patch(f"{BASE}/tasks/{first}", {"status": "cancelled"})
    owner.patch(f"{BASE}/tasks/{second}", {"status": "cancelled"})
    assert "setup" not in agent.resume().json()
