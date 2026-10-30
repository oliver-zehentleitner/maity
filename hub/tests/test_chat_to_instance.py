"""A direct chat message that names an instance wakes that one only (docs/api.md §9.1,
§8.2, tsk-p1df7ggm17bc)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_team_rules import _pair, owner  # noqa: F401


def send(who: Any, agent_id: str, **body: Any) -> Any:
    return who.post(
        f"/projects/maintainer/maity/conversations/{agent_id}/messages", {"body": "hi", **body}
    )


def _token(agent: flow.Agent, instance: str) -> str:
    return f"instance:{agent.id}#{instance}"


def _last(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == "message").order_by(t.event.c.seq.desc())
        ).first()


def _member(engine: Engine, agent: flow.Agent) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()


def test_the_human_names_one_instance_and_only_it_wakes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    first, second = _pair(make_client, owner)
    sent = send(owner, first.id, to_instance=second.instance)
    assert sent.status_code == 201, sent.text
    assert sent.json()["to_instance"] == second.instance
    row = _last(migrated)
    assert row.payload["to_instance"] == second.instance
    assert _token(first, second.instance) in row.audience
    assert f"member:{first.id}" not in row.audience  # the team reads it, one instance wakes
    member = _member(migrated, first)
    assert events.readable_by(row, member, first.id)
    assert events.wakes(row, member, first.id, second.instance)
    assert not events.wakes(row, member, first.id, first.instance)
    listed = owner.get(f"/projects/maintainer/maity/conversations/{first.id}/messages").json()
    assert [m["to_instance"] for m in listed["items"]] == [second.instance]


def test_without_it_the_message_is_as_before(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    first, second = _pair(make_client, owner)
    sent = send(owner, first.id)
    assert sent.status_code == 201 and sent.json()["to_instance"] is None
    row = _last(migrated)
    member = _member(migrated, first)
    assert events.wakes(row, member, first.id, first.instance)
    assert events.wakes(row, member, first.id, second.instance)


def test_a_replaced_instance_reaches_its_successor(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    old = flow.agent(make_client, owner)
    new = flow.agent(make_client, owner, agent={"id": old.id}, replaces=old.instance)
    sent = send(owner, old.id, to_instance=old.instance)
    assert sent.status_code == 201, sent.text
    assert sent.json()["to_instance"] == old.instance  # as written
    row = _last(migrated)
    assert _token(old, new.instance) in row.audience
    assert events.wakes(row, _member(migrated, old), old.id, new.instance)


def test_an_id_that_is_no_instance_of_the_agent_is_invalid(
    owner: flow.Human, make_client: ClientFactory  # noqa: F811
) -> None:
    first, _ = _pair(make_client, owner)
    for bad in ("zzzz", "wqe2", "x", "not-an-id-at-all"):
        refused = send(owner, first.id, to_instance=bad)
        assert refused.status_code == 400, bad
        assert refused.json()["error"]["details"]["fields"] == {"to_instance": "not_an_instance"}


def test_a_revoked_instance_without_a_successor_is_accepted_and_wakes_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    only = flow.agent(make_client, owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == only.credential_id)
            .values(revoked_at=clock.now())
        )
    assert send(owner, only.id, to_instance=only.instance).status_code == 201
    row = _last(migrated)
    assert _token(only, only.instance) in row.audience


def test_only_the_human_names_an_instance_and_only_in_a_direct_chat(
    owner: flow.Human, make_client: ClientFactory  # noqa: F811
) -> None:
    first, second = _pair(make_client, owner)
    from_the_agent = send(first, first.id, to_instance=second.instance)
    assert from_the_agent.status_code == 400
    assert from_the_agent.json()["error"]["details"]["fields"] == {"to_instance": "human_only"}
    other = flow.agent(make_client, owner)
    group = owner.post(
        "/projects/maintainer/maity/conversations",
        {"title": "Room", "participants": [first.id, other.id]},
    ).json()
    in_group = send(owner, group["id"], to_instance=second.instance)
    assert in_group.status_code == 400
    assert in_group.json()["error"]["details"]["fields"] == {"to_instance": "direct_chat_only"}
    typed = owner.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": first.id, "body": "x", "to_instance": "wqe2"},
    )
    assert typed.status_code == 400
