"""docs/api.md §2.3 "Version.": the roles list carries a `version`; a `PUT` names the one it
was made on as `base_version`, and a stale one is `conflict` with nothing changed."""

from __future__ import annotations

import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"
LEGAL = {"name": "legal", "base": "reviewer", "description": "Checks licences"}
TRANSLATOR = {"name": "translator", "base": "writer", "description": ""}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    return owner


def raw_put(owner: flow.Human, body: Any, **headers: str) -> Any:
    return owner.client.put(
        f"/api/v1{BASE}/roles", json=body, headers={"X-CSRF-Token": owner.csrf, **headers}
    )


def read(owner: flow.Human) -> dict[str, Any]:
    answer = owner.get(f"{BASE}/roles")
    assert answer.status_code == 200, answer.text
    body: dict[str, Any] = answer.json()
    return body


def stored(migrated: Engine) -> tuple[Any, int]:
    with migrated.connect() as conn:
        row = conn.execute(select(t.project.c.roles, t.project.c.roles_version)).one()
    return row.roles, row.roles_version


def policy_events(migrated: Engine) -> int:
    with migrated.connect() as conn:
        kinds = conn.execute(select(t.event.c.kind)).scalars().all()
    return kinds.count("policy_changed")


def test_the_version_starts_at_0_and_grows_with_each_change(owner: flow.Human) -> None:
    assert read(owner)["version"] == 0
    first = raw_put(owner, {"custom": [LEGAL], "base_version": 0})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert read(owner)["version"] == 1
    second = raw_put(owner, {"custom": [LEGAL, TRANSLATOR], "base_version": 1})
    assert second.status_code == 200, second.text
    assert (second.json()["version"], read(owner)["version"]) == (2, 2)


def test_a_stale_version_is_conflict_and_nothing_changes(
    owner: flow.Human, migrated: Engine
) -> None:
    assert raw_put(owner, {"custom": [LEGAL], "base_version": 0}).status_code == 200
    before = stored(migrated)
    events = policy_events(migrated)
    stale = raw_put(owner, {"custom": [TRANSLATOR], "base_version": 0})
    assert stale.status_code == 409, stale.text
    error = stale.json()["error"]
    assert error["code"] == "conflict"
    assert error["details"] == {"current_version": 1, "base_version": 0}
    assert stored(migrated) == before
    assert policy_events(migrated) == events


def test_a_version_ahead_of_the_list_is_stale_too(owner: flow.Human) -> None:
    ahead = raw_put(owner, {"custom": [LEGAL], "base_version": 7})
    assert ahead.status_code == 409, ahead.text
    assert ahead.json()["error"]["details"] == {"current_version": 0, "base_version": 7}


def test_without_a_version_the_put_is_invalid(owner: flow.Human, migrated: Engine) -> None:
    for body in ({"custom": [LEGAL]}, {"custom": [LEGAL], "base_version": None}):
        missing = raw_put(owner, body)
        assert missing.status_code == 400, missing.text
        error = missing.json()["error"]
        assert error["code"] == "invalid"
        assert error["details"]["fields"] == {"base_version": "required"}
    assert stored(migrated) == (None, 0)


@pytest.mark.parametrize("value", [-1, 1.5, "one", [0], {"v": 0}])
def test_a_version_that_is_no_whole_number_from_0_is_invalid(
    owner: flow.Human, migrated: Engine, value: Any
) -> None:
    bad = raw_put(owner, {"custom": [LEGAL], "base_version": value})
    assert bad.status_code == 400, bad.text
    assert set(bad.json()["error"]["details"]["fields"]) == {"base_version"}
    assert stored(migrated) == (None, 0)


def test_a_bad_body_is_named_before_the_version(owner: flow.Human) -> None:
    """The body first (§2.3 "Version."): a stale or missing version does not hide it."""
    bad = raw_put(owner, {"custom": [{"name": "Legal", "base": "coder"}], "base_version": 5})
    assert bad.status_code == 400, bad.text
    assert bad.json()["error"]["details"]["fields"] == {"custom[0].name": "format"}


