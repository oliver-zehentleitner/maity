"""docs/api.md §6.5, "An outsider's claim" (tsk-5q5emh2nm61k, slice B): the claim request of
an agent with trust `outside`, its confirmation and its decline, the re-check, the declines
of other calls and of the hub, the lapse, the owner's notice, and the owner's placement.

Each rule is checked against its counter-case: the refused caller beside one the rule lets
through, the refused card beside an open one."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import claim_requests, clock, outsiders, probe, public_pages
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_outsider_join import _outside_agent

P = "/projects/maintainer/maity"
TASKS = f"{P}/tasks"


@pytest.fixture
def make_client(make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch) -> ClientFactory:
    """A hub that serves public pages, without its probe or public-pages worker."""
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    monkeypatch.setattr(public_pages.Worker, "start", lambda self: None)
    return lambda **kw: make_client(**{"public_pages": True, **kw})


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The outsiders' join switched on for the test, so an agent with trust `outside` comes
    from the real join and exchange."""
    monkeypatch.setattr(outsiders, "JOINS_ON", True)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity", public_page="on")
    return human


@pytest.fixture
def outsider(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "stranger")


@pytest.fixture
def agent(
    on: None, owner: flow.Human, outsider: flow.Human, make_client: ClientFactory
) -> flow.Agent:
    return _outside_agent(make_client, owner, outsider)


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar_one()
    return found


def _card(owner: flow.Human, title: str = "A card", **body: Any) -> str:
    body.setdefault("open_to_outsiders", True)
    made = owner.post(TASKS, {"title": title, **body})
    assert made.status_code == 201, made.text
    card_id: str = made.json()["id"]
    return card_id


def _policy(owner: flow.Human, **policy: Any) -> None:
    done = owner.patch(P, {"policy": policy, "reason": "outsiders"})
    assert done.status_code == 200, done.text


def _reason(answer: Any) -> Any:
    return answer.json()["error"]["details"].get("reason")


def _claim(agent: flow.Agent, card: str) -> Any:
    return agent.post(f"{TASKS}/{card}/claim", {})


def _requested(agent: flow.Agent, card: str) -> dict[str, Any]:
    filed = _claim(agent, card)
    assert filed.status_code == 202, filed.text
    request: dict[str, Any] = filed.json()["claim_request"]
    return request


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _row(engine: Engine, request_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.claim_request).where(t.claim_request.c.id == request_id)).one()


def _human(make_client: ClientFactory, engine: Engine, handle: str, trust: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, _project_id(engine), "coder", trust=trust, human_id=human.id)
    return human


def _notices(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.request)
                .where(t.request.c.claim_notice.is_not(None))
                .order_by(t.request.c.created_at, t.request.c.id)
            )
        )


# --- the claim request -------------------------------------------------------------------


