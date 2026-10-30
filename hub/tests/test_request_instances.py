"""An instance address in a request: the asking instance and `to: <member>#<id>`
(docs/api.md §7, §8.2, tsk-7v120qsccj5e)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_requests import answer, asked
from tests.test_team_rules import _last, _membership, _pair, owner  # noqa: F401


def _reader(migrated: Engine, agent: flow.Agent) -> Any:
    return _membership(migrated, agent)


def _token(agent: flow.Agent, instance: str) -> str:
    return f"instance:{agent.id}#{instance}"


def test_the_answer_wakes_the_asking_instance_and_its_team_reads_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    first, second = _pair(make_client, owner)
    request = asked(first, to="owner")
    assert request["asked_by"]["instance"] == first.instance
    assert answer(owner, request, text="Yes.").status_code == 200
    event = _last(migrated, "request_answered")
    assert event.audience == [_token(first, first.instance)]
    reader = _reader(migrated, first)
    assert events.readable_by(event, reader, first.id)  # the team reads along
    assert events.wakes(event, reader, first.id, first.instance)
    assert not events.wakes(event, reader, first.id, second.instance)  # and wakes only it


def test_a_withdrawal_wakes_the_asking_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    first, second = _pair(make_client, owner)
    request = asked(second, to="owner")
    withdrawn = second.post(
        f"/projects/maintainer/maity/requests/{request['id']}/withdraw", {"reason": "moot"}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert _last(migrated, "request_withdrawn").audience == [_token(first, second.instance)]


def test_a_human_asker_is_reached_as_the_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    first, _ = _pair(make_client, owner)
    request = asked(owner, to=first.id)
    assert request["asked_by"]["instance"] is None
    assert answer(first, request, text="Done.").status_code == 200
    assert _last(migrated, "request_answered").audience == [f"member:{owner.id}"]


def test_a_request_to_an_instance_address_wakes_that_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    first, second = _pair(make_client, owner)
    address = f"{first.id}#{second.instance}"
    request = asked(owner, to=address)
    assert request["to"] == address
    event = _last(migrated, "request_created")
    assert event.audience == [_token(first, second.instance)]
    reader = _reader(migrated, first)
    assert events.readable_by(event, reader, first.id)
    assert events.wakes(event, reader, first.id, second.instance)
    assert not events.wakes(event, reader, first.id, first.instance)
    listed = [
        r["id"] for r in first.get("/projects/maintainer/maity/requests?to=me").json()["items"]
    ]
    assert request["id"] in listed  # the whole team may answer
    assert answer(first, request, text="From the sibling.").status_code == 200


def test_an_address_of_an_instance_the_member_never_had_is_refused(
    owner: flow.Human, make_client: ClientFactory  # noqa: F811
) -> None:
    first, _ = _pair(make_client, owner)
    unknown = owner.post(
        "/projects/maintainer/maity/requests",
        {"class": "decision", "title": "Which?", "to": f"{first.id}#zzzz"},
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["fields"] == {"to": "not_an_instance"}
    human = owner.post(
        "/projects/maintainer/maity/requests",
        {"class": "decision", "title": "Which?", "to": f"{owner.id}#abcd"},
    )
    assert human.json()["error"]["details"]["fields"] == {"to": "not_an_instance"}


def test_a_replaced_instances_address_reaches_its_successor(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    old = flow.agent(make_client, owner)
    middle = flow.agent(make_client, owner, agent={"id": old.id}, replaces=old.instance)
    new = flow.agent(make_client, owner, agent={"id": old.id}, replaces=middle.instance)
    address = f"{old.id}#{old.instance}"
    request = asked(owner, to=address)
    assert request["to"] == address  # as written
    assert _last(migrated, "request_created").audience == [_token(old, new.instance)]


def test_a_revoked_instance_without_a_successor_is_accepted_and_wakes_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    agent = flow.agent(make_client, owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(revoked_at=clock.now())
        )
    asked(owner, to=f"{agent.id}#{agent.instance}")
    assert _last(migrated, "request_created").audience == [_token(agent, agent.instance)]
    with migrated.connect() as conn:
        live = conn.execute(
            select(t.credential.c.instance).where(
                t.credential.c.membership_id == _membership(migrated, agent).id,
                t.credential.c.revoked_at.is_(None),
            )
        ).all()
    assert live == []
