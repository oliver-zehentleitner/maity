"""docs/api.md §6.2, "Another owner's agent": a change of an agent by a caller that is not its
owner waits for its owner's consent (tsk-8c6vdjpw82b1, part 2)."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, jcs
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


def _lent(engine: Engine, friend: flow.Human) -> str:
    """An agent of `friend`, who is no member of the project, in the project."""
    return factory.agent(engine, _project(engine), friend.id).agent_id


def _row(engine: Engine, principal: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                t.membership.c.agent_id == principal, t.membership.c.active.is_(True)
            )
        ).one()


def _requests(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.request)
                .where(t.request.c.proposal.is_not(None))
                .order_by(t.request.c.created_at, t.request.c.id)
            )
        )


def put(who: Any, member_id: str, **body: Any) -> Any:
    return who.patch(f"{PROJECT}/members/{member_id}", body)


def _raw(who: flow.Human, member_id: str, content: bytes) -> Any:
    return who.client.patch(
        f"/api/v1{PROJECT}/members/{member_id}",
        content=content,
        headers={"X-CSRF-Token": who.csrf, "Content-Type": "application/json"},
    )


def answer(who: Any, request_id: str, reply: str) -> Any:
    return who.post(f"/requests/{request_id}/answer", {"reply_id": reply})


def test_a_change_of_another_owners_agent_waits_for_its_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    before = _row(migrated, lent)
    asked = put(owner, lent, role="reviewer", areas=["web/"])
    assert asked.status_code == 202, asked.text
    body = asked.json()
    assert body["class"] == "consent" and body["to"] == f"human:{friend.id}"
    assert body["title"].startswith("Change ") and " in " in body["title"]
    assert "role:" in body["summary"] and "areas:" in body["summary"] and "→" in body["summary"]
    now = _row(migrated, lent)
    # nothing on the call, the role's base included: no scope or audience moves before the go
    assert (now.role, now.role_base, now.areas) == (before.role, before.role_base, before.areas)
    with migrated.connect() as conn:
        assert not [
            e
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload["id"] == lent
        ]  # no member_updated either
    [pending] = _requests(migrated)
    assert pending.personal is True and pending.to_human == friend.id
    assert [r["id"] for r in friend.get("/requests").json()["items"]] == [pending.id]
    done = answer(friend, pending.id, "go")
    assert done.status_code == 200, done.text
    changed = _row(migrated, lent)
    assert (changed.role, changed.role_base, changed.areas) == ("reviewer", "reviewer", ["web/"])
    with migrated.connect() as conn:
        updates = [
            e
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload["id"] == lent
        ]
    assert (
        len(updates) == 1 and updates[0].payload["role"] == "reviewer"
    )  # one for the whole change


def test_a_no_or_a_withdrawal_changes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    first = put(owner, lent, role="reviewer").json()["id"]
    assert answer(friend, first, "no").status_code == 200
    assert (_row(migrated, lent).role, _row(migrated, lent).role_base) == ("coder", "coder")
    second = put(owner, lent, role="reviewer").json()["id"]
    withdrawn = owner.post(f"{PROJECT}/requests/{second}/withdraw", {"reason": "changed my mind"})
    assert withdrawn.status_code == 200, withdrawn.text
    assert _row(migrated, lent).role != "reviewer"
    assert answer(friend, second, "go").status_code in (400, 404, 409)  # nothing left to answer


def test_a_further_patch_supersedes_the_open_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    first = put(owner, lent, role="reviewer").json()["id"]
    second = put(owner, lent, areas=["web/"]).json()["id"]
    rows = {r.id: r for r in _requests(migrated)}
    assert rows[first].status == "withdrawn" and rows[first].withdraw_reason == "superseded"
    assert rows[second].status == "open"
    assert answer(friend, second, "go").status_code == 200
    changed = _row(migrated, lent)
    assert changed.areas == ["web/"] and changed.role != "reviewer"  # only the newer fields


def test_only_the_owner_answers_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    request_id = put(owner, lent, role="reviewer").json()["id"]
    assert answer(owner, request_id, "go").status_code in (403, 404)  # the asker
    stranger = flow.human(make_client, migrated, "stranger")
    assert answer(stranger, request_id, "go").status_code in (403, 404)
    assert _row(migrated, lent).role != "reviewer"


def test_the_owners_own_agents_and_callers_for_humans_change_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    mine = flow.agent(make_client, owner)
    assert put(owner, mine.id, role="reviewer").status_code == 200  # an agent of its own
    peer = flow.human(make_client, migrated, "peer")
    factory.membership(migrated, _project(migrated), "coder", human_id=peer.id)
    assert put(owner, peer.id, role="reviewer").status_code == 200  # a human's membership


def test_an_admin_agent_of_another_owner_asks_the_owner_too(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    admin = flow.agent(make_client, owner, role="admin")
    asked = put(admin, lent, areas=["web/"])
    assert asked.status_code == 202, asked.text
    assert asked.json()["to"] == f"human:{friend.id}"
    assert _row(migrated, lent).areas != ["web/"]
    assert answer(friend, asked.json()["id"], "go").status_code == 200
    assert _row(migrated, lent).areas == ["web/"]


def test_removing_the_agent_withdraws_the_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    request_id = put(owner, lent, role="reviewer").json()["id"]
    assert owner.delete(f"{PROJECT}/members/{lent}").status_code == 200
    [row] = [r for r in _requests(migrated) if r.id == request_id]
    assert row.status == "withdrawn" and row.withdraw_reason == "member_removed"


def test_a_pause_of_another_owners_agent_waits_and_a_reports_to_follows_its_own_path(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    asked = put(owner, lent, paused={"reason": "quota"})
    assert asked.status_code == 202, asked.text
    assert _row(migrated, lent).paused_since is None
    assert answer(friend, asked.json()["id"], "go").status_code == 200
    assert _row(migrated, lent).paused_since is not None
    # `reports_to` and a field together: two requests, the field consent is the answer.
    both = put(owner, lent, role="reviewer", reports_to=owner.id)
    assert both.status_code == 202, both.text
    assert both.json()["title"].startswith("Change ")
    assert len(_requests(migrated)) == 3  # the pause, the field change, the edge's one request


def test_a_manager_changes_another_owners_agent_in_its_reach_at_once_and_only_then(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The exception for "a manager acting inside its reach" (§6.2): part (b) of the reach
    holds only while `line_consent` is true; a manager without `members:admin` then changes
    the agent at once, without the owner."""
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    manager = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    # Before any consent the agent is outside the manager's reach: nothing at all happens.
    outside = put(manager, lent, areas=["web/"])
    assert outside.status_code in (403, 404), outside.text
    assert _row(migrated, lent).areas != ["web/"]
    edge = put(owner, lent, reports_to=manager.id)
    assert edge.status_code == 202, edge.text
    assert answer(friend, edge.json()["id"], "go").status_code == 200
    assert _row(migrated, lent).line_consent is True
    inside = put(manager, lent, areas=["web/"])
    assert inside.status_code == 200, inside.text  # at once, no request to the owner
    assert _row(migrated, lent).areas == ["web/"]
    assert [r.proposal["kind"] for r in _requests(migrated) if r.status == "open"] == []