def test_the_claim_files_one_request_and_takes_nothing(
    agent: flow.Agent, owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    before = len(_events(migrated, "task_updated"))
    filed = _claim(agent, card)
    assert filed.status_code == 202, filed.text
    body = filed.json()
    request = body["claim_request"]
    assert set(request) == {"id", "member_id", "instance", "requested_at"}
    assert request["id"].startswith("clr-")
    assert (request["member_id"], request["instance"]) == (agent.id, agent.instance)
    assert (body["status"], body["claim"]) == ("open", None)
    assert body["claim_requests"] == [request]
    shown = owner.get(f"{TASKS}/{card}").json()
    assert (shown["status"], shown["claim"], shown["claim_requests"]) == ("open", None, [request])
    [event] = _events(migrated, "claim_requested")
    assert event.payload == {"task_id": card, "claim_request": request}
    assert f"member:{owner.id}" in event.audience
    assert f"instance:{agent.id}#{agent.instance}" in event.audience
    assert "all" not in event.audience
    assert len(_events(migrated, "task_updated")) == before  # the filing emits none


def test_the_same_agent_gets_its_request_again_and_another_agent_waits(
    agent: flow.Agent,
    owner: flow.Human,
    outsider: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    again = _claim(agent, card)
    assert again.status_code == 202, again.text
    assert again.json()["claim_request"] == request
    assert len(_events(migrated, "claim_requested")) == 1  # nothing new filed or emitted
    sibling = _outside_agent(make_client, owner, outsider)  # an agent of the same owner
    waits = _claim(sibling, card)
    assert waits.status_code == 409, waits.text
    assert waits.json()["error"]["code"] == "already_claimed"
    assert waits.json()["error"]["details"] == {"pending": True}


def test_a_card_not_open_to_outsiders_is_refused_under_each_setting(
    agent: flow.Agent, owner: flow.Human
) -> None:
    closed = _card(owner, "Closed", open_to_outsiders=False)
    refused = _claim(agent, closed)
    assert (refused.status_code, _reason(refused)) == (403, "not_open_to_outsiders")
    _policy(owner, looking_for_coders="all")
    assert _claim(agent, closed).status_code == 202  # every open card under `all`
    other = _card(owner, "Open")
    _policy(owner, looking_for_coders="off")
    off = _claim(agent, other)
    assert (off.status_code, _reason(off)) == (403, "not_open_to_outsiders")


def test_a_project_no_longer_public_opens_no_card(agent: flow.Agent, owner: flow.Human) -> None:
    card = _card(owner)
    assert owner.patch(P, {"public_page": "off"}).status_code == 200
    refused = _claim(agent, card)
    assert (refused.status_code, _reason(refused)) == (403, "not_open_to_outsiders")


def test_outside_claims_max_counts_held_and_pending(agent: flow.Agent, owner: flow.Human) -> None:
    first, second = _card(owner, "One"), _card(owner, "Two")
    _policy(owner, outside_claims_max=1)
    _requested(agent, first)
    assert _claim(agent, first).status_code == 202  # its own request is not counted again
    refused = _claim(agent, second)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"reason": "outside_claims_max", "max": 1}
    _policy(owner, outside_claims_max=2)
    assert _claim(agent, second).status_code == 202


def test_direct_takes_the_card_at_once(agent: flow.Agent, owner: flow.Human) -> None:
    card = _card(owner)
    _policy(owner, outside_claims="direct")
    taken = _claim(agent, card)
    assert taken.status_code == 200, taken.text
    assert taken.json()["claim"]["holder"] == agent.id
    assert taken.json()["claim_requests"] == []


# --- confirmation and decline ---------------------------------------------------------------


def test_a_confirmation_hands_the_card_to_the_requesting_instance(
    agent: flow.Agent, owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    confirmed = owner.post(f"{TASKS}/{card}/claim/confirm", {"request_id": request["id"]})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "in_progress"
    assert (body["claim"]["holder"], body["claim"]["instance"]) == (agent.id, agent.instance)
    assert body["claim_requests"] == []
    claimed = _events(migrated, "task_claimed")[-1]
    assert claimed.payload["confirmed_by"] == {"member_id": owner.id, "instance": None}
    assert claimed.payload["holder"] == agent.id
    updated = _events(migrated, "task_updated")[-1]
    assert updated.payload["fields"] == ["claim_requests", "status"]
    assert f"member:{owner.id}" in updated.audience
    assert _row(migrated, request["id"]).status == "confirmed"
    second = owner.post(f"{TASKS}/{card}/claim/confirm", {"request_id": request["id"]})
    assert second.status_code == 404, second.text


def test_only_a_confirmer_confirms_and_learns_nothing_of_the_ids(
    agent: flow.Agent, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    member = _human(make_client, migrated, "plain", "member")
    for body in ({"request_id": request["id"]}, {"request_id": "clr-unknown"}):
        refused = member.post(f"{TASKS}/{card}/claim/confirm", body)
        assert (refused.status_code, _reason(refused)) == (403, "not_a_confirmer"), body
    admin = _human(make_client, migrated, "admin", "admin")
    unknown = admin.post(f"{TASKS}/{card}/claim/confirm", {"request_id": "clr-unknown"})
    assert unknown.status_code == 404, unknown.text
    assert (
        admin.post(f"{TASKS}/{card}/claim/confirm", {"request_id": request["id"]}).status_code
        == 200
    )


def test_an_agent_confirms_only_under_agent(
    agent: flow.Agent, owner: flow.Human, make_client: ClientFactory
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    admin_agent = flow.agent(make_client, owner, trust="admin", role="coder")
    path = f"{TASKS}/{card}/claim/confirm"
    refused = admin_agent.post(path, {"request_id": request["id"]})
    assert (refused.status_code, _reason(refused)) == (403, "not_a_confirmer")
    _policy(owner, outside_claims="agent")
    done = admin_agent.post(path, {"request_id": request["id"]})
    assert done.status_code == 200, done.text


def test_the_owner_of_the_agent_confirms_nothing_even_as_an_admin(
    agent: flow.Agent, owner: flow.Human, outsider: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    factory.membership(
        migrated, _project_id(migrated), "coder", trust="admin", human_id=outsider.id
    )
    for verb in ("confirm", "decline"):
        refused = outsider.post(f"{TASKS}/{card}/claim/{verb}", {"request_id": request["id"]})
        assert (refused.status_code, _reason(refused)) == (403, "not_a_confirmer"), verb
    assert (
        owner.post(f"{TASKS}/{card}/claim/decline", {"request_id": request["id"]}).status_code
        == 200
    )


def test_a_decline_keeps_the_card_open_and_tells_the_instance_and_the_owner(
    agent: flow.Agent, owner: flow.Human, outsider: flow.Human, migrated: Engine
) -> None:
    card = _card(owner, "Hub work")
    request = _requested(agent, card)
    path = f"{TASKS}/{card}/claim/decline"
    for wrong in ("rude", 3, "expired", "taken"):
        bad = owner.post(path, {"request_id": request["id"], "reason": wrong})
        assert bad.status_code == 400, bad.text
        assert bad.json()["error"]["details"]["fields"] == {"reason": "unknown"}, wrong
    extra = owner.post(path, {"request_id": request["id"], "note": "x"})
    assert extra.status_code == 400, extra.text
    declined = owner.post(path, {"request_id": request["id"], "reason": "not_a_fit"})
    assert declined.status_code == 200, declined.text
    assert (declined.json()["status"], declined.json()["claim_requests"]) == ("open", [])
    [told] = _events(migrated, "claim_declined")
    assert told.audience == [f"instance:{agent.id}#{agent.instance}"]
    assert told.payload == {
        "task_id": card,
        "request_id": request["id"],
        "reason": "not_a_fit",
        "decided_by": {"member_id": owner.id, "instance": None},
    }
    updated = _events(migrated, "task_updated")[-1]
    assert updated.payload["fields"] == ["claim_requests"]
    [notice] = _notices(migrated)
    assert notice.to_human == outsider.id
    assert notice.title == "Claim request declined: Hub work"
    assert notice.claim_notice == {
        "claim_request_id": request["id"],
        "reason": "not_a_fit",
        "decided_by": "maintainer",
    }
    assert notice.summary is None


def test_confirm_takes_no_reason(agent: flow.Agent, owner: flow.Human) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    refused = owner.post(
        f"{TASKS}/{card}/claim/confirm", {"request_id": request["id"], "reason": "declined"}
    )
    assert refused.status_code == 400, refused.text


# --- the re-check ---------------------------------------------------------------------------


def test_a_failed_recheck_declines_although_the_call_answers_409(
    agent: flow.Agent, owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    assert owner.patch(f"{TASKS}/{card}", {"open_to_outsiders": False}).status_code == 200
    refused = owner.post(f"{TASKS}/{card}/claim/confirm", {"request_id": request["id"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "conflict"
    assert _reason(refused) == "not_open_to_outsiders"
    row = _row(migrated, request["id"])
    assert (row.status, row.reason, row.pending) == ("declined", "not_open_to_outsiders", None)
    assert owner.get(f"{TASKS}/{card}").json()["claim_requests"] == []
    assert _events(migrated, "claim_declined")[-1].payload["reason"] == "not_open_to_outsiders"


def test_the_recheck_counts_the_cap(agent: flow.Agent, owner: flow.Human, migrated: Engine) -> None:
    first, second = _card(owner, "One"), _card(owner, "Two")
    one, two = _requested(agent, first), _requested(agent, second)
    _policy(owner, outside_claims_max=1)
    refused = owner.post(f"{TASKS}/{first}/claim/confirm", {"request_id": one["id"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"] == {"reason": "outside_claims_max", "max": 1}
    # One request less: the other one fits now.
    done = owner.post(f"{TASKS}/{second}/claim/confirm", {"request_id": two["id"]})
    assert done.status_code == 200, done.text


# --- settled by another call ----------------------------------------------------------------


def test_a_members_claim_and_an_assign_elsewhere_decline_it_as_taken(
    agent: flow.Agent, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    member = flow.agent(make_client, owner)
    card = _card(owner)
    request = _requested(agent, card)
    assert member.post(f"{TASKS}/{card}/claim", {}).status_code == 200
    assert _row(migrated, request["id"]).reason == "taken"
    updated = _events(migrated, "task_updated")[-1]
    assert updated.payload["fields"] == ["claim_requests", "status"]
    other = _card(owner, "Other")
    second = _requested(agent, other)
    assert owner.post(f"{TASKS}/{other}/assign", {"assignee": member.id}).status_code == 200
    row = _row(migrated, second["id"])
    assert (row.reason, row.decided_by is not None) == ("taken", True)


def test_an_assign_or_a_holder_claim_naming_the_requester_is_the_confirmation(
    agent: flow.Agent, owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    wrong = owner.post(f"{TASKS}/{card}/assign", {"assignee": agent.id, "instance": "zzzz"})
    assert wrong.status_code == 400, wrong.text
    assigned = owner.post(f"{TASKS}/{card}/assign", {"assignee": agent.id})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["claim"]["instance"] == agent.instance
    assert _row(migrated, request["id"]).status == "confirmed"
    other = _card(owner, "Other")
    second = _requested(agent, other)
    held = owner.post(f"{TASKS}/{other}/claim", {"holder": agent.id})
    assert held.status_code == 200, held.text
    assert _row(migrated, second["id"]).status == "confirmed"
    assert _events(migrated, "task_claimed")[-1].payload["confirmed_by"]["member_id"] == owner.id


def test_an_agents_assign_to_the_requester_is_humans_only(
    agent: flow.Agent, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    admin_agent = flow.agent(make_client, owner, trust="admin", role="coder")
    refused = admin_agent.post(f"{TASKS}/{card}/assign", {"assignee": agent.id})
    assert (refused.status_code, _reason(refused)) == (403, "humans_only")
    assert _row(migrated, request["id"]).pending is True


# --- the owner's placement (the lead's ruling: one test per path) -----------------------------


@pytest.fixture
def owner_admin(agent: flow.Agent, outsider: flow.Human, migrated: Engine) -> flow.Human:
    """The outsider joined the project later, with tasks:admin and trust admin; its agent keeps
    trust `outside`."""
    factory.membership(
        migrated, _project_id(migrated), "coder", trust="admin", human_id=outsider.id
    )
    return outsider


def test_the_owner_assigns_its_agent_nothing(
    agent: flow.Agent, owner: flow.Human, owner_admin: flow.Human
) -> None:
    card = _card(owner)
    refused = owner_admin.post(f"{TASKS}/{card}/assign", {"assignee": agent.id})
    assert (refused.status_code, _reason(refused)) == (403, "not_a_confirmer")
    assert owner.get(f"{TASKS}/{card}").json()["assigned_to"] is None
    _requested(agent, card)  # with a request waiting, the same
    again = owner_admin.post(f"{TASKS}/{card}/assign", {"assignee": agent.id})
    assert (again.status_code, _reason(again)) == (403, "not_a_confirmer")
    # The counter-check: another human admin places it.
    assert owner.post(f"{TASKS}/{card}/assign", {"assignee": agent.id}).status_code == 200


def test_the_owner_claims_nothing_for_its_agent(
    agent: flow.Agent, owner: flow.Human, owner_admin: flow.Human
) -> None:
    card = _card(owner)
    refused = owner_admin.post(f"{TASKS}/{card}/claim", {"holder": agent.id})
    assert (refused.status_code, _reason(refused)) == (403, "not_a_confirmer")
    assert owner.get(f"{TASKS}/{card}").json()["claim"] is None
    assert owner.post(f"{TASKS}/{card}/claim", {"holder": agent.id}).status_code == 200


def test_the_owners_patch_naming_its_agent_changes_nothing(
    agent: flow.Agent, owner: flow.Human, owner_admin: flow.Human
) -> None:
    card = _card(owner, "Before")
    refused = owner_admin.patch(f"{TASKS}/{card}", {"assigned_to": agent.id, "title": "After"})
    assert (refused.status_code, _reason(refused)) == (403, "not_a_confirmer")
    shown = owner.get(f"{TASKS}/{card}").json()
    assert (shown["assigned_to"], shown["title"]) == (None, "Before")
    done = owner.patch(f"{TASKS}/{card}", {"assigned_to": agent.id})
    assert done.status_code == 200, done.text


# --- the hub's declines and the lapse -----------------------------------------------------------


def test_turning_the_page_off_declines_at_once(
    agent: flow.Agent, owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    assert owner.patch(P, {"public_page": "off"}).status_code == 200
    row = _row(migrated, request["id"])
    assert (row.status, row.reason, row.decided_by) == ("declined", "not_public", None)
    assert _events(migrated, "claim_declined")[-1].payload["decided_by"] is None


def test_isolation_declines_it(agent: flow.Agent, owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    _policy(owner, agent_owners="members")  # an outsider's agent is isolated under members
    assert _row(migrated, request["id"]).reason == "isolated"


def test_the_lapse_files_one_decision_and_its_answer_confirms(
    agent: flow.Agent, owner: flow.Human, outsider: flow.Human, migrated: Engine
) -> None:
    card = _card(owner, "Hub work")
    request = _requested(agent, card)
    claim_requests.sweep(migrated)
    assert _row(migrated, request["id"]).lapse_request_id is None  # not due yet
    with migrated.begin() as conn:
        conn.execute(
            update(t.claim_request)
            .where(t.claim_request.c.id == request["id"])
            .values(lapses_at=clock.now() - timedelta(minutes=1))
        )
    claim_requests.sweep(migrated)
    claim_requests.sweep(migrated)  # once per claim request
    row = _row(migrated, request["id"])
    assert row.pending is True and row.lapse_request_id is not None
    with migrated.connect() as conn:
        decisions = conn.execute(
            select(t.request).where(
                t.request.c.claim_request_id == request["id"], t.request.c.personal.is_(False)
            )
        ).all()
    [decision] = decisions
    assert (decision.to_role, decision.humans_only, decision.filed_by) == (
        "trust:admin",
        True,
        "hub",
    )
    [expired] = _notices(migrated)
    assert expired.claim_notice["reason"] == "expired"
    assert expired.title == "Claim request waiting for the project's admins: Hub work"
    shown = owner.get(f"{P}/requests/{decision.id}").json()
    assert shown["claim_request_id"] == request["id"]
    assert [r["id"] for r in shown["replies"]] == ["confirm", "decline"]
    answered = owner.post(f"{P}/requests/{decision.id}/answer", {"reply_id": "confirm"})
    assert answered.status_code == 200, answered.text
    assert owner.get(f"{TASKS}/{card}").json()["claim"]["holder"] == agent.id
    assert _row(migrated, request["id"]).status == "confirmed"


def test_a_decline_withdraws_the_lapse_decision(
    agent: flow.Agent, owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    request = _requested(agent, card)
    with migrated.begin() as conn:
        conn.execute(
            update(t.claim_request)
            .where(t.claim_request.c.id == request["id"])
            .values(lapses_at=clock.now() - timedelta(minutes=1))
        )
    claim_requests.sweep(migrated)
    lapse = _row(migrated, request["id"]).lapse_request_id
    assert (
        owner.post(f"{TASKS}/{card}/claim/decline", {"request_id": request["id"]}).status_code
        == 200
    )
    with migrated.connect() as conn:
        status, reason = conn.execute(
            select(t.request.c.status, t.request.c.withdraw_reason).where(t.request.c.id == lapse)
        ).one()
    assert (status, reason) == ("withdrawn", "claim_request_declined")
    assert [n.claim_notice["reason"] for n in _notices(migrated)] == ["expired", "declined"]


def test_the_human_confirmers_get_one_inbox_item(
    agent: flow.Agent, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card = _card(owner, "Hub work")
    member = _human(make_client, migrated, "plain", "member")
    _requested(agent, card)
    items = owner.get("/me/notifications").json()["items"]
    [item] = [i for i in items if (i.get("target") or {}).get("type") == "task"]
    assert item["kind"] == "inbox"
    assert item["target"] == {"type": "task", "id": card}
    assert item["title"].endswith("asks to work on: Hub work")
    assert item["url"].endswith(f"/tasks/{card}")
    # The counter-check: a member who confirms nothing gets none.
    theirs = member.get("/me/notifications").json()["items"]
    assert not [i for i in theirs if (i.get("target") or {}).get("type") == "task"]


def test_the_outsiders_read_lists_holds_and_requests(
    agent: flow.Agent, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    held, waiting = _card(owner, "Held"), _card(owner, "Waiting")
    assert owner.post(f"{TASKS}/{held}/claim", {"holder": agent.id}).status_code == 200
    request = _requested(agent, waiting)
    shown = owner.get(f"{P}/outsiders")
    assert shown.status_code == 200, shown.text
    [item] = shown.json()["items"]
    assert shown.json()["next_cursor"] is None
    assert item["person"]["handle"] == "stranger"
    assert [a["id"] for a in item["agents"]] == [agent.id]
    assert item["agents"][0]["trust"] == "outside"
    assert (item["agents_max"], item["blocked"]) == (None, None)
    assert sorted(item["claims"], key=lambda c: c["pending"]) == [
        {"task_id": held, "member_id": agent.id, "pending": False, "request_id": None},
        {"task_id": waiting, "member_id": agent.id, "pending": True, "request_id": request["id"]},
    ]
    member = _human(make_client, migrated, "plain", "member")
    refused = member.get(f"{P}/outsiders")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["scope"] == "members:admin"
    stranger = flow.human(make_client, migrated, "nobody")
    assert stranger.get(f"{P}/outsiders").status_code == 404


def test_contribution_counts_the_open_cards(
    agent: flow.Agent, owner: flow.Human, outsider: flow.Human
) -> None:
    _card(owner, "Open")
    _card(owner, "Closed", open_to_outsiders=False)
    assert outsider.get(f"{P}/contribution").json()["open_cards"] == 1
    _policy(owner, looking_for_coders="all")
    assert outsider.get(f"{P}/contribution").json()["open_cards"] == 2
    _policy(owner, looking_for_coders="off")
    assert outsider.get(f"{P}/contribution").json()["open_cards"] == 0
