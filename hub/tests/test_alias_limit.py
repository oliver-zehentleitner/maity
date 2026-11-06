"""docs/api.md §16.5 `max_aliases`, §6.24, §6.25: the aliases one id may hold, an instance
setting from 1 to 8, default 3; a rename over it is refused, lowering it drops nothing."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, delete, insert, select

from maity_hub import clock, namespace
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from tests import flow
from tests.conftest import ClientFactory

PATH = "/admin/settings/limits"


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin: the earliest account."""
    return flow.human(make_client, migrated)


def _window_passed(engine: Engine) -> None:
    """Three renames a day (§1.7): forget the earlier ones, so a test can go on."""
    with engine.begin() as conn:
        conn.execute(delete(t.handle_change))


def _rename(who: flow.Human, engine: Engine, handle: str) -> Any:
    _window_passed(engine)
    return who.patch("/me", {"handle": handle})


def _error(response: Any) -> tuple[int, str, dict[str, Any]]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["details"]


def test_the_value_is_one_to_eight_and_never_unlimited(admin: flow.Human) -> None:
    for good in (1, 8):
        got = admin.patch(PATH, {"max_aliases": good})
        assert got.json()["max_aliases"] == {"value": good, "source": "admin"}, got.text
    for bad in (0, 9, "unlimited", True, 2.5):
        refused = admin.patch(PATH, {"max_aliases": bad})
        assert refused.status_code == 400, (bad, refused.text)
        assert refused.json()["error"]["details"]["fields"] == {"max_aliases": "invalid"}
    back = admin.patch(PATH, {"max_aliases": None})
    assert back.json()["max_aliases"] == {"value": 3, "source": "default"}
    refused = admin.patch(PATH, {"names_at_alias_limit": 0})
    assert refused.json()["error"]["details"]["fields"] == {"names_at_alias_limit": "read_only"}


def test_the_environment_sets_it_and_wins(make_client: ClientFactory, migrated: Engine) -> None:
    assert Settings.from_env({"MAITY_MAX_ALIASES": "5"}).max_aliases == 5
    assert Settings.from_env({"MAITY_MAX_ALIASES": ""}).max_aliases is None
    for bad in ("0", "9", "unlimited", "x"):
        with pytest.raises(ConfigError):
            Settings.from_env({"MAITY_MAX_ALIASES": bad})
    who = flow.human(lambda **kw: make_client(max_aliases=1, **kw), migrated)
    assert who.get(PATH).json()["max_aliases"] == {"value": 1, "source": "env"}
    assert _rename(who, migrated, "first").status_code == 200
    assert _error(_rename(who, migrated, "second"))[:2] == (409, "alias_limit")
    refused = who.patch(PATH, {"max_aliases": 8})
    assert refused.json()["error"]["details"]["fields"] == {"max_aliases": "set_by_environment"}


def test_a_rename_up_to_the_value_and_the_one_over_it(admin: flow.Human, migrated: Engine) -> None:
    """limit − 1, limit and limit + 1, at the default 3."""
    old = admin.handle
    for n in range(3):  # aliases 1, 2, 3
        assert _rename(admin, migrated, f"name-{n}").status_code == 200
    assert admin.get(PATH).json()["names_at_alias_limit"] == 1
    status, code, details = _error(_rename(admin, migrated, "name-3"))
    assert (status, code, details["limit"]) == (409, "alias_limit", 3)
    assert details["aliases"] == [old, "name-0", "name-1"]
    assert admin.get("/me").json()["member"]["handle"] == "name-2"  # nothing changed


def test_a_lowered_value_drops_nothing_and_a_name_taken_back_stays_possible(
    admin: flow.Human, migrated: Engine
) -> None:
    old = admin.handle
    for n in range(3):
        assert _rename(admin, migrated, f"name-{n}").status_code == 200
    assert admin.patch(PATH, {"max_aliases": 1}).status_code == 200
    me = admin.get("/me").json()["member"]
    assert me["aliases"] == [old, "name-0", "name-1"]  # all three kept
    # An old name still reaches the same account.
    assert admin.get(f"/people/{old}").json()["handle"] == "name-2"
    assert _error(_rename(admin, migrated, "name-9"))[:2] == (409, "alias_limit")
    taken_back = _rename(admin, migrated, "name-0")  # adds none: the current one replaces it
    assert taken_back.status_code == 200, taken_back.text
    assert admin.get(PATH).json()["names_at_alias_limit"] == 1


def test_an_agent_profile_follows_the_same_value(
    make_client: ClientFactory, admin: flow.Human, migrated: Engine
) -> None:
    assert admin.patch(PATH, {"max_aliases": 1}).status_code == 200
    flow.project(admin)
    agent = flow.agent(make_client, admin, agent={"handle": "bee", "display_name": "Bee"})
    assert admin.patch(f"/agents/{agent.id}", {"handle": "wasp"}).status_code == 200
    _window_passed(migrated)
    refused = admin.patch(f"/agents/{agent.id}", {"handle": "moth"})
    assert _error(refused)[:2] == (409, "alias_limit")
    assert _error(refused)[2]["limit"] == 1


def test_a_project_over_a_lowered_value_keeps_its_names_and_may_take_one_back(
    admin: flow.Human, migrated: Engine
) -> None:
    flow.project(admin)
    with migrated.begin() as conn:
        project = conn.execute(select(t.project)).one()
        for n in range(2):
            conn.execute(
                insert(t.project_alias).values(
                    project_id=project.id,
                    **namespace.owner_values(project.owner_id),
                    slug=f"old-{n}",
                    created_at=clock.now(),
                )
            )
    assert admin.patch(PATH, {"max_aliases": 1}).status_code == 200
    name = f"{admin.handle}/maity"
    refused = admin.patch(f"/projects/{name}", {"slug": "new"})
    assert _error(refused)[:2] == (409, "alias_limit")
    back = admin.patch(f"/projects/{name}", {"slug": "old-1"})
    assert back.status_code == 200, back.text
    assert admin.get(PATH).json()["names_at_alias_limit"] == 1
