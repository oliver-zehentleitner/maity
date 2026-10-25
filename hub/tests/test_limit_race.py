"""docs/api.md §6.12: a limit's expiry against a renewal, on two real connections."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Engine, select, update

from maity_hub import availability, clock
from maity_hub import tables as t
from tests import factory
from tests.concurrency import background, finished, two_transactions, waiting


def _agent_with_a_passed_limit(engine: Engine) -> tuple[str, int]:
    project_id = factory.project(engine)
    owner = factory.human(engine)
    factory.membership(engine, project_id, "owner", human_id=owner)
    agent = factory.agent(engine, project_id, owner)
    passed = clock.now() - timedelta(minutes=1)
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == agent.membership_id)
            .values(limit_until=passed, limit_since=passed, limit_source="agent")
        )
    return project_id, agent.membership_id


def _limit(engine: Engine, membership_id: int) -> object:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership.c.limit_until).where(t.membership.c.id == membership_id)
        ).scalar()


def test_an_expiry_that_read_before_a_renewal_clears_nothing(migrated: Engine) -> None:
    """The sweep read the passed limit; the agent declares a new one and commits; the
    sweep's clearing then finds a different `until` and leaves the new limit alone."""
    project_id, membership_id = _agent_with_a_passed_limit(migrated)
    renewed = clock.now() + timedelta(hours=3)
    with two_transactions(migrated) as (sweep, agent):
        [stale] = availability.due_limits(sweep, project_id)
        row = agent.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
        availability.set_agent_limit(
            agent,
            row,
            renewed,
            source="agent",
            harness=None,
            reason=None,
            placement_id=None,
            actor=None,
        )
        agent.commit()
        project = sweep.execute(select(t.project).where(t.project.c.id == project_id)).one()
        assert availability.end_limit(sweep, project, stale) is False
        sweep.commit()
    assert _limit(migrated, membership_id) == renewed
    with migrated.connect() as conn:
        ended = conn.execute(select(t.event).where(t.event.c.kind == "member_limit_ended")).all()
    assert ended == []


def test_a_renewal_waits_for_a_running_expiry_and_then_stands(migrated: Engine) -> None:
    """The sweep holds the project lock and clears the passed limit; the agent's new
    limit waits for it, then is stored: the expiry ends the old limit once and never
    the new one."""
    project_id, membership_id = _agent_with_a_passed_limit(migrated)
    renewed = clock.now() + timedelta(hours=3)
    with two_transactions(migrated) as (sweep, agent), background() as run:
        availability.expire_limits(sweep, project_id)  # takes the lock, clears, announces

        def renew() -> None:
            row = agent.execute(
                select(t.membership).where(t.membership.c.id == membership_id)
            ).one()
            availability.set_agent_limit(
                agent,
                row,
                renewed,
                source="agent",
                harness=None,
                reason=None,
                placement_id=None,
                actor=None,
            )
            agent.commit()

        step = run(renew)
        assert waiting(step)  # blocked on the project lock the expiry holds
        sweep.commit()
        finished(step)
    assert _limit(migrated, membership_id) == renewed
    with migrated.connect() as conn:
        ended = conn.execute(select(t.event).where(t.event.c.kind == "member_limit_ended")).all()
    assert len(ended) == 1
