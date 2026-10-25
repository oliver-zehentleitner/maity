"""docs/api.md §6.1, §6.21, §5.2: the project's memory provider and its setup cards."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

REPO = {"url": "https://github.com/oliver-zehentleitner/maity"}
TITLES = [
    "Set up Keep the Why in the repository",
    "Add the Keep the Why badge to the README",
    "Add the Maity badge to the README",
]


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def create(owner: flow.Human, **body: Any) -> Any:
    return owner.post("/projects", {"slug": "maity", "name": "Maity", **body})


def cards(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.card).where(t.card.c.kind == "setup").order_by(t.card.c.created_at)
            )
        )


def task_created(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.event).where(t.event.c.kind == "task_created")))


def test_a_new_project_uses_keep_the_why_and_waits_for_its_repository(
    owner: flow.Human, migrated: Engine
) -> None:
    body = create(owner).json()
    assert body["memory"] == {"provider": "keep-the-why"} and body["keep_the_why"] is True
    assert body["setup"] == {
        "keep_the_why_init": True,
        "keep_the_why_badge": True,
        "maity_badge": False,
        "cards": None,
    }
    assert cards(migrated) == []  # nothing to set up without a repository


def test_a_project_with_a_repository_gets_one_card_per_option_in_order(
    owner: flow.Human, migrated: Engine
) -> None:
    body = create(owner, repository=REPO, setup={"maity_badge": True}).json()
    made = cards(migrated)
    assert [c.title for c in made] == TITLES
    assert body["setup"]["cards"] == [c.id for c in made]
    for card in made:
        assert (card.status, card.label, card.area, card.assigned_to) == (
            "open",
            "chore",
            "/",
            None,
        )
        assert REPO["url"] in card.body and "pull request" in card.body
        assert "never a direct push" in card.body and "`code: false`" in card.body
    snippet = (
        "[![maity](https://hub.example/badge/maity.svg)](https://hub.example/#/p/maity/overview)"
    )
    assert snippet in made[2].body
    with migrated.connect() as conn:
        creator = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == owner.id)
        ).scalar_one()
    assert {c.created_by for c in made} == {creator}
    events = task_created(migrated)
    assert [e.subject_id for e in events] == [c.id for c in made]
    card = owner.get(f"/projects/maity/tasks/{made[0].id}").json()
    assert card["kind"] == "setup"


def test_without_a_memory_provider_only_the_maity_badge_is_offered(
    owner: flow.Human, migrated: Engine
) -> None:
    body = create(
        owner,
        repository=REPO,
        memory={"provider": "none"},
        setup={"keep_the_why_init": True, "maity_badge": True},
    ).json()
    assert body["keep_the_why"] is False and body["memory"] == {"provider": "none"}
    assert body["setup"]["keep_the_why_init"] is False
    assert [c.title for c in cards(migrated)] == [TITLES[2]]


def test_every_option_off_is_processed_with_nothing_to_create(
    owner: flow.Human, migrated: Engine
) -> None:
    off = {"keep_the_why_init": False, "keep_the_why_badge": False, "maity_badge": False}
    body = create(owner, repository=REPO, setup=off).json()
    assert body["setup"]["cards"] == [] and cards(migrated) == []


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"memory": {"provider": "notion"}}, {"memory.provider": "unknown_provider"}),
        ({"setup": {"readme": True}}, {"setup.readme": "unknown_field"}),
        ({"setup": {"maity_badge": "yes"}}, {"setup.maity_badge": "not_a_boolean"}),
        (
            {"memory": {"provider": "none"}, "keep_the_why": True},
            {"keep_the_why": "conflicts_with_memory"},
        ),
    ],
)
def test_the_choice_is_validated(owner: flow.Human, body: dict[str, Any], fields: Any) -> None:
    refused = create(owner, **body)
    assert refused.status_code == 400 and refused.json()["error"]["details"]["fields"] == fields


def test_the_alias_still_chooses_the_provider(owner: flow.Human) -> None:
    assert create(owner, keep_the_why=False).json()["memory"] == {"provider": "none"}


def test_a_patch_changes_the_provider_never_the_setup(owner: flow.Human, migrated: Engine) -> None:
    create(owner, repository=REPO)
    before = len(cards(migrated))
    refused = owner.patch("/projects/maity", {"setup": {"maity_badge": True}})
    assert refused.json()["error"]["details"]["fields"] == {"setup": "read_only"}
    changed = owner.patch("/projects/maity", {"memory": {"provider": "none"}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["keep_the_why"] is False and changed.json()["rules_version"] == 2
    with migrated.connect() as conn:
        bumped = conn.execute(select(t.event).where(t.event.c.kind == "rules_changed")).all()
    assert len(bumped) == 1
    assert len(cards(migrated)) == before  # a provider change creates and cancels nothing


def test_the_cards_come_when_the_repository_is_first_set_and_never_again(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    create(owner)
    admin = flow.human(make_client, migrated, "admin")
    with migrated.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    from tests import factory

    admin_membership = factory.membership(migrated, project_id, "admin", human_id=admin.id)
    first = admin.patch("/projects/maity", {"repository": REPO})
    assert first.status_code == 200, first.text
    made = cards(migrated)
    assert [c.title for c in made] == TITLES[:2]
    assert {c.created_by for c in made} == {admin_membership}  # whoever set it
    moved = owner.patch("/projects/maity", {"repository": {"url": REPO["url"] + "-two"}})
    assert moved.status_code == 200
    assert len(cards(migrated)) == 2  # never recreated
    owner.patch("/projects/maity", {"repository": None})
    owner.patch("/projects/maity", {"repository": REPO})
    assert len(cards(migrated)) == 2


def test_a_project_from_before_the_setup_gets_no_card(owner: flow.Human, migrated: Engine) -> None:
    create(owner)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(setup=None))
    owner.patch("/projects/maity", {"repository": REPO})
    assert cards(migrated) == []
    assert owner.get("/projects/maity").json()["setup"] is None


def test_in_freeze_the_hub_gives_the_reason_and_a_closed_project_gets_none(
    owner: flow.Human, migrated: Engine
) -> None:
    create(owner)
    owner.patch("/projects/maity", {"state": "freeze", "reason": "release"})
    owner.patch("/projects/maity", {"repository": REPO})
    [first, *_] = task_created(migrated)
    assert first.payload["project_state"] == "freeze"
    assert first.payload["reason"] == "project setup"
    other = owner.post("/projects", {"slug": "other", "name": "Other"})
    assert other.status_code == 201
    owner.patch("/projects/other", {"state": "accepted", "reason": "done"})
    owner.patch("/projects/other", {"repository": REPO})
    assert owner.get("/projects/other").json()["setup"]["cards"] is None


def test_only_the_hub_creates_a_setup_card(owner: flow.Human) -> None:
    create(owner)
    refused = owner.post("/projects/maity/tasks", {"kind": "setup", "title": "mine"})
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"kind": "unknown"}


def test_the_packet_names_the_setup_that_waits(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    create(owner, repository=REPO)
    agent = flow.agent(make_client, owner)
    made = cards(migrated)
    packet = agent.resume().json()
    assert packet["project"]["memory"] == {"provider": "keep-the-why"}
    assert packet["setup"] == [
        {"id": c.id, "title": c.title, "status": "open", "holder": None} for c in made
    ]
    assert agent.post(f"/projects/maity/tasks/{made[0].id}/claim", {}).status_code == 200
    held = agent.resume().json()["setup"][0]
    assert held["status"] == "in_progress" and held["holder"] == agent.id
    for card in made:
        done = owner.patch(f"/projects/maity/tasks/{card.id}", {"status": "cancelled"})
        assert done.status_code == 200, done.text
    assert "setup" not in agent.resume().json()


@pytest.mark.parametrize("state", ["accepted", "archived"])
def test_a_patch_that_sets_the_repository_and_closes_makes_no_card(
    owner: flow.Human, migrated: Engine, state: str
) -> None:
    create(owner)
    done = owner.patch("/projects/maity", {"repository": REPO, "state": state, "reason": "r"})
    assert done.status_code == 200, done.text
    assert done.json()["setup"]["cards"] is None and cards(migrated) == []


def test_a_patch_that_sets_the_repository_and_freezes_gives_the_hubs_reason(
    owner: flow.Human, migrated: Engine
) -> None:
    create(owner)
    done = owner.patch("/projects/maity", {"repository": REPO, "state": "freeze", "reason": "r"})
    assert done.status_code == 200, done.text
    made = task_created(migrated)
    assert made and all(e.payload["project_state"] == "freeze" for e in made)
    assert all(e.payload["reason"] == "project setup" for e in made)


def test_a_patch_that_reopens_and_sets_the_repository_makes_the_cards(
    owner: flow.Human, migrated: Engine
) -> None:
    create(owner)
    owner.patch("/projects/maity", {"state": "accepted", "reason": "r"})
    done = owner.patch("/projects/maity", {"repository": REPO, "state": "build", "reason": "r"})
    assert done.status_code == 200, done.text
    assert [c.title for c in cards(migrated)] == TITLES[:2]
