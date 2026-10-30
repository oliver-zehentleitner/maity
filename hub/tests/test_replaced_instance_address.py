"""An address that names a replaced instance reaches its successor, in a message's `to`,
in a mention and in the list filter `to=` (docs/api.md §6.17, §8.2, §8.6,
tsk-q7p3sz8df62q)."""

from __future__ import annotations

from sqlalchemy import Engine, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_mentions import agent_named, owner, say  # noqa: F401
from tests.test_requests import asked


def _replaced_twice(
    make_client: ClientFactory, owner: flow.Human  # noqa: F811
) -> tuple[flow.Agent, flow.Agent, flow.Agent]:
    old = agent_named(make_client, owner, "agent-b")
    middle = flow.agent(make_client, owner, agent={"id": old.id}, replaces=old.instance)
    new = flow.agent(make_client, owner, agent={"id": old.id}, replaces=middle.instance)
    return old, middle, new


def _token(agent: flow.Agent, instance: str) -> str:
    return f"instance:{agent.id}#{instance}"


def test_a_message_to_a_replaced_instance_reaches_its_successor_along_the_chain(
    make_client: ClientFactory, owner: flow.Human  # noqa: F811
) -> None:
    old, middle, new = _replaced_twice(make_client, owner)
    writer = agent_named(make_client, owner, "agent-a")
    for named in (old, middle):
        address = f"{old.id}#{named.instance}"
        sent = say(writer, to=address, body="Over to you.")
        assert sent.status_code == 201, sent.text
        assert sent.json()["payload"]["to"] == address  # as written
        assert _token(old, new.instance) in sent.json()["audience"]
        assert _token(old, named.instance) not in sent.json()["audience"]


def test_a_message_to_a_revoked_instance_without_a_successor_is_accepted(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine  # noqa: F811
) -> None:
    only = agent_named(make_client, owner, "agent-b")
    writer = agent_named(make_client, owner, "agent-a")
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == only.credential_id)
            .values(revoked_at=clock.now())
        )
    sent = say(writer, to=f"{only.id}#{only.instance}", body="Anyone?")
    assert sent.status_code == 201, sent.text
    assert _token(only, only.instance) in sent.json()["audience"]  # wakes nobody
    unknown = say(writer, to=f"{only.id}#zzzz", body="Anyone?")
    assert unknown.json()["error"]["details"]["fields"] == {"to": "not_an_instance"}


def test_a_mention_of_a_replaced_instance_pings_its_successor(
    make_client: ClientFactory, owner: flow.Human  # noqa: F811
) -> None:
    old, _, new = _replaced_twice(make_client, owner)
    writer = agent_named(make_client, owner, "agent-a")
    event = say(writer, to=owner.id, body=f"@agent-b#{old.instance} please").json()
    [mention] = event["payload"]["mentions"]
    assert mention["instance"] == old.instance  # as written
    assert _token(old, new.instance) in event["audience"]
    assert _token(old, old.instance) not in event["audience"]


def test_a_card_mention_of_a_replaced_instance_pings_its_successor(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine  # noqa: F811
) -> None:
    old, _, new = _replaced_twice(make_client, owner)
    created = owner.post(
        "/projects/maintainer/maity/tasks", {"title": "x", "body": f"@agent-b#{old.instance}"}
    )
    assert created.status_code == 201, created.text
    with migrated.connect() as conn:
        event = conn.execute(select(t.event).where(t.event.c.kind == "mentioned")).one()
    assert event.audience == [_token(old, new.instance)]


def test_a_member_id_in_the_list_filter_also_names_its_teams_instance_addresses(
    make_client: ClientFactory, owner: flow.Human  # noqa: F811
) -> None:
    first = agent_named(make_client, owner, "agent-b")
    owner.patch(f"/projects/maintainer/maity/members/{first.id}", {"team": {"max_instances": 2}})
    second = flow.agent(make_client, owner, agent={"id": first.id}, new_instance=True)
    other = agent_named(make_client, owner, "agent-c")
    to_team = asked(owner, to=first.id)
    to_instance = asked(owner, to=f"{first.id}#{second.instance}")
    to_other = asked(owner, to=other.id)

    def listed(to: str) -> set[str]:
        items = owner.get("/projects/maintainer/maity/requests", params={"to": to}).json()["items"]
        return {r["id"] for r in items}

    assert listed(first.id) == {to_team["id"], to_instance["id"]}  # the team reads both
    assert listed(f"{first.id}#{second.instance}") == {to_instance["id"]}  # one instance only
    assert listed(f"{first.id}#{first.instance}") == set()
    assert listed(other.id) == {to_other["id"]}


def test_in_a_group_chat_a_mention_of_a_replaced_instance_wakes_its_successor(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine  # noqa: F811
) -> None:
    old, middle, new = _replaced_twice(make_client, owner)
    other = agent_named(make_client, owner, "agent-c")
    chat = owner.post(
        "/projects/maintainer/maity/conversations",
        {"title": "Room", "participants": [old.id, other.id]},
    ).json()
    sent = owner.post(
        f"/projects/maintainer/maity/conversations/{chat['id']}/messages",
        {"body": f"@agent-b#{old.instance} please"},
    )
    assert sent.status_code == 201, sent.text
    with migrated.connect() as conn:
        row = conn.execute(
            select(t.event).where(t.event.c.kind == "message").order_by(t.event.c.seq.desc())
        ).first()
        member = conn.execute(select(t.membership).where(t.membership.c.agent_id == old.id)).one()
    assert events.wakes(row, member, old.id, new.instance)
    assert not events.wakes(row, member, old.id, middle.instance)  # replaced, wakes nobody


def test_a_chain_that_ends_in_a_revoked_instance_wakes_nobody(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine  # noqa: F811
) -> None:
    old = agent_named(make_client, owner, "agent-b")
    middle = flow.agent(make_client, owner, agent={"id": old.id}, replaces=old.instance)
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == middle.credential_id)
            .values(revoked_at=clock.now())
        )
    writer = agent_named(make_client, owner, "agent-a")
    sent = say(writer, to=f"{old.id}#{old.instance}", body="Anyone?")
    assert sent.status_code == 201, sent.text  # accepted (§8.2)
    assert _token(old, middle.instance) in sent.json()["audience"]  # the dead end's token


def test_an_instance_mention_after_a_rejoin_pings_the_instance_of_the_active_membership(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine  # noqa: F811
) -> None:
    """A removed member keeps its row and joins again with a second one: the mention
    must find the active one, not fail on two (§6.2)."""
    first = agent_named(make_client, owner, "agent-b")
    assert owner.delete(f"/projects/maintainer/maity/members/{first.id}").status_code == 200
    again = flow.agent(make_client, owner, agent={"id": first.id})
    writer = agent_named(make_client, owner, "agent-a")
    sent = say(writer, to=owner.id, body=f"@agent-b#{again.instance} please")
    assert sent.status_code == 201, sent.text
    assert _token(first, again.instance) in sent.json()["audience"]
    created = owner.post(
        "/projects/maintainer/maity/tasks", {"title": "x", "body": f"@agent-b#{again.instance}"}
    )
    assert created.status_code == 201, created.text
    with migrated.connect() as conn:
        event = conn.execute(
            select(t.event).where(t.event.c.kind == "mentioned").order_by(t.event.c.seq.desc())
        ).first()
    assert event is not None and event.audience == [_token(first, again.instance)]
