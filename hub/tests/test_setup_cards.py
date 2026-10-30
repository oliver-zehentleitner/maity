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
    "keep_the_why_ci": "Run the Keep the Why linter in CI",
    "keep_the_why_dashboard": "Publish the Keep the Why dashboard",
    "maity_badge": "Add the Maity badge to the README",
}
KTW = ("keep_the_why_init", "keep_the_why_badge", "keep_the_why_ci", "keep_the_why_dashboard")
KTW_OFF = {key: False for key in KTW}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def _card(owner: flow.Human, card_id: str) -> dict[str, Any]:
    response = owner.get(f"{BASE}/tasks/{card_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_default_options_make_four_cards_in_order(owner: flow.Human) -> None:
    body = flow.project(owner, repository=REPOSITORY)
    setup = body["setup"]
    assert {k: v for k, v in setup.items() if k != "cards"} == {
        "keep_the_why_init": True,
        "keep_the_why_badge": True,
        "keep_the_why_ci": True,
        "keep_the_why_dashboard": True,
        "dashboard_path": "keep-the-why-dashboard",
        "maity_badge": False,
    }
    cards = [_card(owner, i) for i in setup["cards"]]
    assert [c["title"] for c in cards] == [TITLES[k] for k in KTW]
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
    assert "/maintainer/maity/overview)" in cards[-1]["body"]
    assert "/#/" not in cards[-1]["body"]  # a path address, never a hash route (§16.11)


def test_the_badge_is_on_without_a_repository_and_no_card_exists_yet(owner: flow.Human) -> None:
    body = flow.project(owner, setup={"maity_badge": True})
    assert body["policy"]["badge"] == "members"
    assert body["setup"] == {
        "keep_the_why_init": True,
        "keep_the_why_badge": True,
        "keep_the_why_ci": True,
        "keep_the_why_dashboard": True,
        "dashboard_path": "keep-the-why-dashboard",
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
    assert len(cards) == 4 and _card(owner, cards[0])["created_by"] == owner.id
    owner.patch(BASE, {"repository": {**REPOSITORY, "default_branch": "dev"}})
    assert owner.get(BASE).json()["setup"]["cards"] == cards


def test_under_none_only_the_maity_badge_is_offered(owner: flow.Human) -> None:
    body = flow.project(
        owner,
        repository=REPOSITORY,
        memory={"provider": "none"},
        setup={key: True for key in (*KTW, "maity_badge")},
    )
    assert all(body["setup"][key] is False for key in KTW)
    assert body["setup"]["dashboard_path"] is None
    assert [_card(owner, i)["title"] for i in body["setup"]["cards"]] == [TITLES["maity_badge"]]


def test_every_option_off_reads_an_empty_list(owner: flow.Human) -> None:
    body = flow.project(
        owner,
        repository=REPOSITORY,
        setup=KTW_OFF,
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
        ({"keep_the_why_ci": 1}, {"setup.keep_the_why_ci": "not_a_boolean"}),
        ({"keep_the_why_dashboard": None}, {"setup.keep_the_why_dashboard": "not_a_boolean"}),
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
    ids = body["setup"]["cards"]
    waiting = agent.resume().json()["setup"]
    assert waiting == [
        {"id": card_id, "title": TITLES[key], "status": "open", "holder": None}
        for card_id, key in zip(ids, KTW, strict=True)
    ]
    claimed = agent.post(f"{BASE}/tasks/{ids[0]}/claim", {})
    assert claimed.status_code == 200, claimed.text
    assert agent.resume().json()["setup"][0]["holder"] == agent.id
    for card_id in ids:
        owner.patch(f"{BASE}/tasks/{card_id}", {"status": "cancelled"})
    assert "setup" not in agent.resume().json()


def _kinds(engine: Engine) -> list[str]:
    from sqlalchemy import select

    from maity_hub import tables as t

    with engine.connect() as conn:
        return list(conn.execute(select(t.event.c.kind).order_by(t.event.c.seq)).scalars())


def test_a_patch_that_archives_with_the_repository_opens_no_card(owner: flow.Human) -> None:
    flow.project(owner)
    both = owner.patch(BASE, {"repository": REPOSITORY, "state": "archived", "reason": "done"})
    assert both.status_code == 200, both.text
    assert both.json()["state"] == "archived"
    assert both.json()["setup"]["cards"] is None  # judged by the state the PATCH leaves


def test_a_patch_that_brings_the_project_back_with_the_repository_opens_the_cards(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner)
    assert owner.patch(BASE, {"state": "archived", "reason": "pause"}).status_code == 200
    back = owner.patch(BASE, {"repository": REPOSITORY, "state": "build", "reason": "again"})
    assert back.status_code == 200, back.text
    cards = back.json()["setup"]["cards"]
    assert cards is not None and len(cards) == 4  # not lost for good to the old state
    assert [_card(owner, c)["title"] for c in cards] == [TITLES[k] for k in KTW]
    # The project's state_changed comes first, then the cards it opens.
    kinds = _kinds(migrated)
    last_state = max(i for i, k in enumerate(kinds) if k == "state_changed")
    created = [i for i, k in enumerate(kinds) if k == "task_created"]
    assert len(created) == 4 and min(created) > last_state


@pytest.mark.parametrize(
    "path",
    ["docs/why", "a", "a.b_c-d/e1/f/g/h", "x" * 63],
)
def test_a_dashboard_path_in_shape_is_kept_and_named_in_the_card(
    owner: flow.Human, path: str
) -> None:
    body = flow.project(owner, repository=REPOSITORY, setup={"dashboard_path": path})
    assert body["setup"]["dashboard_path"] == path
    dashboard = _card(owner, body["setup"]["cards"][3])
    assert dashboard["title"] == TITLES["keep_the_why_dashboard"]
    assert f"`{path}`" in dashboard["body"]
    assert f"/{path}[/<child directory>]/state.json" in dashboard["body"]
    assert "dashboard-state:" in dashboard["body"]
    assert "default branch, never a direct push" in dashboard["body"]


@pytest.mark.parametrize(
    "path",
    [
        None,
        "",
        7,
        "/docs",
        "docs/",
        "docs//why",
        "Docs",
        "-docs",
        "a..b",
        "docs/../x",
        "a/b/c/d/e/f",
        "x" * 64,
        "dö",
    ],
)
def test_a_dashboard_path_out_of_shape_is_format(owner: flow.Human, path: Any) -> None:
    response = owner.post(
        "/projects", {"slug": "xx", "name": "XX", "setup": {"dashboard_path": path}}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {"setup.dashboard_path": "format"}


@pytest.mark.parametrize(
    "extra",
    [
        {"setup": {"keep_the_why_dashboard": False, "dashboard_path": "docs/../x"}},
        {"setup": {"dashboard_path": "docs/../x"}, "memory": {"provider": "none"}},
    ],
)
def test_a_path_out_of_shape_is_format_even_where_it_would_be_dropped(
    owner: flow.Human, extra: dict[str, Any]
) -> None:
    response = owner.post("/projects", {"slug": "xx", "name": "XX", **extra})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {"setup.dashboard_path": "format"}


def test_the_path_is_dropped_without_the_dashboard_option(owner: flow.Human) -> None:
    body = flow.project(
        owner,
        repository=REPOSITORY,
        setup={"keep_the_why_dashboard": False, "dashboard_path": "docs/why"},
    )
    assert body["setup"]["keep_the_why_dashboard"] is False
    assert body["setup"]["dashboard_path"] is None
    titles = [_card(owner, i)["title"] for i in body["setup"]["cards"]]
    assert TITLES["keep_the_why_dashboard"] not in titles
    assert titles == [TITLES[k] for k in KTW[:3]]


def test_the_ci_card_asks_for_the_lint_step(owner: flow.Human) -> None:
    body = flow.project(owner, repository=REPOSITORY, setup={**KTW_OFF, "keep_the_why_ci": True})
    [card_id] = body["setup"]["cards"]
    card = _card(owner, card_id)
    assert card["title"] == TITLES["keep_the_why_ci"]
    assert "`ktw-lint`" in card["body"] and REPOSITORY["url"] in card["body"]
    assert "lint step green" in card["body"]
    assert body["setup"]["dashboard_path"] is None  # the dashboard option is off
