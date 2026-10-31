"""docs/api.md §3.1, §3.2, §5.2, §6.2, §8.1: a first join names whose work the new agent continues
(`takes_over`) and where the hand-over is written (`handover`); neither moves anything."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
JOINS = f"{PROJECT}/joins"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def old(owner: flow.Human, make_client: ClientFactory) -> flow.Agent:
    return flow.agent(make_client, owner, agent={"handle": "old-one", "display_name": "Old One"})


def card(owner: flow.Human) -> str:
    response = owner.post(f"{PROJECT}/tasks", {"title": "What the old agent left"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def refused(response: Any, field: str, reason: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {field: reason}


def new_join(owner: flow.Human, n: int = 1, **body: Any) -> Any:
    return owner.post(
        JOINS, {"agent": {"handle": f"new-one-{n}", "display_name": f"New {n}"}, **body}
    )


def test_a_join_names_the_agent_it_continues_and_the_hand_over(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    left = card(owner)
    created = new_join(owner, takes_over=old.id, handover=left)
    assert created.status_code == 201, created.text
    [listed] = [j for j in owner.get(JOINS).json()["items"] if j["id"] == created.json()["id"]]
    assert (listed["takes_over"], listed["handover"]) == (old.id, {"kind": "task", "id": left})
    new = _exchanged(make_client, created.json())
    expected = {"member_id": old.id, "handle": "old-one", "name": "maintainer/old-one"}
    view = owner.get(f"{PROJECT}/members/{new.id}").json()
    assert (view["takes_over"], view["handover"]) == (expected, {"kind": "task", "id": left})
    other = owner.get(f"{PROJECT}/members/{old.id}").json()
    assert (other["takes_over"], other["handover"]) == (None, None)  # nothing moved (§3.1)
    assert other["trust"] == "member"
    packet = new.resume().json()["membership"]
    assert (packet["takes_over"], packet["handover"]) == (expected, {"kind": "task", "id": left})
    assert "What the old agent left" not in str(view) + str(packet)  # never a text


def test_the_packet_drops_both_once_the_member_has_checked_in(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    created = new_join(owner, takes_over=old.id, handover=card(owner))
    new = _exchanged(make_client, created.json())
    with migrated.begin() as conn:
        from sqlalchemy import update

        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == new.id)
            .values(onboarded_at=_now())
        )
    packet = new.resume().json()["membership"]
    assert (packet["takes_over"], packet["handover"]) == (None, None)
    view = owner.get(f"{PROJECT}/members/{new.id}").json()  # the member view keeps them
    assert view["takes_over"]["handle"] == "old-one" and view["handover"]["kind"] == "task"


def _now() -> Any:
    from maity_hub import clock

    return clock.now()


def _exchanged(make_client: ClientFactory, created: dict[str, Any]) -> flow.Agent:
    client = make_client()
    response = flow.exchange(client, created)
    assert response.status_code == 201, response.text
    return flow.Agent(
        client,
        response.text,
        response.headers["Maity-Credential-Id"],
        response.headers["Maity-Member-Id"],
        response.headers["Maity-Instance"],
    )


def test_the_name_stays_as_it_was_after_the_other_member_is_removed(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory
) -> None:
    new = _exchanged(make_client, new_join(owner, takes_over=old.id).json())
    assert owner.delete(f"{PROJECT}/members/{old.id}").status_code == 200
    taken = new.resume().json()["membership"]["takes_over"]
    assert taken == {"member_id": old.id, "handle": "old-one", "name": "maintainer/old-one"}


def test_member_joined_is_also_told_to_the_lead_of_the_member_it_continues(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead = flow.agent(
        make_client, owner, agent={"handle": "the-lead", "display_name": "Lead"}, role="manager"
    )
    old = flow.agent(
        make_client, owner, agent={"handle": "old-two", "display_name": "Old"}, reports_to=lead.id
    )
    _exchanged(make_client, new_join(owner, 2, takes_over=old.id).json())
    _exchanged(make_client, new_join(owner, 3).json())
    with migrated.connect() as conn:
        audiences = [
            row.audience
            for row in conn.execute(
                select(t.event).where(t.event.c.kind == "member_joined").order_by(t.event.c.seq)
            )
        ]
    with_takeover, plain = audiences[-2], audiences[-1]
    assert "all" in with_takeover and f"member:{lead.id}" in with_takeover
    assert "trust:admin" in with_takeover  # the default coordinator (§6.12)
    assert plain == ["all"]


def test_an_isolated_lead_is_not_told_who_continues_the_work(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead = flow.agent(
        make_client, owner, agent={"handle": "the-boss", "display_name": "Boss"}, role="manager"
    )
    old = flow.agent(
        make_client, owner, agent={"handle": "old-three", "display_name": "Old"}, reports_to=lead.id
    )
    isolated = owner.post(f"{PROJECT}/members/{lead.id}/isolate", {"reason": "it went astray"})
    assert isolated.status_code == 200, isolated.text
    _exchanged(make_client, new_join(owner, 9, takes_over=old.id).json())
    with migrated.connect() as conn:
        told = conn.execute(
            select(t.event.c.audience)
            .where(t.event.c.kind == "member_joined")
            .order_by(t.event.c.seq.desc())
        ).first()
    assert told is not None and f"member:{lead.id}" not in told.audience


def test_takes_over_is_for_a_first_join_only(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory
) -> None:
    for extra in ({"new_instance": True}, {"replaces": old.instance}):
        refused(
            owner.post(JOINS, {"agent": {"id": old.id}, "takes_over": old.id, **extra}),
            "takes_over",
            "first_join_only",
        )
    refused(
        new_join(owner, 4, takes_over=old.id, new_instance=True), "takes_over", "first_join_only"
    )


def test_takes_over_names_another_agent_member_of_the_project(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory
) -> None:
    for named in (owner.id, "agt-nobody", old.id + "x"):
        refused(new_join(owner, takes_over=named), "takes_over", "not_an_agent_member")
    flow.project(owner, "elsewhere")  # an agent of another project is no member here
    foreign = flow.agent(
        make_client, owner, "elsewhere", agent={"handle": "far-away", "display_name": "F"}
    )
    refused(new_join(owner, takes_over=foreign.id), "takes_over", "not_an_agent_member")
    refused(new_join(owner, takes_over=old.id, new_instance=True), "takes_over", "first_join_only")


def test_handover_is_a_card_of_the_project_or_a_message_to_everyone(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory
) -> None:
    refused(new_join(owner, handover="tsk-nothing"), "handover", "not_found")
    refused(new_join(owner, handover=999999), "handover", "not_found")
    owner.post("/projects", {"slug": "elsewhere", "name": "Elsewhere"})
    foreign = owner.post("/projects/maintainer/elsewhere/tasks", {"title": "Not ours"}).json()["id"]
    refused(new_join(owner, handover=foreign), "handover", "not_found")
    said = owner.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "The hand-over: read X."},
    )
    assert said.status_code == 201, said.text
    seq = said.json()["seq"]
    created = new_join(owner, 5, takes_over=old.id, handover=seq)
    assert created.status_code == 201, created.text
    new = _exchanged(make_client, created.json())
    assert new.resume().json()["membership"]["handover"] == {"kind": "message", "id": seq}
    private = owner.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": old.id, "body": "Between us."},
    )
    assert private.status_code == 201, private.text
    refused(new_join(owner, 6, handover=private.json()["seq"]), "handover", "not_readable")


def test_a_member_may_name_only_an_agent_of_their_own(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests import factory

    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, project_id, "member", human_id=friend.id)
    body = {"agent": {"handle": "friends-new", "display_name": "N"}}
    response = friend.post(JOINS, {**body, "takes_over": old.id})  # the owner's agent
    assert response.status_code == 403, response.text
    assert response.json()["error"]["details"] == {
        "reason": "member_join_limit",
        "field": "takes_over",
    }
    mine = flow.agent(make_client, friend, agent={"handle": "friends-old", "display_name": "O"})
    again = friend.post(
        JOINS, {"agent": {"handle": "friends-next", "display_name": "N2"}, "takes_over": mine.id}
    )
    assert again.status_code == 201, again.text


def test_a_join_without_either_leaves_both_null(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory
) -> None:
    new = _exchanged(make_client, new_join(owner, 7).json())
    packet = new.resume().json()["membership"]
    assert (packet["takes_over"], packet["handover"]) == (None, None)


def test_the_join_page_says_who_is_continued_and_never_the_hand_over(
    owner: flow.Human, old: flow.Agent, make_client: ClientFactory
) -> None:
    left = card(owner)
    created = new_join(owner, takes_over=old.id, handover=left).json()
    page = make_client().get(created["join_url"].replace("https://hub.example", "")).text
    assert "You continue the work of `old-one`; the hand-over is in your first resume." in page
    assert left not in page and "What the old agent left" not in page
    plain = new_join(owner, 8).json()
    text = make_client().get(plain["join_url"].replace("https://hub.example", "")).text
    assert "You continue the work of" not in text
