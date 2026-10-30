"""docs/api.md §2.3: a human may always set the `reports_to` of an agent they own to null or to
a member they own, whatever their trust and role and whether or not they are a member of the
project (tsk-fw3x5c13vq9g)."""

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


def move(who: Any, member_id: str, **body: Any) -> Any:
    return who.patch(f"{PROJECT}/members/{member_id}", body)


def fields(answer: Any) -> dict[str, str]:
    assert answer.status_code == 400, answer.text
    found: dict[str, str] = answer.json()["error"]["details"]["fields"]
    return found


def _agents(engine: Engine, human: str, count: int = 2) -> list[str]:
    return [factory.agent(engine, _project(engine), human).agent_id for _ in range(count)]


def _events(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event).where(t.event.c.kind == "member_updated").order_by(t.event.c.seq)
            )
        )


def test_an_owner_outside_the_project_moves_its_agent_to_nobody_or_to_another_of_theirs(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent, other = _agents(migrated, friend.id)
    migrated_events = len(_events(migrated))
    moved = move(friend, lent, reports_to=other)
    assert moved.status_code == 204, moved.text  # nothing of the project to show (§1.3)
    assert _boss_of(migrated, lent) == other
    assert len(_events(migrated)) == migrated_events + 1  # member_updated, as an admin's
    assert move(friend, lent, reports_to=None).status_code == 204
    assert _boss_of(migrated, lent) is None


def test_the_line_consent_for_the_old_edge_ends_with_the_move(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent, other = _agents(migrated, friend.id)
    boss = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    lent_id, boss_id = _row(migrated, lent).id, _row(migrated, boss.id).id
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == lent_id)
            .values(reports_to=boss_id, line_consent=True)
        )
    assert move(friend, lent, reports_to=other).status_code == 204
    assert _row(migrated, lent).line_consent is False


def test_an_owner_who_is_a_member_without_admin_may_name_themselves(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project(migrated), "member", human_id=friend.id)
    [lent] = _agents(migrated, friend.id, 1)
    moved = move(friend, lent, reports_to=friend.id)
    assert moved.status_code == 200, moved.text
    assert moved.json()["reports_to"] == friend.id
    assert _boss_of(migrated, lent) == friend.id


def test_the_owner_outside_the_project_may_not_name_themselves(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    [lent] = _agents(migrated, friend.id, 1)
    assert fields(move(friend, lent, reports_to=friend.id)) == {"reports_to": "not_a_member"}


def test_a_guest_is_never_the_target(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project(migrated), "guest", human_id=friend.id)
    [lent] = _agents(migrated, friend.id, 1)
    assert fields(move(friend, lent, reports_to=friend.id)) == {"reports_to": "guest"}


def test_a_cycle_is_refused(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent, other = _agents(migrated, friend.id)
    assert move(friend, other, reports_to=lent).status_code == 204
    assert fields(move(friend, lent, reports_to=other)) == {"reports_to": "cycle"}
    assert _boss_of(migrated, lent) is None


def test_another_owners_member_is_not_opened_by_this_path(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A target the caller does not own is the ordinary rules' case: members:admin."""
    friend = flow.human(make_client, migrated, "friend")
    [lent] = _agents(migrated, friend.id, 1)
    theirs = flow.agent(make_client, owner)
    outside = move(friend, lent, reports_to=theirs.id)
    assert outside.status_code == 404, outside.text  # not a member of the project (§1.3)
    factory.membership(migrated, _project(migrated), "member", human_id=friend.id)
    inside = move(friend, lent, reports_to=theirs.id)
    assert inside.status_code == 403, inside.text
    assert _boss_of(migrated, lent) is None


def test_it_opens_nothing_else_of_the_membership(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent, other = _agents(migrated, friend.id)
    for body in ({"reports_to": other, "role": "manager"}, {"role": "reviewer"}, {"areas": ["x/"]}):
        refused = move(friend, lent, **body)
        assert refused.status_code in (403, 404), body
    assert _boss_of(migrated, lent) is None and _row(migrated, lent).role == "coder"


def test_only_the_agents_own_owner_and_only_a_human(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    stranger = flow.human(make_client, migrated, "stranger")
    lent, other = _agents(migrated, friend.id)
    assert move(stranger, lent, reports_to=other).status_code in (403, 404)
    agent = flow.agent(make_client, owner)
    assert move(agent, lent, reports_to=other).status_code in (403, 404)
    assert _boss_of(migrated, lent) is None


def test_a_replayed_key_answers_as_the_first_call_did(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = flow.human(make_client, migrated, "friend")
    lent, other = _agents(migrated, friend.id)
    key = {"Idempotency-Key": "owner-reports-to-0001", "X-CSRF-Token": friend.csrf}
    path = f"/api/v1{PROJECT}/members/{lent}"
    first = friend.client.patch(path, json={"reports_to": other}, headers=key)
    again = friend.client.patch(path, json={"reports_to": other}, headers=key)
    assert (first.status_code, again.status_code) == (204, 204)
    assert again.headers["Idempotent-Replayed"] == "true"