def test_a_put_that_changes_nothing_keeps_the_version_whatever_it_names(
    owner: flow.Human, migrated: Engine
) -> None:
    assert raw_put(owner, {"custom": [LEGAL], "base_version": 0}).status_code == 200
    events = policy_events(migrated)
    for base_version in (1, 0, 9):
        same = raw_put(owner, {"custom": [LEGAL], "base_version": base_version})
        assert same.status_code == 200, same.text
        assert same.json()["version"] == 1
    assert read(owner)["version"] == 1
    assert policy_events(migrated) == events


def test_putting_no_roles_on_a_project_without_any_changes_nothing(
    owner: flow.Human, migrated: Engine
) -> None:
    same = raw_put(owner, {"custom": [], "base_version": 4})
    assert same.status_code == 200, same.text
    assert same.json() == {"custom": [], "version": 0}
    assert stored(migrated) == (None, 0)


def test_a_stale_removal_is_conflict_before_role_in_use(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """The version before `role_in_use` (§2.3 "Version."): a removal decided on a stale
    list is refused as stale, and the caller reads the list again."""
    assert raw_put(owner, {"custom": [LEGAL], "base_version": 0}).status_code == 200
    agent = flow.agent(make_client, owner)
    member = owner.patch(f"{BASE}/members/{agent.id}", {"trust": "member", "role": "legal"})
    assert member.status_code == 200, member.text
    stale = raw_put(owner, {"custom": [], "base_version": 0})
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["details"] == {"current_version": 1, "base_version": 0}
    current = raw_put(owner, {"custom": [], "base_version": 1})
    assert current.status_code == 409, current.text
    assert current.json()["error"]["details"]["reason"] == "role_in_use"


def test_a_replay_answers_the_list_and_its_version(owner: flow.Human) -> None:
    key = {"Idempotency-Key": "roles-version-0001"}
    body = {"custom": [LEGAL], "base_version": 0}
    first = raw_put(owner, body, **key)
    assert first.status_code == 200, first.text
    again = raw_put(owner, body, **key)
    assert again.status_code == 200, again.text
    assert again.json()["custom"] == first.json()["custom"]
    assert again.json()["version"] == 1
    assert read(owner)["version"] == 1  # replayed, not written twice


def test_two_admins_on_the_same_version_exactly_one_wins(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two saves made on the same read, at once: on a server database each waits right
    before the project's lock for the other to get there too, so both read their caller
    and parsed their body before either writes (SQLite takes its write lock at BEGIN and
    serialises them; the wait then gives up). One `PUT` wins; the other is `conflict` and
    its list is not written over the winner's — never last-write-wins."""
    admin = flow.human(make_client, migrated, "second")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "coder", trust="admin", human_id=admin.id)
    assert read(owner)["version"] == read(admin)["version"] == 0
    both_checked = threading.Barrier(2)
    real_lock = events.lock_project
    waited: list[Any] = []

    def after_both_checked(conn: Any, project_id: str) -> Any:
        # Only a request's first lock waits: the event the winner emits locks again.
        if not any(seen is conn for seen in waited):
            waited.append(conn)
            with contextlib.suppress(threading.BrokenBarrierError):
                both_checked.wait(timeout=2)
        return real_lock(conn, project_id)

    monkeypatch.setattr(events, "lock_project", after_both_checked)
    lists = {owner.id: [LEGAL], admin.id: [TRANSLATOR]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(
            pool.map(
                lambda who: raw_put(who, {"custom": lists[who.id], "base_version": 0}),
                [owner, admin],
            )
        )
    # On a server database both really were past their reads at once; SQLite let one wait
    # at BEGIN, so the other's wait gave up.
    assert both_checked.broken is (migrated.dialect.name == "sqlite")
    statuses = sorted(a.status_code for a in answers)
    assert statuses == [200, 409], [a.text for a in answers]
    [won] = [a for a in answers if a.status_code == 200]
    [lost] = [a for a in answers if a.status_code == 409]
    assert lost.json()["error"]["details"] == {"current_version": 1, "base_version": 0}
    roles, version = stored(migrated)
    assert version == 1
    assert [r["name"] for r in roles] == [r["name"] for r in won.json()["custom"]]
    assert policy_events(migrated) == 1
