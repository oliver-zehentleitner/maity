"""docs/api.md §6.12 stage 2: cover by a substitute, the return, and the coordinator gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import availability, clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


def z(moment: datetime) -> str:
    return clock.rfc3339(moment)


def events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def policy(owner: flow.Human, member_id: str, **body: Any) -> None:
    response = owner.patch(f"/projects/maity/members/{member_id}", {"availability_policy": body})
    assert response.status_code == 200, response.text


def card_of(who: Any, card_id: str) -> dict[str, Any]:
    found: dict[str, Any] = who.get(f"/projects/maity/tasks/{card_id}").json()
    return found


def ask(who: Any, to: str, klass: str = "decision") -> dict[str, Any]:
    body: dict[str, Any] = {"class": klass, "title": f"A {klass}", "to": to}
    response = who.post("/projects/maity/requests", body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def limit(agent: flow.Agent, until: datetime) -> None:
    response = agent.post("/me/limit", {"until": z(until)})
    assert response.status_code == 200, response.text


# --- cover and return ---------------------------------------------------------------------------


def test_a_substitute_takes_the_work_and_gives_back_what_it_did_not_touch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    covered = flow.agent(make_client, owner, reports_to=owner.id)
    sub = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    for agent in (covered, sub, asker):
        agent.resume()
    held, assigned, other = task(owner), task(owner), task(owner)
    covered.post(f"/projects/maity/tasks/{held['id']}/claim", {})
    owner.post(f"/projects/maity/tasks/{assigned['id']}/assign", {"assignee": covered.id})
    request = ask(asker, covered.id)
    policy(owner, covered.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=0)

    limit(covered, now[0] + timedelta(hours=2))
    changed = events(migrated, "member_availability_changed")[-1]
    assert changed.payload["cover"] == "substitute"
    [started] = events(migrated, "cover_started")
    assert changed.seq < started.seq  # the outage is announced first, then the cover
    assert {**started.payload, "tasks": sorted(started.payload["tasks"])} == {
        "member_id": covered.id,
        "substitute_id": sub.id,
        "tasks": sorted([held["id"], assigned["id"]]),
        "requests": [request["id"]],
        "left": [],
    }
    assert started.audience == [
        f"member:{covered.id}",
        f"member:{sub.id}",
        f"member:{owner.id}",
        "role:admin",
    ]
    assert [e.payload["reason"] for e in events(migrated, "task_assigned")][-2:] == [
        "cover",
        "cover",
    ]
    moved = card_of(owner, held["id"])
    assert moved["claim"]["holder"] == sub.id
    assert moved["cover"] == {"for": covered.id, "by": sub.id, "since": z(now[0])}
    assert card_of(owner, assigned["id"])["assigned_to"] == sub.id
    assert card_of(owner, other["id"])["cover"] is None
    covered_view = owner.get(f"/projects/maity/members/{covered.id}").json()
    assert covered_view["covered_by"] == {"member_id": sub.id, "since": z(now[0])}
    assert owner.get(f"/projects/maity/members/{sub.id}").json()["covering"] == [
        {"member_id": covered.id, "since": z(now[0])}
    ]
    inbox = sub.get("/projects/maity/requests?to=me").json()["items"]
    assert [r["id"] for r in inbox] == [request["id"]]
    assert inbox[0]["cover"] == {"for": covered.id, "by": sub.id, "since": z(now[0])}
    assert sub.resume().json()["membership"]["covering"] == [
        {"member_id": covered.id, "since": z(now[0])}
    ]

    # The substitute works on one card, and the member comes back.
    sub.post(f"/projects/maity/tasks/{held['id']}/checkpoint", {"last_step": "a", "next_step": "b"})
    now[0] += timedelta(minutes=30)
    covered.resume()
    [ended] = events(migrated, "cover_ended")
    assert ended.payload["kept"] == [held["id"]]
    assert sorted(ended.payload["returned"]) == sorted([assigned["id"], request["id"]])
    assert card_of(owner, held["id"])["claim"]["holder"] == sub.id  # touched: stays
    back = card_of(owner, assigned["id"])
    assert back["assigned_to"] == covered.id and back["cover"] is None
    assert owner.get(f"/projects/maity/members/{covered.id}").json()["covered_by"] is None
    assert sub.get("/projects/maity/requests?to=me").json()["items"] == []


def test_a_substitute_answers_on_the_covered_members_behalf(
    owner: flow.Human, make_client: ClientFactory, now: list[datetime]
) -> None:
    covered = flow.agent(make_client, owner)
    sub = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    for agent in (covered, sub, asker):
        agent.resume()
    request = ask(asker, covered.id)
    policy(owner, covered.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=0)
    limit(covered, now[0] + timedelta(hours=1))
    answered = sub.post(
        f"/projects/maity/requests/{request['id']}/answer", {"text": "yes, from the stand-in"}
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"]["by"] == sub.id
    assert answered.json()["answer"]["on_behalf_of"] == covered.id


def test_cover_never_hands_over_what_the_entry_may_not_take(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    covered = flow.agent(make_client, owner, role="admin")  # a consent may go to it
    reviewer = flow.agent(make_client, owner, role="reviewer")
    member = flow.agent(make_client, owner)
    for agent in (covered, reviewer, member):
        agent.resume()
    in_review = task(owner)
    covered.post(f"/projects/maity/tasks/{in_review['id']}/claim", {})
    covered.post(
        f"/projects/maity/tasks/{in_review['id']}/report",
        {"summary": "done", "code": False, "pr_status": "none"},
    )
    own_question = ask(reviewer, covered.id)  # the reviewer's own question
    consent = ask(member, covered.id, klass="consent")  # needs requests:answer
    policy(
        owner,
        covered.id,
        on_unavailable="substitute",
        substitutes=[reviewer.id, member.id],
        grace_minutes=0,
    )
    limit(covered, now[0] + timedelta(hours=1))
    started = {e.payload["substitute_id"]: e.payload for e in events(migrated, "cover_started")}
    # The review goes to the one without done authority; the reviewer's own question
    # to the next entry; the consent to nobody: neither holds requests:answer.
    assert started[member.id]["tasks"] == [in_review["id"]]
    assert started[member.id]["requests"] == [own_question["id"]]
    assert started[member.id]["left"] == [consent["id"]]
    assert reviewer.id not in started  # it took nothing: no cover_started for it


def test_a_humans_owner_decisions_and_consents_wait_for_a_human(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    sub = flow.agent(make_client, owner)
    asker = flow.agent(make_client, owner)
    for agent in (sub, asker):
        agent.resume()
    decision = ask(asker, owner.id)
    to_owner = ask(asker, "owner")
    policy(owner, owner.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=0)
    response = owner.post("/me/limit", {"until": z(now[0] + timedelta(hours=3))})
    assert response.status_code == 200, response.text
    [started] = events(migrated, "cover_started")
    assert started.payload["requests"] == []  # every request to the owner is an owner decision
    assert sorted(started.payload["left"]) == sorted([decision["id"], to_owner["id"]])


def test_the_policy_acts_only_after_the_grace_and_never_for_a_limit_within_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    short = flow.agent(make_client, owner)
    long = flow.agent(make_client, owner)
    sub = flow.agent(make_client, owner)
    for agent in (short, long, sub):
        agent.resume()
    for member in (short, long):
        policy(
            owner, member.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=15
        )
    limit(short, now[0] + timedelta(minutes=10))
    limit(long, now[0] + timedelta(hours=2))
    assert events(migrated, "cover_started") == []
    assert events(migrated, "member_availability_changed")[-1].payload["cover"] is None
    sub.get("/me")  # keeps the substitute present
    now[0] += timedelta(minutes=16)
    sub.get("/me")
    availability.sweep(migrated)
    started = events(migrated, "cover_started")
    assert [e.payload["member_id"] for e in started] == [long.id]


def test_with_nobody_available_the_cover_waits_and_tries_again(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    covered = flow.agent(make_client, owner)
    sub = flow.agent(make_client, owner)  # never resumed: offline
    covered.resume()
    card = task(owner)
    covered.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    policy(owner, covered.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=0)
    limit(covered, now[0] + timedelta(hours=2))
    assert events(migrated, "member_availability_changed")[-1].payload["cover"] == "none_available"
    assert events(migrated, "cover_started") == []
    sub.resume()
    availability.sweep(migrated)
    [started] = events(migrated, "cover_started")
    assert started.payload["tasks"] == [card["id"]]


def test_the_wait_policy_moves_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    policy(owner, agent.id, grace_minutes=0)
    limit(agent, now[0] + timedelta(hours=1))
    assert events(migrated, "member_availability_changed")[-1].payload["cover"] == "wait"
    assert events(migrated, "cover_started") == []


def test_area_routing_sends_a_new_card_to_the_substitute(
    owner: flow.Human, make_client: ClientFactory, now: list[datetime]
) -> None:
    covered = flow.agent(make_client, owner, areas=["hub/"])
    sub = flow.agent(make_client, owner)
    for agent in (covered, sub):
        agent.resume()
    policy(owner, covered.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=0)
    limit(covered, now[0] + timedelta(hours=1))
    routed = task(owner, area="hub/")
    assert routed["assigned_to"] == sub.id
    assert routed["cover"] == {"for": covered.id, "by": sub.id, "since": z(now[0])}
    covered.resume()  # back: an untouched routed card returns as well
    assert card_of(owner, routed["id"])["assigned_to"] == covered.id


# --- the coordinator gate -----------------------------------------------------------------------


def test_agents_make_no_new_assignments_while_the_coordinator_is_out(
    owner: flow.Human, make_client: ClientFactory, now: list[datetime]
) -> None:
    lead = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    stand_in = flow.agent(make_client, owner, role="admin")
    worker = flow.agent(make_client, owner)
    for agent in (lead, admin, stand_in, worker):
        agent.resume()
    owner.patch("/projects/maity", {"policy": {"coordinator": lead.id}, "reason": "t"})
    policy(owner, lead.id, grace_minutes=0)
    until = now[0] + timedelta(hours=3)
    limit(lead, until)
    card = task(owner)
    refused = admin.post(f"/projects/maity/tasks/{card['id']}/assign", {"assignee": worker.id})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "coordinator_unavailable"
    assert refused.json()["error"]["details"] == {"coordinator": lead.id, "until": z(until)}
    on_behalf = admin.post(f"/projects/maity/tasks/{card['id']}/claim", {"holder": worker.id})
    assert on_behalf.json()["error"]["code"] == "coordinator_unavailable"
    # Work in progress goes on, and humans are not gated.
    assert worker.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200
    other = task(owner)
    assert (
        owner.post(
            f"/projects/maity/tasks/{other['id']}/assign", {"assignee": worker.id}
        ).status_code
        == 200
    )
    # An available coordinator_substitute lifts the gate.
    owner.patch(
        "/projects/maity", {"policy": {"coordinator_substitute": stand_in.id}, "reason": "t"}
    )
    third = task(owner)
    assert (
        admin.post(
            f"/projects/maity/tasks/{third['id']}/assign", {"assignee": worker.id}
        ).status_code
        == 200
    )


def test_no_gate_without_a_coordinator_and_none_within_the_grace(
    owner: flow.Human, make_client: ClientFactory, now: list[datetime]
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    worker = flow.agent(make_client, owner)
    for agent in (admin, worker):
        agent.resume()
    limit(admin, now[0] + timedelta(hours=1))  # the only agent admin, within its grace
    card = task(owner)
    assert (
        admin.post(
            f"/projects/maity/tasks/{card['id']}/assign", {"assignee": worker.id}
        ).status_code
        == 200
    )


# --- review of #285 -------------------------------------------------------------------------


def test_a_card_moved_on_to_a_third_member_is_never_taken_back(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    covered = flow.agent(make_client, owner)
    sub = flow.agent(make_client, owner)
    third = flow.agent(make_client, owner)
    for agent in (covered, sub, third):
        agent.resume()
    held, assigned = task(owner), task(owner)
    covered.post(f"/projects/maity/tasks/{held['id']}/claim", {})
    owner.post(f"/projects/maity/tasks/{assigned['id']}/assign", {"assignee": covered.id})
    policy(owner, covered.id, on_unavailable="substitute", substitutes=[sub.id], grace_minutes=0)
    limit(covered, now[0] + timedelta(hours=2))
    # The substitute gives the held card back to the board and a third member claims it;
    # a human hands the assigned one to the third member, who claims it too.
    assert sub.post(f"/projects/maity/tasks/{held['id']}/release").status_code == 200
    assert third.post(f"/projects/maity/tasks/{held['id']}/claim", {}).status_code == 200
    owner.post(f"/projects/maity/tasks/{assigned['id']}/assign", {"assignee": third.id})
    assert third.post(f"/projects/maity/tasks/{assigned['id']}/claim", {}).status_code == 200
    covered.resume()
    for card in (held, assigned):
        shown = card_of(owner, card["id"])
        assert shown["claim"]["holder"] == third.id and shown["cover"] is None
    ended = events(migrated, "cover_ended")
    assert all(not e.payload["returned"] and not e.payload["kept"] for e in ended)


def test_a_substitute_who_could_not_answer_a_proposals_kind_is_skipped(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    from tests import factory

    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    proxy = flow.human(make_client, migrated, handle="proxy")
    factory.membership(migrated, project_id, role="proxy", human_id=proxy.id)
    admin_human = flow.human(make_client, migrated, handle="admin")
    factory.membership(migrated, project_id, role="admin", human_id=admin_human.id)
    lead = flow.agent(make_client, owner, role="admin")
    reviewer = flow.agent(make_client, owner, role="reviewer")
    for agent in (lead, reviewer):
        agent.resume()
    # An admin agent's change of a reviewer waits for a human with members:admin.
    asked = lead.patch(f"/projects/maity/members/{reviewer.id}", {"role": "member"})
    assert asked.status_code == 202, asked.text
    policy(
        owner,
        owner.id,
        on_unavailable="substitute",
        substitutes=[proxy.id, admin_human.id],
        grace_minutes=0,
    )
    for human in (proxy, admin_human):
        human.get("/me")  # present: both could cover, by availability
    owner.post("/me/limit", {"until": z(now[0] + timedelta(hours=2))})
    started = {e.payload["substitute_id"]: e.payload for e in events(migrated, "cover_started")}
    assert started[admin_human.id]["requests"] == [asked.json()["id"]]
    assert proxy.id not in started
