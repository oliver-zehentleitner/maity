"""The project setting `why_merge_children` (§6.1, §11.5): whether the Why view shows the
whole Keep the Why family in one view. A boolean, `true` unless stored `false`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PATH = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _setting(client: Any) -> Any:
    return client.get(PATH).json()["settings"]["why_merge_children"]


def _events(migrated: Engine) -> list[Any]:
    with migrated.connect() as conn:
        rows = conn.execute(
            select(t.event).where(t.event.c.kind == "project_updated").order_by(t.event.c.seq)
        ).all()
    return [r for r in rows if "settings.why_merge_children" in r.payload.get("fields", {})]


def test_new_and_existing_projects_read_true_and_nothing_is_written(
    owner: flow.Human, migrated: Engine
) -> None:
    assert _setting(owner) is True
    assert owner.get("/projects").json()["items"][0]["settings"]["why_merge_children"] is True
    with migrated.begin() as conn:  # a project from before the setting: no key at all
        conn.execute(update(t.project).values(settings={"language": "de"}))
    assert _setting(owner) is True
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.settings)).scalar_one() == {"language": "de"}


def test_false_is_stored_null_restores_the_default_and_only_changes_are_announced(
    owner: flow.Human, migrated: Engine
) -> None:
    owner.patch(PATH, {"settings": {"release_checklist": ["keep this"]}})
    response = owner.patch(PATH, {"settings": {"why_merge_children": False}})
    assert response.status_code == 200
    assert response.json()["settings"]["why_merge_children"] is False
    assert response.json()["settings"]["release_checklist"] == ["keep this"]
    assert _setting(owner) is False
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.settings)).scalar_one() == {
            "release_checklist": ["keep this"],
            "why_merge_children": False,
        }
    owner.patch(PATH, {"settings": {"why_merge_children": False}})
    owner.patch(PATH, {"settings": {}})
    owner.patch(PATH, {"settings": {"release_checklist": ["other"]}})  # not named: unchanged
    assert _setting(owner) is False
    assert (
        owner.patch(PATH, {"settings": {"why_merge_children": None}}).json()["settings"][
            "why_merge_children"
        ]
        is True
    )
    owner.patch(PATH, {"settings": {"why_merge_children": True}})  # reads the same: no event
    owner.patch(PATH, {"settings": {"why_merge_children": None}})
    with migrated.connect() as conn:
        settings = conn.execute(select(t.project.c.settings)).scalar_one()
    assert settings == {"release_checklist": ["other"]}
    events = _events(migrated)
    assert [e.payload for e in events] == [
        {"fields": {"settings.why_merge_children": False}},
        {"fields": {"settings.why_merge_children": True}},
    ]
    assert all(e.audience == ["all"] for e in events)


def test_a_change_bumps_no_rules_version(owner: flow.Human, migrated: Engine) -> None:
    with migrated.connect() as conn:
        before = conn.execute(select(t.project.c.rules_version)).scalar_one()
    owner.patch(PATH, {"settings": {"why_merge_children": False}})
    owner.patch(PATH, {"settings": {"why_merge_children": None}})
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.rules_version)).scalar_one() == before


@pytest.mark.parametrize("value", [0, 1, "true", "false", "", [], {}, 1.0])
def test_anything_but_a_boolean_or_null_is_not_a_boolean(owner: flow.Human, value: Any) -> None:
    response = owner.patch(PATH, {"settings": {"why_merge_children": value}})
    assert response.status_code == 400
    assert response.headers["Maity-Error"] == "invalid"
    assert response.json()["error"]["details"]["fields"] == {
        "settings.why_merge_children": "not_a_boolean"
    }
    assert _setting(owner) is True


@pytest.mark.parametrize("role", ["admin", "member"])
def test_agents_may_not_set_or_reset_it(
    owner: flow.Human, make_client: ClientFactory, role: str
) -> None:
    agent = flow.agent(make_client, owner, role=role)
    for value in [False, True, None]:
        response = agent.patch(PATH, {"settings": {"why_merge_children": value}})
        assert response.status_code == 403
        assert response.json()["error"]["details"]["reason"] == "humans_only"
    assert _setting(owner) is True
    assert _setting(agent) is True  # every member reads it with the project


@pytest.mark.parametrize(("role", "status"), [("admin", 200), ("member", 403)])
def test_only_human_project_admins_set_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, role: str, status: int
) -> None:
    human = flow.human(make_client, migrated, "other")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, role, human_id=human.id)
    response = human.patch(PATH, {"settings": {"why_merge_children": False}})
    assert response.status_code == status
    assert _setting(human) is (status != 200)
