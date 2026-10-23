"""The team's rules at work: distribution, review, wake, an instance's own pause and
presence (docs/api.md §5.3, §6.17, §6.18, §8.2)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, events, listening
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

WORK = "w-0123456789ab"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _team(owner: flow.Human, member_id: str, **team: Any) -> Any:
    response = owner.patch(f"/projects/maity/members/{member_id}", {"team": team})
    assert response.status_code == 200, response.text
    return response


def _pair(
    make_client: ClientFactory, owner: flow.Human, distribution: str = "free", **join: Any
) -> tuple[flow.Agent, flow.Agent]:
    """One team of two instances, both resumed."""
    first = flow.agent(make_client, owner, **join)
    _team(owner, first.id, max_instances=2, distribution=distribution)
    second = flow.agent(make_client, owner, agent={"id": first.id}, new_instance=True)
    for agent in (first, second):
        assert agent.resume().status_code == 200
    return first, second


def _assigned(owner: flow.Human, agent: flow.Agent, **body: Any) -> dict[str, Any]:
    card = owner.post("/projects/maity/tasks", {"title": "A card"})
    assert card.status_code == 201, card.text
    response = owner.post(
        f"/projects/maity/tasks/{card.json()['id']}/assign", {"assignee": agent.id, **body}
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _session(agent: flow.Agent) -> str:
    session: str = agent.resume().json()["session"]["id"]  # its open session from now on
    return session


@pytest.fixture
def listens() -> Iterator[list[str]]:
    """Session ids marked as holding a long-poll, unmarked after the test."""
    opened: list[str] = []
    yield opened
    for session_id in opened:
        listening.closed(session_id)


def _listen(listens: list[str], agent: flow.Agent) -> None:
    session_id = _session(agent)
    listening.opened(session_id)
    listens.append(session_id)


def _last(engine: Engine, kind: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq.desc())
        ).first()


def _membership(engine: Engine, agent: flow.Agent) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()


# --- distribution ------------------------------------------------------------------------


def test_an_assigned_instance_is_the_only_one_to_claim(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner, "round_robin")
    card = _assigned(owner, first, instance=second.instance)
    assert card["assigned_instance"] == second.instance
    refused = first.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "instance_assigned"
    assert refused.json()["error"]["details"] == {"assigned_instance": second.instance}
    claimed = second.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    assert claimed.status_code == 200 and claimed.json()["claim"]["instance"] == second.instance


def test_an_unknown_instance_is_refused_on_assign(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = owner.post("/projects/maity/tasks", {"title": "A card"}).json()
    response = owner.post(
        f"/projects/maity/tasks/{card['id']}/assign", {"assignee": agent.id, "instance": "zzzz"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"instance": "not_an_instance"}


def test_under_lead_the_lead_hands_out_the_teams_cards(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    lead, other = _pair(make_client, owner)
    _team(owner, lead.id, distribution="lead", lead_instance=lead.instance)
    card = _assigned(owner, lead)
    assert card["assigned_instance"] is None
    path = f"/projects/maity/tasks/{card['id']}"
    refused = other.post(f"{path}/claim", {})
    assert refused.json()["error"]["code"] == "instance_assigned"
    assert refused.json()["error"]["details"] == {"assigned_instance": None}
    # The lead is no admin, yet hands the card to an instance of its own team.
    handed = lead.post(f"{path}/assign", {"assignee": lead.id, "instance": other.instance})
    assert handed.status_code == 200, handed.text
    assert other.post(f"{path}/claim", {}).status_code == 200
    # It does not hand out cards beyond its team, nor does a sibling.
    elsewhere = owner.post("/projects/maity/tasks", {"title": "Another"}).json()
    response = lead.post(f"/projects/maity/tasks/{elsewhere['id']}/assign", {"assignee": lead.id})
    assert response.status_code == 403
    own = _assigned(owner, lead)
    sibling = other.post(
        f"/projects/maity/tasks/{own['id']}/assign",
        {"assignee": lead.id, "instance": other.instance},
    )
    assert sibling.status_code == 403


def test_under_lead_the_lead_claims_an_unassigned_card_itself(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    lead, _ = _pair(make_client, owner)
    _team(owner, lead.id, distribution="lead", lead_instance=lead.instance)
    card = _assigned(owner, lead)
    assert lead.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200


def test_round_robin_takes_turns_and_skips_a_paused_instance(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    _team(owner, first.id, distribution="round_robin")
    turns = [_assigned(owner, first)["assigned_instance"] for _ in range(3)]
    assert turns == [first.instance, second.instance, first.instance]
    paused = owner.patch(
        f"/projects/maity/members/{first.id}",
        {"paused": {"reason": "quota", "instance": second.instance}},
    )
    assert paused.status_code == 200, paused.text
    assert _assigned(owner, first)["assigned_instance"] == first.instance


def test_a_free_team_leaves_the_card_to_any_instance(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    _, second = _pair(make_client, owner)
    card = _assigned(owner, second)
    assert card["assigned_instance"] is None
    assert second.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200


# --- review within the team ----------------------------------------------------------------


def _reported(owner: flow.Human, author: flow.Agent) -> str:
    card = _assigned(owner, author, instance=author.instance)
    path = f"/projects/maity/tasks/{card['id']}"
    assert author.post(f"{path}/claim", {}).status_code == 200
    report = author.post(f"{path}/report", {"summary": "Done.", "pr_status": "none", "code": False})
    assert report.status_code == 200, report.text
    card_id: str = card["id"]
    return card_id


@pytest.mark.parametrize("within", [False, True])
def test_review_within_the_team(
    owner: flow.Human, make_client: ClientFactory, within: bool
) -> None:
    owner.patch("/projects/maity", {"policy": {"done_authority": "admin"}, "reason": "test"})
    author, reviewer = _pair(make_client, owner, "round_robin", role="admin")
    if within:
        _team(owner, author.id, review_within_team=True)
    card_id = _reported(owner, author)
    response = reviewer.patch(f"/projects/maity/tasks/{card_id}", {"status": "done"})
    if within:
        assert response.status_code == 200, response.text
        return
    assert response.status_code == 403, response.text
    details = response.json()["error"]["details"]
    assert details == {"reason": "same_team_review", "instance": author.instance}
    # The owner, outside the team, reviews as before.
    assert owner.patch(f"/projects/maity/tasks/{card_id}", {"status": "done"}).status_code == 200


# --- instance tokens and the team wake -----------------------------------------------------


class _Reader:
    def __init__(self, membership: Any) -> None:
        self.id = membership.id
        self.role = membership.role
        self.agent_id = membership.agent_id


def test_an_instance_token_is_read_by_the_team_and_wakes_only_that_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner, "round_robin")
    card = _assigned(owner, first, instance=first.instance)
    event = _last(migrated, "task_assigned")
    assert f"instance:{first.id}#{first.instance}" in event.audience
    assert f"member:{first.id}" not in event.audience
    reader = _Reader(_membership(migrated, first))
    assert events.readable_by(event, reader, first.id)
    assert events.wakes(event, reader, first.id, first.instance)
    assert not events.wakes(event, reader, first.id, second.instance)
    items = second.get("/projects/maity/events").json()["items"]
    assert card["id"] in {(i["subject"] or {}).get("id") for i in items}


def test_an_instance_token_never_opens_a_humans_only_event(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    reader = _Reader(_membership(migrated, agent))
    row = _Row("shared_environment_detected", [f"instance:{agent.id}#{agent.instance}"], None, None)
    assert not events.readable_by(row, reader, agent.id)
    tombstone = _Row("event_redacted", [f"instance:{agent.id}#{agent.instance}"], None, "7")
    assert not events.readable_by(tombstone, reader, agent.id, frozenset({"7"}))


class _Row:
    def __init__(self, kind: str, audience: list[str], wakes: Any, subject_id: str | None) -> None:
        self.kind = kind
        self.audience = audience
        self.wakes = wakes
        self.subject_id = subject_id
        self.actor_membership = None
        self.actor_credential_id = None
        self.conversation_id = None


def test_without_a_narrowing_team_an_event_records_no_wakes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _assigned(owner, agent)
    assert _last(migrated, "task_assigned").wakes is None
    item = owner.get("/projects/maity/events").json()["items"][-1]
    assert "wakes" not in item


def test_next_free_wakes_the_listening_instance_with_the_fewest_claims(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, listens: list[str]
) -> None:
    first, second = _pair(make_client, owner)
    busy = _assigned(owner, first)
    assert first.post(f"/projects/maity/tasks/{busy['id']}/claim", {}).status_code == 200
    _team(owner, first.id, wake="next_free")
    _listen(listens, first)
    _listen(listens, second)
    _assigned(owner, first)
    event = _last(migrated, "task_assigned")
    assert event.wakes == {first.id: [second.instance]}
    reader = _Reader(_membership(migrated, first))
    assert events.wakes(event, reader, first.id, second.instance)
    assert not events.wakes(event, reader, first.id, first.instance)
    item = owner.get("/projects/maity/events").json()["items"][-1]
    assert item["wakes"] == [f"{first.id}#{second.instance}"]


def test_a_lead_team_wakes_its_lead_and_nobody_when_it_does_not_listen(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, listens: list[str]
) -> None:
    lead, other = _pair(make_client, owner)
    _team(owner, lead.id, wake="lead", lead_instance=lead.instance)
    _listen(listens, other)
    _assigned(owner, lead)
    event = _last(migrated, "task_assigned")
    assert event.wakes == {lead.id: []}
    reader = _Reader(_membership(migrated, lead))
    assert not events.wakes(event, reader, lead.id, other.instance)
    _listen(listens, lead)
    _assigned(owner, lead)
    assert _last(migrated, "task_assigned").wakes == {lead.id: [lead.instance]}
    # Back to all: the project stops looking.
    _team(owner, lead.id, wake="all")
    _assigned(owner, lead)
    assert _last(migrated, "task_assigned").wakes is None


# --- an instance's own pause and presence --------------------------------------------------


def test_a_paused_instance_takes_no_new_work_while_its_sibling_does(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    path = f"/projects/maity/members/{first.id}"
    response = owner.patch(path, {"paused": {"reason": "too fast", "instance": first.instance}})
    assert response.status_code == 200, response.text
    view = {i["id"]: i for i in response.json()["instances"]}
    assert view[first.instance]["paused"]["reason"] == "too fast"
    assert view[first.instance]["presence"] == "paused"
    assert view[second.instance]["paused"] is None
    assert response.json()["paused"] is None  # the membership is not paused
    announced = _last(migrated, "session_paused")
    assert announced.payload["instance"] == first.instance
    assert f"instance:{first.id}#{first.instance}" in announced.audience
    card = owner.post("/projects/maity/tasks", {"title": "A card"}).json()
    refused = first.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "paused"
    assert refused.json()["error"]["details"]["instance"] == first.instance
    own = first.patch("/me", {"paused": None})
    assert own.json()["error"]["details"]["reason"] == "paused_by_human"
    assert second.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200
    # Not lifted by its resume; lifted with `paused: null` and the instance.
    assert first.resume().json()["membership"]["paused"]["reason"] == "too fast"
    lifted = owner.patch(path, {"paused": None, "instance": first.instance})
    assert lifted.status_code == 200, lifted.text
    assert _last(migrated, "session_paused").payload["paused"] is None


def test_instance_goes_with_paused_only(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    response = owner.patch(
        f"/projects/maity/members/{agent.id}", {"areas": ["hub/"], "instance": agent.instance}
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"instance": "paused_only"}


def test_a_members_presence_is_the_best_of_its_instances(
    owner: flow.Human, make_client: ClientFactory, listens: list[str]
) -> None:
    first, second = _pair(make_client, owner)
    _listen(listens, second)
    first.patch("/me", {"paused": {"reason": "waiting"}})
    view = owner.get(f"/projects/maity/members/{first.id}").json()
    presences = {i["id"]: i["presence"] for i in view["instances"]}
    assert presences == {first.instance: "paused", second.instance: "online"}
    assert view["presence"] == "online"


def test_two_instances_in_one_workspace_are_shown_to_the_owner(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    for agent in (first, second):
        assert agent.resume(environment={"workspace": WORK}).status_code == 200
    view = owner.get(f"/projects/maity/members/{first.id}").json()
    shared = {i["id"]: i["shared_environment"] for i in view["instances"]}
    assert shared == {
        first.instance: [{"instance": second.instance, "level": "workspace"}],
        second.instance: [{"instance": first.instance, "level": "workspace"}],
    }
    assert view["shared_environment"] == []  # between members only (§5.3)
    peer = first.get(f"/projects/maity/members/{first.id}").json()
    assert all("shared_environment" not in i for i in peer["instances"])


def test_a_message_to_an_instance_address_wakes_that_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner)
    address = f"{first.id}#{second.instance}"
    sent = owner.post(
        "/projects/maity/events",
        {"kind": "message", "type": "notice", "to": address, "body": "Over to you."},
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["payload"]["to"] == address
    event = _last(migrated, "message")
    assert f"instance:{first.id}#{second.instance}" in event.audience
    reader = _Reader(_membership(migrated, first))
    assert events.wakes(event, reader, first.id, second.instance)
    assert not events.wakes(event, reader, first.id, first.instance)
    assert events.readable_by(event, reader, first.id)
    unknown = owner.post(
        "/projects/maity/events",
        {"kind": "message", "type": "notice", "to": f"{first.id}#zzzz", "body": "Hm."},
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["fields"] == {"to": "not_an_instance"}


# --- review findings ---------------------------------------------------------------------


def test_the_lead_never_moves_a_held_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead, _ = _pair(make_client, owner)
    _team(owner, lead.id, distribution="lead", lead_instance=lead.instance)
    outsider = flow.agent(make_client, owner)
    for holder in (owner, outsider):
        card = _assigned(owner, lead)
        path = f"/projects/maity/tasks/{card['id']}"
        claimed = holder.post(f"{path}/claim", {})
        assert claimed.status_code == 200, claimed.text
        with migrated.begin() as conn:
            conn.execute(
                t.card.update().where(t.card.c.id == card["id"]).values(lease_until=clock.now())
            )
        moved = lead.post(f"{path}/assign", {"assignee": lead.id, "instance": lead.instance})
        if holder is owner:
            assert moved.status_code == 403, moved.text
            assert moved.json()["error"]["details"]["reason"] == "humans_only"
        else:
            assert moved.status_code == 409, moved.text
            assert moved.json()["error"]["code"] == "takeover_required"
        assert owner.get(f"{path}").json()["claim"]["holder"] == holder.id


def test_a_held_card_does_not_move_to_a_sibling_by_assign(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner, "round_robin")
    card = _assigned(owner, first, instance=first.instance)
    path = f"/projects/maity/tasks/{card['id']}"
    assert first.post(f"{path}/claim", {}).status_code == 200
    with migrated.begin() as conn:
        conn.execute(
            t.card.update().where(t.card.c.id == card["id"]).values(lease_until=clock.now())
        )
    moved = owner.post(f"{path}/assign", {"assignee": first.id, "instance": second.instance})
    assert moved.status_code == 409 and moved.json()["error"]["code"] == "takeover_required"


def test_round_robin_applies_on_every_path_that_assigns(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner, "round_robin")
    created = owner.post("/projects/maity/tasks", {"title": "Made", "assigned_to": first.id})
    assert created.json()["assigned_instance"] == first.instance
    other = owner.post("/projects/maity/tasks", {"title": "Later"}).json()
    patched = owner.patch(f"/projects/maity/tasks/{other['id']}", {"assigned_to": first.id})
    assert patched.json()["assigned_instance"] == second.instance
    owner.patch(f"/projects/maity/members/{first.id}", {"areas": ["hub/"]})
    found = owner.post("/projects/maity/tasks", {"title": "Found", "area": "hub/"})
    assert found.json()["assigned_to"] == first.id
    assert found.json()["assigned_instance"] == first.instance


def test_round_robin_takes_turns_when_two_instances_share_a_moment(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _pair(make_client, owner, "round_robin")
    with migrated.begin() as conn:
        same = conn.execute(
            select(t.credential.c.created_at).where(t.credential.c.instance == first.instance)
        ).scalar_one()
        conn.execute(
            t.credential.update()
            .where(t.credential.c.instance == second.instance)
            .values(created_at=same)
        )
    turns = [_assigned(owner, first)["assigned_instance"] for _ in range(4)]
    assert sorted(turns) == sorted([first.instance, second.instance] * 2)
    assert turns[0] != turns[1] and turns[1] != turns[2]


def test_an_instance_under_free_is_refused(owner: flow.Human, make_client: ClientFactory) -> None:
    first, _ = _pair(make_client, owner)
    card = owner.post("/projects/maity/tasks", {"title": "A card"}).json()
    response = owner.post(
        f"/projects/maity/tasks/{card['id']}/assign",
        {"assignee": first.id, "instance": first.instance},
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"instance": "distribution_free"}


def test_reporting_again_does_not_clear_another_instances_work(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner.patch("/projects/maity", {"policy": {"done_authority": "admin"}, "reason": "test"})
    author, reviewer = _pair(make_client, owner, "round_robin", role="admin")
    card_id = _reported(owner, author)
    with migrated.begin() as conn:  # the sibling came to hold it some other way
        conn.execute(
            t.card.update()
            .where(t.card.c.id == card_id)
            .values(status="in_progress", claim_instance=reviewer.instance)
        )
    again = reviewer.post(
        f"/projects/maity/tasks/{card_id}/report",
        {"summary": "Mine now.", "pr_status": "none", "code": False},
    )
    assert again.status_code == 200, again.text
    assert "reported_instances" not in again.json()["report"]
    done = reviewer.patch(f"/projects/maity/tasks/{card_id}", {"status": "done"})
    assert done.status_code == 403, done.text
    assert done.json()["error"]["details"] == {
        "reason": "same_team_review",
        "instance": author.instance,
    }


def test_an_outsider_does_not_read_an_instance_token(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    outsider = flow.agent(make_client, owner)
    address = f"{first.id}#{second.instance}"
    sent = owner.post(
        "/projects/maity/events",
        {"kind": "message", "type": "notice", "to": address, "body": "For you."},
    ).json()
    seen = {i["seq"] for i in outsider.get("/projects/maity/events").json()["items"]}
    assert sent["seq"] not in seen
    team = {i["seq"] for i in first.get("/projects/maity/events").json()["items"]}
    assert sent["seq"] in team


def test_the_long_poll_wakes_only_the_addressed_instance(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    first, second = _pair(make_client, owner)
    cursor = owner.get("/projects/maity/events").json()["cursor"]
    owner.post(
        "/projects/maity/events",
        {
            "kind": "message",
            "type": "notice",
            "to": f"{first.id}#{second.instance}",
            "body": "Wake up.",
        },
    )
    woken = second.get(f"/projects/maity/events?after={cursor}&wait=1").json()["items"]
    assert [i["payload"]["body"] for i in woken] == ["Wake up."]
    asleep = first.get(f"/projects/maity/events?after={cursor}&wait=1").json()["items"]
    assert asleep == []


def test_an_admin_agents_pause_is_named_as_such(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    with migrated.begin() as conn:
        conn.execute(
            t.credential.update()
            .where(t.credential.c.id == agent.credential_id)
            .values(paused_reason="hold", paused_since=clock.now(), paused_by=admin.id)
        )
    response = agent.patch("/me", {"paused": None})
    assert response.status_code == 403
    assert response.json()["error"]["details"] == {"reason": "paused_by_admin"}


def test_removing_the_last_narrowing_team_stops_the_lookup(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, _ = _pair(make_client, owner)
    _team(owner, first.id, wake="next_free")
    assert owner.delete(f"/projects/maity/members/{first.id}").status_code == 200
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.team_wake)).scalar_one() is False
