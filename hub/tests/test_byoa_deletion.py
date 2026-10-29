"""Bringing your own agent (docs/api.md §3.1) meets account deletion (§2.9): a member's
joins and the agents they brought when the member deletes the account."""

from __future__ import annotations

import contextvars
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import account_deletion
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_account_deletion import admin_first, deleted_at, person, press, requested
from tests.test_two_factor import Clock
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

PROJECT = "/projects/boss/team"
JOINS = f"{PROJECT}/joins"


def _team(make_client: ClientFactory, migrated: Engine, moment: Clock) -> tuple[Any, Any]:
    """The project's owner `boss` and `pat`, a member with trust member who brings agents."""
    admin_first(migrated, moment)
    boss = person(make_client, migrated, moment, "boss")
    flow.project(boss, "team")
    pat = person(make_client, migrated, moment, "pat")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=pat.id)
    return boss, pat


def _bring(pat: Any, handle: str) -> dict[str, Any]:
    made = pat.post(JOINS, {"agent": {"handle": handle, "display_name": handle}})
    assert made.status_code == 201, made.text
    result: dict[str, Any] = made.json()
    return result


def _join(migrated: Engine, join_id: str) -> Any:
    with migrated.connect() as conn:
        return conn.execute(select(t.join_link).where(t.join_link.c.id == join_id)).one()


def test_a_members_joins_and_agents_go_with_the_account(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """The unused joins are revoked; the agent already brought leaves the project as
    §2.9 removes the profiles the account owns; while the deletion is only requested,
    the member still brings agents (§2.9: nothing else changes yet)."""
    boss, pat = _team(make_client, migrated, moment)
    used = _bring(pat, "pat-agent")
    exchanged = flow.exchange(make_client(), used)
    assert exchanged.status_code == 201, exchanged.text
    agent_id = exchanged.headers["Maity-Member-Id"]
    unused = _bring(pat, "pat-spare")

    token = requested(pat, migrated)
    pending = _bring(pat, "pat-late")  # the request alone changes nothing

    assert press(pat, token).status_code == 200
    assert deleted_at(migrated, pat.id) is not None
    for join in (unused, pending):
        assert _join(migrated, join["id"]).revoked_at is not None
        assert flow.exchange(make_client(), join).status_code == 404
    with migrated.connect() as conn:
        membership = conn.execute(
            select(t.membership.c.removed_at).where(t.membership.c.agent_id == agent_id)
        ).one()
        profile = conn.execute(
            select(t.agent_profile.c.deleted_at).where(t.agent_profile.c.id == agent_id)
        ).one()
    assert membership.removed_at is not None and profile.deleted_at is not None
    members = boss.get(f"{PROJECT}/members").json()["items"]
    assert agent_id not in [m["id"] for m in members]


def test_a_members_join_in_flight_does_not_outlive_the_deletion(
    make_client: ClientFactory, migrated: Engine, moment: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A join authenticated before the deletion and handled after it is refused and leaves
    no join behind. The deletion commits before the route's transaction, so the refusal
    comes from the membership check; the race against `write_guard` itself (a write past
    its checks when the deletion commits) is covered in test_account_deletion.py."""
    from maity_hub import events, idempotency
    from maity_hub.deps import settings_of

    _, pat = _team(make_client, migrated, moment)
    token = requested(pat, migrated)
    original = idempotency.run

    def held(engine: Engine, request: Any, caller: Any, action: Any) -> Any:
        def press_link() -> None:
            with events.transaction(engine) as conn:
                assert account_deletion.confirm(conn, settings_of(request), token) == "deleted"

        contextvars.Context().run(press_link)
        return original(engine, request, caller, action)

    monkeypatch.setattr(idempotency, "run", held)
    late = pat.post(JOINS, {"agent": {"handle": "too-late", "display_name": "Too late"}})
    monkeypatch.undo()
    # Refused before anything is written: the member's membership is gone with the
    # account, so the route answers `not_found` as for any non-member (§1.3).
    assert late.status_code == 404, late.text
    with migrated.connect() as conn:
        assert not conn.execute(
            select(t.agent_profile).where(t.agent_profile.c.handle == "too-late")
        ).first()
        assert not conn.execute(
            select(t.join_link).where(t.join_link.c.created_by == pat.id)
        ).first()
