"""docs/api.md §5.2 `handover`, §6.17: what a replaced instance left undone."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory


def tell(owner: flow.Human, to: str, body: str) -> int:
    """A message to an address (`agt-b#wle2`) or a member id; its seq."""
    response = owner.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": to, "body": body},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["seq"])


def replace(make_client: ClientFactory, owner: flow.Human, old: flow.Agent) -> flow.Agent:
    return flow.agent(make_client, owner, agent={"id": old.id}, replaces=old.instance)


def seqs(handover: dict[str, Any]) -> list[int]:
    """The messages among the items: the exchange writes events to the member as well."""
    return [item["seq"] for item in handover["items"] if item["kind"] == "message"]


def test_a_replacing_instance_gets_what_was_left_undone(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    old = flow.agent(make_client, owner)
    acknowledged = old.resume().json()["events"]["cursor"]
    old.resume(cursor=acknowledged)
    for_instance = tell(owner, f"{old.id}#{old.instance}", "to the instance")
    for_team = tell(owner, old.id, "to the team")
    new = replace(make_client, owner, old)
    after_exchange = tell(
        owner, f"{old.id}#{old.instance}", "to the old address, after the exchange"
    )

    packet = new.resume().json()
    handover = packet["handover"]
    assert handover["from"] == [old.instance] and handover["after"] == acknowledged
    # The instance's first, oldest first, then what only the team was told.
    assert seqs(handover) == [for_instance, after_exchange, for_team]
    assert handover["truncated"] is False
    # It moves nothing: the event list starts at the head, without these.
    assert for_instance not in [e["seq"] for e in packet["events"]["items"]]


def test_the_handover_comes_until_the_first_packet_is_acknowledged(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    old = flow.agent(make_client, owner)
    old.resume()
    left = tell(owner, f"{old.id}#{old.instance}", "undone")
    new = replace(make_client, owner, old)

    first = new.resume().json()
    assert seqs(first["handover"]) == [left]
    # The packet was lost: no cursor was kept, the same comes again (at least once).
    again = new.resume().json()
    assert seqs(again["handover"]) == [left]
    # Acknowledged: the first packet's cursor is passed back, and the handover is done.
    done = new.resume(cursor=first["events"]["cursor"]).json()
    assert "handover" not in done


def test_a_chain_goes_back_through_instances_that_never_had_a_session(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    oldest = flow.agent(make_client, owner)
    oldest.resume()
    for_oldest = tell(owner, f"{oldest.id}#{oldest.instance}", "for the oldest")
    middle = replace(make_client, owner, oldest)  # never resumes
    for_middle = tell(owner, f"{middle.id}#{middle.instance}", "for the middle")
    newest = replace(make_client, owner, middle)

    handover = newest.resume().json()["handover"]
    assert handover["from"] == [middle.instance, oldest.instance]
    assert seqs(handover) == [for_oldest, for_middle]


def test_nothing_is_handed_over_to_an_instance_that_replaced_nothing(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    tell(owner, f"{agent.id}#{agent.instance}", "hello")
    assert "handover" not in agent.resume().json()


def test_the_first_packet_carries_it_whatever_cursor_the_resume_named(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    old = flow.agent(make_client, owner)
    old.resume()
    left = tell(owner, f"{old.id}#{old.instance}", "undone")
    new = replace(make_client, owner, old)
    first = new.resume(cursor=10**6).json()  # a cursor at or above the head, from the start
    assert seqs(first["handover"]) == [left]
    assert "handover" not in new.resume(cursor=10**6).json()  # acknowledged


def test_more_than_fifty_items_are_cut_and_say_so(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    old = flow.agent(make_client, owner)
    old.resume()
    sent = [tell(owner, f"{old.id}#{old.instance}", f"message {i}") for i in range(55)]
    new = replace(make_client, owner, old)
    handover = new.resume().json()["handover"]
    assert len(seqs(handover)) == 50 and handover["truncated"] is True
    assert seqs(handover) == sent[:50]  # oldest first; `GET …/events?after=` pages on


def test_only_what_is_addressed_to_the_chain_and_readable_comes(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    old = flow.agent(make_client, owner)
    stranger = flow.agent(make_client, owner)
    old.resume()
    mine = tell(owner, f"{old.id}#{old.instance}", "for the chain")
    tell(owner, stranger.id, "for somebody else")
    new = replace(make_client, owner, old)
    to_new_address = tell(
        owner, f"{new.id}#{new.instance}", "to the new address, before its first resume"
    )
    assert seqs(new.resume().json()["handover"]) == [mine, to_new_address]


def test_an_instance_from_before_the_cursors_existed_falls_back_to_its_creation(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from sqlalchemy import update

    from maity_hub import tables as t

    owner = flow.human(make_client, migrated)
    flow.project(owner)
    first = flow.agent(make_client, owner)  # never resumes
    left = tell(owner, f"{first.id}#{first.instance}", "undone")
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == first.credential_id)
            .values(exchange_seq=None)
        )
    second = replace(make_client, owner, first)
    assert left in seqs(second.resume().json()["handover"])
