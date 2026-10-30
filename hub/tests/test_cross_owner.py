"""docs/api.md §6.2, "Across owners": a `reports_to` across owners takes effect only after both
owners' go (tsk-3jdqtppzmtdb)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _row(engine: Engine, principal: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal),
                t.membership.c.active.is_(True),
            )
        ).one()


def _boss_of(engine: Engine, principal: str) -> str | None:
    boss = _row(engine, principal).reports_to
    if boss is None:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.id == boss)).one()
    return str(row.agent_id or row.human_id)


def _handle(engine: Engine, agent_id: str) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == agent_id)
        ).scalar_one()
    return found


def _lent(engine: Engine, friend: flow.Human) -> str:
    """An agent of `friend`, who is no member of the project, in the project."""
    return factory.agent(engine, _project(engine), friend.id).agent_id


def _requests(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.request)
                .where(t.request.c.proposal.is_not(None))
                .order_by(t.request.c.created_at, t.request.c.id)
            )
        )


def _status(engine: Engine, request_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.request).where(t.request.c.id == request_id)).one()


def put(who: Any, member_id: str, **body: Any) -> Any:
    return who.patch(f"{PROJECT}/members/{member_id}", body)


def answer(who: Any, request_id: str, reply: str) -> Any:
    return who.post(f"/requests/{request_id}/answer", {"reply_id": reply})


def test_a_boss_from_another_owner_waits_for_the_subordinates_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    asked = put(owner, lent, reports_to=owner.id)
    assert asked.status_code == 202, asked.text
    body = asked.json()
    assert body["class"] == "consent" and body["to"] == f"human:{friend.id}"
    handle = _handle(migrated, lent)
    assert body["title"] == f"Let {handle} report to maintainer of maintainer"
    assert "friend" in body["summary"] and "can end the edge at any time" in body["summary"]
    assert _boss_of(migrated, lent) is None  # nothing changes until the go (§6.2 "Pending")
    [pending] = _requests(migrated)
    assert pending.personal is True and pending.to_human == friend.id
    inbox = friend.get("/requests").json()["items"]
    assert [r["id"] for r in inbox] == [pending.id]
    done = answer(friend, pending.id, "go")
    assert done.status_code == 200, done.text
    assert _boss_of(migrated, lent) == owner.id  # set at the go that leaves none open
    view = owner.get(f"{PROJECT}/members/{lent}").json()
    assert view["cross_owner"] is True and view["reports_to"] == owner.id


def test_a_no_changes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    request_id = put(owner, lent, reports_to=owner.id).json()["id"]
    assert answer(friend, request_id, "no").status_code == 200
    assert _boss_of(migrated, lent) is None
    assert _status(migrated, request_id).status == "answered"


def _two_sides(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> tuple[flow.Human, flow.Human, str, str]:
    """A subordinate of `friend` and a boss of `other`, both owners outside the project: a
    `PATCH` by the project owner, who is neither, asks both."""
    friend = flow.human(make_client, migrated, "friend")
    other = flow.human(make_client, migrated, "other")
    lent = _lent(migrated, friend)
    boss = factory.agent(migrated, _project(migrated), other.id).agent_id
    return friend, other, lent, boss


def test_a_caller_who_is_neither_owner_asks_both_and_the_edge_waits_for_the_last_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, other, lent, boss = _two_sides(owner, make_client, migrated)
    asked = put(owner, lent, reports_to=boss)
    assert asked.status_code == 202, asked.text
    first, second = _requests(migrated)
    assert asked.json()["id"] == first.id  # the boss side's request is the answer (§6.2)
    assert (first.to_human, second.to_human) == (other.id, friend.id)
    assert first.title.startswith("Take ") and second.title.startswith("Let ")
    assert second.id in first.summary and first.id in second.summary
    assert (first.proposal["requests"], second.proposal["requests"]) == ([first.id, second.id],) * 2
    assert answer(other, first.id, "go").status_code == 200
    assert _boss_of(migrated, lent) is None  # the subordinate's owner has not answered
    assert answer(friend, second.id, "go").status_code == 200
    assert _boss_of(migrated, lent) == boss
    with migrated.connect() as conn:
        updated = [
            e
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload["id"] == lent and e.payload["reports_to"] == boss
        ]
    assert len(updated) == 1 and updated[0].payload["cross_owner"] is True


def test_a_no_on_either_request_withdraws_the_other(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, other, lent, boss = _two_sides(owner, make_client, migrated)
    put(owner, lent, reports_to=boss)
    first, second = _requests(migrated)
    assert answer(friend, second.id, "no").status_code == 200
    assert _status(migrated, first.id).status == "withdrawn"
    assert _status(migrated, first.id).withdraw_reason == "refused"
    assert _boss_of(migrated, lent) is None


def test_a_withdrawal_of_either_request_withdraws_the_other(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, other, lent, boss = _two_sides(owner, make_client, migrated)
    put(owner, lent, reports_to=boss)
    first, second = _requests(migrated)
    done = friend.post(f"/requests/{second.id}/withdraw", {"reason": "changed my mind"})
    assert done.status_code == 200, done.text
    assert _status(migrated, first.id).status == "withdrawn"
    assert _boss_of(migrated, lent) is None


def test_a_further_patch_of_reports_to_supersedes_the_open_requests(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, other, lent, boss = _two_sides(owner, make_client, migrated)
    put(owner, lent, reports_to=boss)
    assert put(owner, lent, reports_to=None).status_code == 200  # a human who may PATCH
    for request in _requests(migrated):
        assert request.status == "withdrawn" and request.withdraw_reason == "superseded"
    assert _boss_of(migrated, lent) is None


def test_removing_either_member_withdraws_the_requests(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend, other, lent, boss = _two_sides(owner, make_client, migrated)
    put(owner, lent, reports_to=boss)
    assert owner.delete(f"{PROJECT}/members/{boss}").status_code == 200
    for request in _requests(migrated):
        assert request.status == "withdrawn" and request.withdraw_reason == "member_removed"


def test_the_other_fields_of_the_patch_apply_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    asked = put(owner, lent, reports_to=owner.id, role="reviewer", areas=["web/"])
    assert asked.status_code == 202, asked.text
    row = _row(migrated, lent)
    assert (row.role, row.areas, row.reports_to) == ("reviewer", ["web/"], None)


def test_an_edge_within_one_owner_is_set_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    mine = flow.agent(make_client, owner)
    boss = flow.agent(make_client, owner)
    assert put(owner, mine.id, reports_to=boss.id).status_code == 200
    assert put(owner, mine.id, reports_to=owner.id).status_code == 200  # its own human
    assert _requests(migrated) == []


def test_a_cycle_made_in_the_meantime_refuses_the_go_and_the_request_stays_open(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    request_id = put(owner, lent, reports_to=owner.id).json()["id"]
    lent_id, owner_id = _row(migrated, lent).id, _row(migrated, owner.id).id
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == owner_id).values(reports_to=lent_id)
        )
    refused = answer(friend, request_id, "go")
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"reports_to": "cycle"}
    assert _status(migrated, request_id).status == "open"
    assert _boss_of(migrated, lent) is None
    assert answer(friend, request_id, "no").status_code == 200  # still open for a no


def test_a_boss_who_is_a_manager_gets_the_reach_at_the_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    request_id = put(owner, lent, reports_to=boss.id).json()["id"]
    assert "manager" in _status(migrated, request_id).summary
    assert answer(friend, request_id, "go").status_code == 200
    assert _row(migrated, lent).line_consent is True


def test_a_boss_who_lost_the_role_before_the_go_gets_no_reach(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    request_id = put(owner, lent, reports_to=boss.id).json()["id"]
    assert put(owner, boss.id, role="coder").status_code == 200
    assert answer(friend, request_id, "go").status_code == 200
    assert _boss_of(migrated, lent) == boss.id and _row(migrated, lent).line_consent is False


def test_an_agent_that_did_not_ask_does_not_end_the_decision(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    request_id = put(owner, lent, reports_to=owner.id).json()["id"]
    bystander = flow.agent(make_client, owner, role="reviewer", reports_to=owner.id)
    refused = bystander.post(f"{PROJECT}/requests/{request_id}/withdraw", {})
    assert refused.status_code == 403 and refused.json()["error"]["details"] == {
        "reason": "pending_consent"
    }
    assert _status(migrated, request_id).status == "open"
    # A human who holds members:admin may, as the asker does.
    assert owner.post(f"{PROJECT}/requests/{request_id}/withdraw", {}).status_code == 200


def test_nobody_but_the_addressee_answers_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    request_id = put(owner, lent, reports_to=owner.id).json()["id"]
    assert answer(owner, request_id, "go").status_code in (403, 404)  # the asker
    stranger = flow.human(make_client, migrated, "stranger")
    assert answer(stranger, request_id, "go").status_code in (403, 404)
    assert _boss_of(migrated, lent) is None


# --- a join (§3.1) -----------------------------------------------------------------------------


def test_a_join_with_a_cross_owner_boss_starts_without_it_and_asks_the_boss_side(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    boss = _lent(migrated, friend)
    agent = flow.agent(make_client, owner, reports_to=boss)
    assert _boss_of(migrated, agent.id) is None  # the membership starts with reports_to null
    assert agent.resume().json()["membership"]["reports_to"] is None
    [pending] = _requests(migrated)
    handle = _handle(migrated, agent.id)
    assert pending.to_human == friend.id and pending.asked_by == _row(migrated, owner.id).id
    assert pending.title == f"Take {handle} of maintainer as a report of {_handle(migrated, boss)}"
    assert answer(friend, pending.id, "go").status_code == 200
    assert _boss_of(migrated, agent.id) == boss  # `go` sets the edge
    assert agent.resume().json()["membership"]["reports_to"] == boss


def test_a_no_leaves_the_joined_agent_without_a_boss(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    boss = _lent(migrated, friend)
    agent = flow.agent(make_client, owner, reports_to=boss)
    [pending] = _requests(migrated)
    assert answer(friend, pending.id, "no").status_code == 200
    assert _boss_of(migrated, agent.id) is None


def test_a_join_to_a_boss_of_its_own_owner_sets_it_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    boss = flow.agent(make_client, owner)
    agent = flow.agent(make_client, owner, reports_to=boss.id)
    assert _boss_of(migrated, agent.id) == boss.id
    agent2 = flow.agent(make_client, owner, reports_to=owner.id)
    assert _boss_of(migrated, agent2.id) == owner.id
    assert _requests(migrated) == []


def test_the_join_page_shows_the_boss_with_the_wait(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    boss = _lent(migrated, friend)
    created = flow.join(owner, "maity", reports_to=boss)
    token = created["join_url"].rsplit("/", 1)[1]
    page = make_client().get(f"/api/v1/join/{token}", headers={"Accept": "text/markdown"}).text
    assert f"`{_handle(migrated, boss)}` (waiting for a human's consent)" in page
    own = flow.join(owner, "maity", reports_to=owner.id)
    page = (
        make_client()
        .get(
            f"/api/v1/join/{own['join_url'].rsplit('/', 1)[1]}", headers={"Accept": "text/markdown"}
        )
        .text
    )
    assert "waiting for a human's consent" not in page


# --- the owner of the subordinate starts it (§2.3, §6.2 "Own consent") --------------------------


def test_the_owner_outside_the_project_asks_the_boss_side_and_reads_and_withdraws_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner)
    asked = put(friend, lent, reports_to=boss.id)
    assert asked.status_code == 202, asked.text
    [pending] = _requests(migrated)
    assert pending.to_human == owner.id and pending.asked_by is None
    assert pending.asked_by_human == friend.id  # a human who is no member of the project
    assert _boss_of(migrated, lent) is None
    # The asker reads and withdraws it by its id; the project's routes stay closed to them.
    seen = friend.get(f"/requests/{pending.id}")
    assert seen.status_code == 200 and seen.json()["id"] == pending.id
    assert friend.get(f"{PROJECT}/requests/{pending.id}").status_code == 404
    assert answer(friend, pending.id, "go").status_code == 404  # only the addressee answers
    assert friend.post(f"/requests/{pending.id}/withdraw", {"reason": "no"}).status_code == 200
    assert _status(migrated, pending.id).status == "withdrawn"
    assert _boss_of(migrated, lent) is None


def test_the_boss_side_answers_the_owners_request_and_the_edge_is_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner)
    request_id = put(friend, lent, reports_to=boss.id).json()["id"]
    done = answer(owner, request_id, "go")
    assert done.status_code == 200, done.text
    assert _boss_of(migrated, lent) == boss.id


def test_an_owner_who_is_a_member_asks_as_a_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project(migrated), "member", human_id=friend.id)
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner)
    asked = put(friend, lent, reports_to=boss.id)
    assert asked.status_code == 202, asked.text
    [pending] = _requests(migrated)
    assert pending.asked_by == _row(migrated, friend.id).id and pending.asked_by_human is None


def test_the_owners_own_move_ends_the_open_request_and_a_foreign_boss_is_checked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner)
    put(friend, lent, reports_to=boss.id)
    assert put(friend, lent, reports_to=None).status_code == 204  # to nobody: at once
    [pending] = _requests(migrated)
    assert pending.status == "withdrawn" and pending.withdraw_reason == "superseded"
    guest = flow.human(make_client, migrated, "guest")
    factory.membership(migrated, _project(migrated), "guest", human_id=guest.id)
    refused = put(friend, lent, reports_to=guest.id)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"reports_to": "guest"}


def test_an_admin_agents_patch_waits_for_its_owner_and_then_asks_both_owners(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.3 ᵃ first, the cross-owner consents when it is applied (§6.2, "PATCH")."""
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    lent_id = _row(migrated, lent).id
    with migrated.begin() as conn:  # a reviewer: its change needs the owner's go (§2.3 ᵃ)
        conn.execute(
            update(t.membership).where(t.membership.c.id == lent_id).values(role="reviewer")
        )
    boss = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin", reports_to=owner.id)
    waiting = put(admin, lent, reports_to=boss.id, role="coder")
    assert waiting.status_code == 202, waiting.text
    first_request = waiting.json()["id"]
    assert _requests(migrated)[0].proposal["kind"] == "member_change"
    go = owner.post(f"{PROJECT}/requests/{first_request}/answer", {"reply_id": "go"})
    assert go.status_code == 200, go.text
    assert _row(migrated, lent).role == "coder"  # the other fields applied at once
    assert _boss_of(migrated, lent) is None  # the boss waits for both owners
    asked = [r for r in _requests(migrated) if r.proposal["kind"] == "cross_owner_reports_to"]
    assert sorted(r.to_human for r in asked) == sorted([owner.id, friend.id])
    for request in asked:
        who = owner if request.to_human == owner.id else friend
        assert answer(who, request.id, "go").status_code == 200
    assert _boss_of(migrated, lent) == boss.id


def test_an_admin_agent_asks_both_owners_and_only_its_own_request_may_be_ended_by_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin", reports_to=owner.id)
    other_admin = flow.agent(make_client, owner, role="admin", reports_to=owner.id)
    asked = put(admin, lent, reports_to=boss.id)
    assert asked.status_code == 202, asked.text
    assert len(_requests(migrated)) == 2  # neither owner is the caller: both are asked
    # An agent that did not ask does not end the owners' decision, whatever its scopes (§6.2).
    refused = put(other_admin, lent, reports_to=None)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "pending_consent"}
    assert all(r.status == "open" for r in _requests(migrated))
    assert put(admin, lent, reports_to=None).status_code == 200  # the asker may supersede
    assert all(r.status == "withdrawn" for r in _requests(migrated))