def test_a_go_is_refused_when_the_asker_may_not_ask_any_more(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from sqlalchemy import update

    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    deputy = flow.human(make_client, migrated, "deputy")
    factory.membership(migrated, _project(migrated), "admin", human_id=deputy.id)
    asked = put(deputy, lent, role="reviewer")
    assert asked.status_code == 202, asked.text
    with migrated.begin() as conn:  # the deputy lost the admin trust meanwhile
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == deputy.id).values(trust="member")
        )
    refused = answer(friend, asked.json()["id"], "go")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "asker_not_allowed"
    assert _row(migrated, lent).role == "coder"
    assert answer(friend, asked.json()["id"], "no").status_code == 200  # still open for a no


def test_the_request_of_an_asker_who_left_the_project_is_withdrawn_with_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The removal withdraws a member's open proposals (`proposals`): no `go` can apply what
    nobody asks for any more, so `_still_allowed` never meets a removed asker."""
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    deputy = flow.human(make_client, migrated, "deputy")
    factory.membership(migrated, _project(migrated), "admin", human_id=deputy.id)
    asked = put(deputy, lent, role="reviewer")
    assert owner.delete(f"{PROJECT}/members/{deputy.id}").status_code == 200
    [row] = [r for r in _requests(migrated) if r.id == asked.json()["id"]]
    assert row.status == "withdrawn"
    assert answer(friend, row.id, "go").status_code == 409
    assert _row(migrated, lent).role == "coder"


def _put_roles(owner: flow.Human, custom: Any) -> Any:
    return owner.client.put(
        f"/api/v1{PROJECT}/roles", json={"custom": custom}, headers={"X-CSRF-Token": owner.csrf}
    )


def test_a_go_checks_the_calls_own_rules_against_todays_state(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """An owner who asked for trust `admin` and was demoted meanwhile no longer grants it."""
    from sqlalchemy import update

    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    partner = flow.human(make_client, migrated, "partner")
    factory.membership(migrated, _project(migrated), "owner", human_id=partner.id)
    asked = put(partner, lent, trust="admin")
    assert asked.status_code == 202, asked.text
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == partner.id).values(trust="admin")
        )
    refused = answer(friend, asked.json()["id"], "go")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "asker_not_allowed"
    assert _row(migrated, lent).trust != "admin"


def test_a_go_is_refused_for_an_admin_agent_that_was_isolated_or_lost_its_trust(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from sqlalchemy import update

    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    admin = flow.agent(make_client, owner, role="admin")
    first = put(admin, lent, areas=["web/"]).json()["id"]
    isolated = owner.post(f"{PROJECT}/members/{admin.id}/isolate", {"reason": "loud"})
    assert isolated.status_code == 200, isolated.text
    refused = answer(friend, first, "go")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "asker_not_allowed"
    owner.delete(f"{PROJECT}/members/{admin.id}/isolate")
    second = put(admin, lent, areas=["api/"]).json()["id"]
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == admin.id).values(trust="member")
        )
    again = answer(friend, second, "go")
    assert again.status_code == 409 and again.json()["error"]["code"] == "asker_not_allowed"
    assert _row(migrated, lent).areas != ["api/"]


def test_a_project_role_is_read_again_at_the_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    legal = {"name": "legal", "base": "reviewer"}
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    assert _put_roles(owner, [legal]).status_code == 200
    asked = put(owner, lent, role="legal")
    assert asked.status_code == 202, asked.text
    # The base moves while the request waits: the agent gets the base the role has now.
    assert _put_roles(owner, [{**legal, "base": "coder"}]).status_code == 200
    assert answer(friend, asked.json()["id"], "go").status_code == 200
    row = _row(migrated, lent)
    assert (row.role, row.role_base) == ("legal", "coder")
    # And a role removed meanwhile refuses the go; the request stays open for a no. The agent
    # leaves the role first, so that the removal is allowed (an open request does not count).
    from sqlalchemy import update

    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == lent)
            .values(role="reviewer", role_base="reviewer")
        )
    asked_legal = put(owner, lent, role="legal")
    assert asked_legal.status_code == 202, asked_legal.text
    removed = _put_roles(owner, [])
    assert removed.status_code == 200, removed.text
    refused = answer(friend, asked_legal.json()["id"], "go")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "role_unknown"
    assert answer(friend, asked_legal.json()["id"], "no").status_code == 200


def test_a_go_asks_the_admin_agents_own_rules_of_the_target_as_it_is_now(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The same `admin_agents.check_change` as the call: a target raised to admin meanwhile is
    no member or guest any more, so an admin agent may not change it."""
    from sqlalchemy import update

    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    admin = flow.agent(make_client, owner, role="admin")
    asked = put(admin, lent, areas=["web/"])
    assert asked.status_code == 202, asked.text
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == lent).values(trust="admin")
        )
    direct = put(admin, lent, areas=["api/"])
    assert direct.status_code == 403, direct.text  # the call refuses it now
    refused = answer(friend, asked.json()["id"], "go")
    assert refused.status_code == 409, refused.text  # and so does the go
    assert refused.json()["error"]["code"] == "asker_not_allowed"
    assert _row(migrated, lent).areas != ["web/"]


