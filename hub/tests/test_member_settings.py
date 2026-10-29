"""docs/api.md §6.2 "A member's own settings in a project" and §18.4 `not_listening`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _own(who: Any, **body: Any) -> Any:
    return who.patch(f"{BASE}/me/settings", body)


def test_the_personal_default_is_inbox_after_an_hour(owner: flow.Human) -> None:
    settings = owner.get("/me/notification-settings").json()
    assert settings["not_listening"] == {"mode": "inbox", "minutes": 60}


def test_the_personal_setting_takes_either_field(owner: flow.Human) -> None:
    changed = owner.patch("/me/notification-settings", {"not_listening": {"mode": "bell"}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["not_listening"] == {"mode": "bell", "minutes": 60}
    changed = owner.patch("/me/notification-settings", {"not_listening": {"minutes": 30}})
    assert changed.json()["not_listening"] == {"mode": "bell", "minutes": 30}
    assert owner.get("/me/notification-settings").json()["not_listening"]["minutes"] == 30


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"mode": "mail"}, "not_listening.mode"),
        ({"minutes": 9}, "not_listening.minutes"),
        ({"minutes": 1441}, "not_listening.minutes"),
        ({"minutes": "60"}, "not_listening.minutes"),
        ({"minutes": True}, "not_listening.minutes"),
        ({"other": 1}, "not_listening"),
    ],
)
def test_the_personal_setting_is_checked(owner: flow.Human, body: Any, field: str) -> None:
    refused = owner.patch("/me/notification-settings", {"not_listening": body})
    assert refused.status_code == 400, refused.text
    assert field in refused.json()["error"]["details"]["fields"]


def test_a_project_reads_the_default_until_the_member_overrides_it(owner: flow.Human) -> None:
    read = owner.get(f"{BASE}/me/settings")
    assert read.status_code == 200, read.text
    assert read.json() == {
        "not_listening": {"minutes": None},
        "effective": {"not_listening": {"minutes": 60}},
    }
    owner.patch("/me/notification-settings", {"not_listening": {"minutes": 45}})
    assert owner.get(f"{BASE}/me/settings").json()["effective"]["not_listening"]["minutes"] == 45
    set_ = _own(owner, not_listening={"minutes": 15})
    assert set_.status_code == 200, set_.text
    assert set_.json() == {
        "not_listening": {"minutes": 15},
        "effective": {"not_listening": {"minutes": 15}},
    }
    assert owner.get(f"{BASE}/me/settings").json()["not_listening"]["minutes"] == 15
    back = _own(owner, not_listening={"minutes": None})  # `null`: the personal default again
    assert back.json() == {
        "not_listening": {"minutes": None},
        "effective": {"not_listening": {"minutes": 45}},
    }


def test_the_override_is_this_projects_only(owner: flow.Human) -> None:
    flow.project(owner, "other")
    _own(owner, not_listening={"minutes": 20})
    other = owner.get("/projects/maintainer/other/me/settings").json()
    assert other["not_listening"]["minutes"] is None
    assert other["effective"]["not_listening"]["minutes"] == 60


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"not_listening": {"minutes": 5}}, "not_listening.minutes"),
        ({"not_listening": {"minutes": 2000}}, "not_listening.minutes"),
        ({"not_listening": {"mode": "bell"}}, "not_listening"),  # the mode is personal only
        ({"language": "de"}, "language"),
    ],
)
def test_the_override_is_checked(owner: flow.Human, body: Any, field: str) -> None:
    refused = owner.patch(f"{BASE}/me/settings", body)
    assert refused.status_code == 400, refused.text
    assert field in refused.json()["error"]["details"]["fields"]


def test_only_a_human_member_has_own_settings(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    refused = agent.get(f"{BASE}/me/settings")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.get(f"{BASE}/me/settings").status_code == 404
    assert (
        stranger.patch(f"{BASE}/me/settings", {"not_listening": {"minutes": 30}}).status_code == 404
    )
