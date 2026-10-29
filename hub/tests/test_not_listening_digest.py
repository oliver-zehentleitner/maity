"""docs/api.md §5.3 "The owner's digest", the `bell` mode: the record
`agents_not_listening` and its item in the bell (§18.1, §18.2)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, not_listening_digest
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    human.patch("/me/notification-settings", {"not_listening": {"mode": "bell"}})
    return human


def _episode(engine: Engine, agent: flow.Agent, ago: timedelta | None) -> None:
    """Start (or with `None` end) the episode of the agent's session `ago` back."""
    with engine.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == agent.credential_id)
            .values(not_listening_since=None if ago is None else clock.now() - ago)
        )


def _records(engine: Engine, owner: flow.Human) -> list[Any]:
    with engine.connect() as conn:
        return [
            r.data
            for r in conn.execute(
                select(t.account_record)
                .where(
                    t.account_record.c.human_id == owner.id,
                    t.account_record.c.type == "agents_not_listening",
                )
                .order_by(t.account_record.c.n)
            )
        ]


def _bell(owner: flow.Human) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = owner.get("/me/notifications", params={"limit": 50}).json()[
        "items"
    ]
    return [i for i in items if (i.get("target") or {}).get("type") == "agents"]


def _agent(make_client: ClientFactory, owner: flow.Human) -> flow.Agent:
    agent = flow.agent(make_client, owner)
    assert agent.resume().status_code == 200  # a session to be not listening in
    return agent


def test_an_instance_away_for_the_threshold_is_in_the_bell(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(minutes=30))  # under the default 60
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [] and _bell(owner) == []
    _episode(migrated, agent, timedelta(minutes=61))
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [{"instances": 1}]
    [item] = _bell(owner)
    assert item["kind"] == "inbox"
    assert item["title"] == "1 of your agent instances are not listening"
    assert item["target"] == {"type": "agents"} and item["url"].endswith("/agents")
    counts = owner.get("/me/notifications", params={"limit": 0}).json()["counts"]
    assert counts["inbox"] == 1
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [{"instances": 1}]  # one record while it lasts


def test_the_count_is_read_live_and_the_item_goes_when_none_is_away(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _agent(make_client, owner), _agent(make_client, owner)
    _episode(migrated, first, timedelta(hours=2))
    not_listening_digest.run(migrated)
    _episode(migrated, second, timedelta(hours=2))
    assert _bell(owner)[0]["title"] == "2 of your agent instances are not listening"
    _episode(migrated, first, None)
    _episode(migrated, second, None)
    assert _bell(owner) == []  # no instance away: not listed, before the next hour
    not_listening_digest.run(migrated)
    # One was away at the first hour; the record keeps that count, the title reads live.
    assert _records(migrated, owner) == [{"instances": 1}, {"instances": 0}]
    _episode(migrated, first, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert _records(migrated, owner)[-1] == {"instances": 1}  # a new phase, a new item
    assert len(_bell(owner)) == 1


def test_the_projects_own_threshold_overrides_the_personal_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _agent(make_client, owner)
    owner.patch(f"{BASE}/me/settings", {"not_listening": {"minutes": 180}})
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert _bell(owner) == []
    owner.patch(f"{BASE}/me/settings", {"not_listening": {"minutes": 90}})
    assert len(_bell(owner)) == 0  # the record waits for the hour
    not_listening_digest.run(migrated)
    assert len(_bell(owner)) == 1


@pytest.mark.parametrize("mode", ["inbox", "off"])
def test_only_bell_writes_the_record_and_leaving_it_closes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, mode: str
) -> None:
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert len(_bell(owner)) == 1
    changed = owner.patch("/me/notification-settings", {"not_listening": {"mode": mode}})
    assert changed.status_code == 200, changed.text
    assert _records(migrated, owner) == [{"instances": 1}, {"instances": 0}]  # at the PATCH
    assert _bell(owner) == []
    not_listening_digest.run(migrated)
    assert _records(migrated, owner)[-1] == {"instances": 0}


def test_the_worker_runs_on_the_hour() -> None:
    now = clock.now().replace(minute=37, second=5, microsecond=12)
    due = not_listening_digest.next_hour(now)
    assert (due.minute, due.second, due.microsecond) == (0, 0, 0)
    assert timedelta(0) < due - now <= timedelta(hours=1)


def test_a_closed_record_lists_nothing_until_the_next_hour_writes_a_new_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """After `{instances: 0}` the bell waits for the worker: neither a new episode nor
    the switch back to `bell` lists the closed record again."""
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    owner.patch("/me/notification-settings", {"not_listening": {"mode": "off"}})
    assert _records(migrated, owner)[-1] == {"instances": 0}
    owner.patch("/me/notification-settings", {"not_listening": {"mode": "bell"}})
    assert _bell(owner) == []  # back under bell, an instance away, the newest record closed
    _episode(migrated, agent, None)
    not_listening_digest.run(migrated)
    _episode(migrated, agent, timedelta(hours=3))  # a new episode, before the next hour
    assert _bell(owner) == []
    not_listening_digest.run(migrated)
    assert _records(migrated, owner)[-1] == {"instances": 1}
    assert len(_bell(owner)) == 1