def test_a_go_refuses_to_lift_the_pause_a_human_set_on_one_instance_meanwhile(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """An admin agent's lift of one instance's pause is asked again at the go, as the call
    asks it (§5.3, §6.17): a human's pause set in between is not the admin agent's to lift."""
    from sqlalchemy import update

    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    lent_row = _row(migrated, lent)
    with migrated.begin() as conn:
        credential = conn.execute(
            select(t.credential).where(t.credential.c.membership_id == lent_row.id)
        ).first()
    assert credential is not None, "the factory agent has an instance"
    admin = flow.agent(make_client, owner, role="admin")
    asked = put(admin, lent, paused=None, instance=credential.instance)
    assert asked.status_code == 202, asked.text
    with migrated.begin() as conn:  # the agent's owner pauses that instance meanwhile
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == credential.id)
            .values(paused_reason="owner's call", paused_since=clock.now(), paused_by=friend.id)
        )
    refused = answer(friend, asked.json()["id"], "go")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "asker_not_allowed"


def _read(who: Any, request_id: str) -> dict[str, Any]:
    body: dict[str, Any] = who.get(f"/requests/{request_id}").json()
    return body


def test_a_reports_to_inside_the_owner_waits_and_the_go_applies_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Null, or another agent of the same human: one owner-consent request, nothing on the call."""
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    sibling = factory.agent(migrated, _project(migrated), friend.id)
    asked = put(owner, lent, reports_to=sibling.agent_id)
    assert asked.status_code == 202, asked.text
    assert asked.json()["to"] == f"human:{friend.id}"
    assert _row(migrated, lent).reports_to is None
    label = f"{sibling.agent_id} ({sibling.agent_id}, owner {friend.handle})"
    assert label in asked.json()["summary"]
    view = _read(friend, asked.json()["id"])
    [field] = view["agent_change"]["fields"]
    assert field["name"] == "reports_to"
    assert field["current"] is None and field["proposed"] == sibling.agent_id
    assert field["canonical"] == jcs.canonicalize(sibling.agent_id)
    assert field["sha256"] == hashlib.sha256(field["canonical"].encode()).hexdigest()
    assert "agent_change" not in friend.get("/requests").json()["items"][0]
    assert answer(friend, asked.json()["id"], "go").status_code == 200
    assert _row(migrated, lent).reports_to == sibling.membership_id
    cleared = put(owner, lent, reports_to=None)
    assert cleared.status_code == 202, cleared.text
    assert _row(migrated, lent).reports_to == sibling.membership_id  # still, until the go
    assert answer(friend, cleared.json()["id"], "go").status_code == 200
    assert _row(migrated, lent).reports_to is None


def test_the_owners_own_agent_sets_reports_to_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    mine = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    moved = put(admin, mine.id, reports_to=owner.id)
    assert moved.status_code == 200, moved.text
    assert _requests(migrated) == []
    with migrated.connect() as conn:
        human = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.human_id == owner.id, t.membership.c.active.is_(True)
            )
        ).scalar_one()
    assert _row(migrated, mine.id).reports_to == human


def test_a_manager_of_another_owner_does_not_set_reports_to(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    manager = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    edge = put(owner, lent, reports_to=manager.id)
    assert edge.status_code == 202, edge.text
    assert answer(friend, edge.json()["id"], "go").status_code == 200
    boss = _row(migrated, lent).reports_to
    refused = put(manager, lent, reports_to=owner.id)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "not_in_line"
    assert _row(migrated, lent).reports_to == boss


def test_a_cross_owner_edge_files_no_second_request_and_the_pair_is_listed_beside(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    only = put(owner, lent, reports_to=owner.id)
    assert only.status_code == 202, only.text
    assert "cross_owner_reports_to" not in only.json()
    assert [r.proposal["kind"] for r in _requests(migrated)] == ["cross_owner_reports_to"]
    withdrawn = owner.post(f"{PROJECT}/requests/{only.json()['id']}/withdraw", {"reason": "done"})
    assert withdrawn.status_code == 200, withdrawn.text
    admin = flow.agent(make_client, owner, role="admin", reports_to=owner.id)
    boss = flow.agent(make_client, owner)
    both = put(admin, lent, role="reviewer", areas=["web/"], reports_to=boss.id)
    assert both.status_code == 202, both.text
    body = both.json()
    assert body["title"].startswith("Change ")
    assert _row(migrated, lent).role == "coder"  # the other fields wait too
    ids = body["cross_owner_reports_to"]
    rows = {r.id: r for r in _requests(migrated)}
    assert [rows[i].proposal["side"] for i in ids] == ["boss", "subordinate"]
    assert rows[body["id"]].proposal["kind"] == "foreign_agent_change"
    assert "reports_to" not in rows[body["id"]].proposal["values"]
    read = _read(friend, body["id"])
    assert "cross_owner_reports_to" not in read
    names = [field["name"] for field in read["agent_change"]["fields"]]
    assert names == ["role", "areas"]
    headers = {"X-CSRF-Token": owner.csrf, "Idempotency-Key": "foreign-pair-replay-0001"}
    path = f"/api/v1{PROJECT}/members/{lent}"
    payload = {"role": "coder", "reports_to": boss.id}
    first = owner.client.patch(path, json=payload, headers=headers)
    assert first.status_code == 202, first.text
    again = owner.client.patch(path, json=payload, headers=headers)
    assert again.headers.get("idempotent-replayed") == "true"
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["cross_owner_reports_to"] == first.json()["cross_owner_reports_to"]


def test_the_summary_quotes_values_in_full_until_the_cap_and_the_go_applies_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    sibling = factory.agent(migrated, _project(migrated), friend.id)
    briefing = "B" * 16384
    asked = put(owner, lent, briefing=briefing, reports_to=sibling.agent_id)
    assert asked.status_code == 202, asked.text
    summary = asked.json()["summary"]
    assert len(summary) <= 16384
    assert "B" * 100 not in summary
    assert "full value in agent_change" in summary
    assert f"owner {friend.handle}" in summary  # reports_to is never replaced
    view = _read(friend, asked.json()["id"])
    fields = {field["name"]: field for field in view["agent_change"]["fields"]}
    assert fields["briefing"]["proposed"] == briefing
    assert fields["briefing"]["canonical"] == jcs.canonicalize(briefing)
    assert (
        fields["briefing"]["sha256"]
        == hashlib.sha256(fields["briefing"]["canonical"].encode()).hexdigest()
    )
    assert answer(friend, asked.json()["id"], "go").status_code == 200
    assert _row(migrated, lent).briefing == briefing
    assert _row(migrated, lent).reports_to == sibling.membership_id


def test_a_bad_number_token_or_a_lone_surrogate_is_refused_before_a_request_is_filed(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    fraction = put(owner, lent, availability_policy={"grace_minutes": 1.0})
    assert fraction.status_code == 400, fraction.text
    assert fraction.json()["error"]["details"]["fields"] == {
        "availability_policy": "not_an_integer"
    }
    raw = owner.client.patch(
        f"/api/v1{PROJECT}/members/{lent}",
        content=b'{"availability_policy":{"grace_minutes":1e2}}',
        headers={"X-CSRF-Token": owner.csrf, "Content-Type": "application/json"},
    )
    assert raw.status_code == 400, raw.text
    assert raw.json()["error"]["details"]["fields"]["availability_policy"] == "not_an_integer"
    surrogate = owner.client.patch(
        f"/api/v1{PROJECT}/members/{lent}",
        content=b'{"briefing":"keep \\udead this"}',
        headers={"X-CSRF-Token": owner.csrf, "Content-Type": "application/json"},
    )
    assert surrogate.status_code == 400, surrogate.text
    assert surrogate.json()["error"]["details"]["fields"] == {"briefing": "lone_surrogate"}
    assert _requests(migrated) == []
    assert _row(migrated, lent).briefing is None


def test_a_fraction_an_exponent_or_an_integer_past_the_range_is_not_an_integer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The field's own code, before a model reports a nested `int_*` (§6.2)."""
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    for token in ("1.5", "1e20", "9007199254740992", "-2e1", "1e5"):
        raw = _raw(
            owner,
            lent,
            f'{{"availability_policy":{{"grace_minutes":{token}}}}}'.encode(),
        )
        assert raw.status_code == 400, (token, raw.text)
        assert raw.json()["error"]["details"]["fields"] == {
            "availability_policy": "not_an_integer"
        }, token
    assert _requests(migrated) == []
    mine = flow.agent(make_client, owner)
    own = _raw(owner, mine.id, b'{"availability_policy":{"grace_minutes":1.5}}')
    assert own.status_code == 400, own.text
    fields = own.json()["error"]["details"]["fields"]
    assert fields.get("availability_policy") != "not_an_integer"
    assert "availability_policy.grace_minutes" in fields


