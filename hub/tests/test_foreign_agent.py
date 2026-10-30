"""docs/api.md §6.2, "Another owner's agent": a change of an agent by a caller that is not its
owner waits for its owner's consent (tsk-8c6vdjpw82b1, part 2)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

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
    assert (now.role, now.areas) == (before.role, before.areas)  # nothing on the call
    [pending] = _requests(migrated)
    assert pending.personal is True and pending.to_human == friend.id
    assert [r["id"] for r in friend.get("/requests").json()["items"]] == [pending.id]
    done = answer(friend, pending.id, "go")
    assert done.status_code == 200, done.text
    changed = _row(migrated, lent)
    assert (changed.role, changed.areas) == ("reviewer", ["web/"])
    with migrated.connect() as conn:
        updates = [
            e
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload["id"] == lent and e.payload["role"] == "reviewer"
        ]
    assert len(updates) == 1  # one member_updated for the whole change


def test_a_no_or_a_withdrawal_changes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent = _lent(migrated, friend)
    first = put(owner, lent, role="reviewer").json()["id"]
    assert answer(friend, first, "no").status_code == 200
    assert _row(migrated, lent).role != "reviewer"
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
