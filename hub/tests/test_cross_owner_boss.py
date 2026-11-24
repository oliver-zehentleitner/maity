"""docs/api.md §6.2, "What the edge does": a boss of another owner than its subordinate gets the
subordinate's `session_paused` and nothing else the hub routes to a boss. `member_not_listening`,
`session_model_changed`, `holder_stalled`, `claim_expired`, `member_availability_changed`,
`cover_started`, `cover_ended` and the added `member:<id>` of a takeover's `member_joined` leave
it out, and the admins read what they read without a boss. A boss of the same owner still gets
them all (tsk-jhjzm9bpd2jx)."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, select, update

from maity_hub import availability, cover, not_listening
from maity_hub import tables as t
from maity_hub.routes import joins
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def other_owner(make_client: ClientFactory, engine: Engine) -> flow.Human:
    """A second human, an admin of the project, who owns agents of their own."""
    other = flow.human(make_client, engine, "other")
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(engine, project_id, "admin", human_id=other.id)
    return other


def row_of(conn: Connection, agent_id: str) -> Any:
    return conn.execute(
        select(t.membership).where(
            t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True)
        )
    ).one()


def reports_to(engine: Engine, member: flow.Agent, boss: flow.Agent) -> None:
    with engine.begin() as conn:
        boss_row = row_of(conn, boss.id)
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == row_of(conn, member.id).id)
            .values(reports_to=boss_row.id)
        )


def _not_listening(conn: Connection, member: Any, other: Any) -> list[str]:
    return not_listening.audience_of(conn, member)  # member_not_listening, session_model_changed


def _stalled(conn: Connection, member: Any, other: Any) -> list[str]:
    return not_listening.audience_of(conn, member, admins_always=False)  # holder_stalled, ...


def _availability(conn: Connection, member: Any, other: Any) -> list[str]:
    project = conn.execute(select(t.project).where(t.project.c.id == member.project_id)).one()
    return availability.changed_audience(conn, member, project)


def _cover(conn: Connection, member: Any, other: Any) -> list[str]:
    return cover._audience(conn, member, other)  # cover_started, cover_ended


def _takeover(conn: Connection, member: Any, other: Any) -> list[str]:
    project = conn.execute(select(t.project).where(t.project.c.id == member.project_id)).one()
    new = SimpleNamespace(takes_over={"member_id": member.agent_id})
    return joins._told_of_takeover(conn, project, new)  # member_joined's added tokens


AUDIENCES: dict[str, Callable[[Connection, Any, Any], list[str]]] = {
    "member_not_listening and session_model_changed": _not_listening,
    "holder_stalled and claim_expired": _stalled,
    "member_availability_changed": _availability,
    "cover_started and cover_ended": _cover,
    "member_joined of a takeover": _takeover,
}


@pytest.mark.parametrize("kind", list(AUDIENCES))
def test_a_boss_of_another_owner_is_left_out_and_the_admins_read_as_without_a_boss(
    kind: str, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_owner(make_client, migrated)
    agent = flow.agent(make_client, owner)
    colleague = flow.agent(make_client, owner)
    boss = flow.agent(make_client, other, role="manager")
    with migrated.connect() as conn:
        without = AUDIENCES[kind](conn, row_of(conn, agent.id), row_of(conn, colleague.id))
    reports_to(migrated, agent, boss)
    with migrated.connect() as conn:
        got = AUDIENCES[kind](conn, row_of(conn, agent.id), row_of(conn, colleague.id))
    assert f"member:{boss.id}" not in got
    assert got == without  # the audience the agent has without a boss, the admins' part too
    if kind == "holder_stalled and claim_expired":
        assert "trust:admin" in got  # read by the admins only while there is no boss to tell


@pytest.mark.parametrize("kind", list(AUDIENCES))
def test_a_boss_of_the_same_owner_still_gets_each_kind(
    kind: str, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    colleague = flow.agent(make_client, owner)
    boss = flow.agent(make_client, owner, role="manager")
    reports_to(migrated, agent, boss)
    with migrated.connect() as conn:
        got = AUDIENCES[kind](conn, row_of(conn, agent.id), row_of(conn, colleague.id))
    assert f"member:{boss.id}" in got
    if kind == "holder_stalled and claim_expired":
        assert "trust:admin" not in got  # with a boss to report to, the admins do not read


def _reports_to_human(engine: Engine, member: flow.Agent, human_id: str) -> None:
    with engine.begin() as conn:
        boss = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
            )
        ).scalar_one()
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == row_of(conn, member.id).id)
            .values(reports_to=boss)
        )


def test_a_human_boss_of_another_owner_is_left_out_and_the_agents_own_human_is_not(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_owner(make_client, migrated)
    agent = flow.agent(make_client, owner)
    _reports_to_human(migrated, agent, other.id)
    with migrated.connect() as conn:
        assert f"member:{other.id}" not in not_listening.audience_of(conn, row_of(conn, agent.id))
    _reports_to_human(migrated, agent, owner.id)
    with migrated.connect() as conn:
        got = not_listening.audience_of(conn, row_of(conn, agent.id), admins_always=False)
    assert got[0] == f"member:{owner.id}"  # its own human, as its boss
    assert "trust:admin" not in got


def test_session_paused_still_reaches_a_boss_of_another_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_owner(make_client, migrated)
    agent = flow.agent(make_client, owner)
    boss = flow.agent(make_client, other, role="manager")
    reports_to(migrated, agent, boss)
    response = owner.patch(
        f"/projects/maintainer/maity/members/{agent.id}", {"paused": {"reason": "quota"}}
    )
    assert response.status_code == 200, response.text
    with migrated.connect() as conn:
        audience = conn.execute(
            select(t.event.c.audience)
            .where(t.event.c.kind == "session_paused")
            .order_by(t.event.c.seq.desc())
        ).first()
    assert audience is not None
    assert audience[0] == [f"member:{agent.id}", f"member:{boss.id}", "trust:admin"]