def test_a_foreign_dormant_number_token_is_not_an_integer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = factory.agent(migrated, _project(migrated), friend.id)
    for token in ("1.0", "1", "0"):
        raw = _raw(
            owner,
            lent.agent_id,
            f'{{"dormant":{token},"instance":"{lent.instance}"}}'.encode(),
        )
        assert raw.status_code == 400, (token, raw.text)
        assert raw.json()["error"]["details"]["fields"] == {"dormant": "not_an_integer"}, token
    assert _requests(migrated) == []
    with migrated.connect() as conn:
        since = conn.execute(
            select(t.credential.c.dormant_since).where(t.credential.c.id == lent.credential_id)
        ).scalar_one()
    assert since is None


def test_a_lone_surrogate_in_dormant_is_lone_surrogate(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = factory.agent(migrated, _project(migrated), friend.id)
    foreign = _raw(
        owner,
        lent.agent_id,
        f'{{"dormant":"\\udead","instance":"{lent.instance}"}}'.encode(),
    )
    assert foreign.status_code == 400, foreign.text
    assert foreign.json()["error"]["details"]["fields"] == {"dormant": "lone_surrogate"}
    mine = flow.agent(make_client, owner)
    own = _raw(
        owner,
        mine.id,
        f'{{"dormant":"\\udead","instance":"{mine.instance}"}}'.encode(),
    )
    assert own.status_code == 400, own.text
    assert own.json()["error"]["details"]["fields"] == {"dormant": "lone_surrogate"}
    assert _requests(migrated) == []


def test_a_replay_of_the_owners_answer_does_not_carry_the_cross_owner_pair(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner)
    filed = put(owner, lent, role="reviewer", reports_to=boss.id)
    assert filed.status_code == 202, filed.text
    assert "cross_owner_reports_to" in filed.json()
    headers = {"X-CSRF-Token": friend.csrf, "Idempotency-Key": "foreign-answer-replay-01"}
    path = f"/api/v1/requests/{filed.json()['id']}/answer"
    first = friend.client.post(path, json={"reply_id": "go"}, headers=headers)
    assert first.status_code == 200, first.text
    assert "cross_owner_reports_to" not in first.json()
    again = friend.client.post(path, json={"reply_id": "go"}, headers=headers)
    assert again.headers.get("idempotent-replayed") == "true"
    assert again.json()["id"] == first.json()["id"]
    assert "cross_owner_reports_to" not in again.json()


def _still_open(engine: Engine, request_id: str) -> Any:
    [row] = [r for r in _requests(engine) if r.id == request_id]
    assert row.status == "open"
    return row


def test_a_go_whose_stored_reports_to_is_no_longer_a_member_stays_open(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    sibling = factory.agent(migrated, _project(migrated), friend.id)
    asked = put(owner, lent, reports_to=sibling.agent_id)
    assert asked.status_code == 202, asked.text
    assert owner.delete(f"{PROJECT}/members/{sibling.agent_id}").status_code == 200
    _still_open(migrated, asked.json()["id"])
    refused = answer(friend, asked.json()["id"], "go")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "asker_not_allowed"
    assert _row(migrated, lent).reports_to is None
    _still_open(migrated, asked.json()["id"])
    assert answer(friend, asked.json()["id"], "no").status_code == 200


def test_a_go_whose_stored_reports_to_would_cycle_stays_open(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    sibling = factory.agent(migrated, _project(migrated), friend.id)
    asked = put(owner, lent, reports_to=sibling.agent_id)
    assert asked.status_code == 202, asked.text
    target_id = _row(migrated, lent).id
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == sibling.membership_id)
            .values(reports_to=target_id)
        )
    refused = answer(friend, asked.json()["id"], "go")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "asker_not_allowed"
    assert _row(migrated, lent).reports_to is None
    _still_open(migrated, asked.json()["id"])
    assert answer(friend, asked.json()["id"], "no").status_code == 200


def test_removing_a_member_clears_a_foreign_agents_reports_to_without_that_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    boss = flow.agent(make_client, owner)
    boss_id = _row(migrated, boss.id).id
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == lent).values(reports_to=boss_id)
        )
    assert owner.delete(f"{PROJECT}/members/{boss.id}").status_code == 200
    assert _row(migrated, lent).reports_to is None
    assert _requests(migrated) == []


