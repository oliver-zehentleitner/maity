"""A human's direct chat message wakes the agent's team by its `wake` rule, or exactly the
instance it names (docs/api.md §9.1, §6.18, tsk-p49b0kverrph)."""

from __future__ import annotations

from sqlalchemy import Engine

from maity_hub import events
from tests import flow
from tests.conftest import ClientFactory
from tests.test_chat_to_instance import send
from tests.test_team_rules import (  # noqa: F401
    _last,
    _listen,
    _membership,
    _pair,
    _Reader,
    _team,
    listens,
    owner,
)


def wakes(migrated: Engine, agent: flow.Agent, instance: str) -> bool:
    event = _last(migrated, "message")
    return events.wakes(event, _Reader(_membership(migrated, agent)), agent.id, instance)


def test_under_all_every_instance_wakes(
    owner: flow.Human,  # noqa: F811
    make_client: ClientFactory,
    migrated: Engine,
) -> None:
    first, second = _pair(make_client, owner)
    assert send(owner, first.id).status_code == 201
    assert _last(migrated, "message").wakes is None
    assert wakes(migrated, first, first.instance) and wakes(migrated, first, second.instance)


def test_under_lead_only_the_lead_wakes_and_nobody_when_it_does_not_listen(
    owner: flow.Human,  # noqa: F811
    make_client: ClientFactory,
    migrated: Engine,
    listens: list[str],  # noqa: F811
) -> None:
    lead, other = _pair(make_client, owner)
    _team(owner, lead.id, wake="lead", lead_instance=lead.instance)
    _listen(listens, other)
    assert send(owner, lead.id).status_code == 201
    assert _last(migrated, "message").wakes == {lead.id: []}  # the lead does not listen
    assert not wakes(migrated, lead, lead.instance) and not wakes(migrated, lead, other.instance)
    _listen(listens, lead)
    assert send(owner, lead.id).status_code == 201
    assert wakes(migrated, lead, lead.instance) and not wakes(migrated, lead, other.instance)


def test_under_next_free_one_listening_instance_wakes(
    owner: flow.Human,  # noqa: F811
    make_client: ClientFactory,
    migrated: Engine,
    listens: list[str],  # noqa: F811
) -> None:
    first, second = _pair(make_client, owner)
    _team(owner, first.id, wake="next_free")
    _listen(listens, first)
    _listen(listens, second)
    assert send(owner, first.id).status_code == 201
    chosen = _last(migrated, "message").wakes[first.id]
    assert len(chosen) == 1
    woken = [a for a in (first, second) if wakes(migrated, first, a.instance)]
    assert [a.instance for a in woken] == chosen


def test_a_named_instance_wakes_whatever_the_rule_says(
    owner: flow.Human,  # noqa: F811
    make_client: ClientFactory,
    migrated: Engine,
    listens: list[str],  # noqa: F811
) -> None:
    lead, other = _pair(make_client, owner)
    _team(owner, lead.id, wake="lead", lead_instance=lead.instance)
    _listen(listens, lead)
    _listen(listens, other)
    assert send(owner, lead.id, to_instance=other.instance).status_code == 201
    assert wakes(migrated, lead, other.instance) and not wakes(migrated, lead, lead.instance)
    assert send(owner, lead.id, to_instance=lead.instance).status_code == 201
    assert wakes(migrated, lead, lead.instance) and not wakes(migrated, lead, other.instance)