def test_an_equal_length_hides_the_later_field_and_the_current_value_first() -> None:
    from maity_hub.foreign_agent import OMITTED, SUMMARY_CAP, _fit, _Piece

    def over(rows: list[tuple[str, Any, Any]]) -> str:
        """A preamble that leaves the summary one character past the cap."""

        def size(preamble: str) -> int:
            lines = [preamble]
            for label, current, proposed in rows:
                lines.append(f"- {label}: {current.text} → {proposed.text}")
            lines.append("c")
            return len("\n".join(lines))

        extra = size("p") - 1  # everything but the preamble
        return "p" * (SUMMARY_CAP + 1 - extra)

    same = "x" * 80
    within = [
        ("trust", _Piece(0, False, same), _Piece(0, True, same)),
        ("role", _Piece(1, False, "short"), _Piece(1, True, "short")),
    ]
    summary = _fit(over(within), within, "c")
    assert len(summary) <= SUMMARY_CAP
    assert f"trust: {OMITTED} → {same}" in summary  # current before proposed
    assert "role: short → short" in summary
    longer = "y" * 80
    tied = [
        ("trust", _Piece(0, False, longer), _Piece(0, True, "short")),
        ("role", _Piece(1, False, longer), _Piece(1, True, "short")),
    ]
    summary = _fit(over(tied), tied, "c")
    assert f"role: {OMITTED} → short" in summary  # equal length: the later field first
    assert f"trust: {longer} → short" in summary
