"""`maity-hub loadtest purge` (hub/context/replicas.md cac80c88): every row of the `lt-<n>`
accounts goes, in every table, and nothing of anyone else's. The scan reads every table, so a new
table that keeps something of an account fails here until `purge` handles it."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import loadtest
from maity_hub import tables as t
from maity_hub.db import metadata
from tests import flow
from tests.conftest import ClientFactory
from tests.test_loadtest import signed_call


def everything(engine: Engine) -> dict[str, list[str]]:
    """Every row of every table, as text."""
    with engine.connect() as conn:
        return {
            table.name: [json.dumps(list(row), default=str) for row in conn.execute(select(table))]
            for table in metadata.tables.values()
        }


def secrets_of(seeded: list[dict[str, Any]], engine: Engine) -> set[str]:
    """What names a seeded account anywhere: its ids, its agents' and credentials', its handle."""
    found = set()
    with engine.connect() as conn:
        for one in seeded:
            human = conn.execute(select(t.human.c.id).where(t.human.c.handle == one["handle"]))
            found.add(str(human.scalar_one()))
            found.add(f'"{one["handle"]}"')
            for agent in one["agents"]:
                found |= {agent["agent_id"], agent["credential_id"], agent["verifier"]}
        found |= set(
            conn.execute(
                select(t.project.c.id).where(t.project.c.owner_id.in_(list(found)))
            ).scalars()
        )
    return found


def busy(make_client: ClientFactory, one: dict[str, Any]) -> None:
    """What `run.js` does with an account: waits, a message, a read, the bell; and a card."""
    client = make_client()
    path = f"/api/v1/projects/{one['owner']}/{one['slug']}"
    writer, waiter = (SimpleNamespace(**a) for a in one["agents"])
    cursor = signed_call(client, waiter, "GET", f"{path}/events", "after=latest").json()["cursor"]
    sent = signed_call(
        client, writer, "POST", f"{path}/events",
        kind="message", type="notice", to=waiter.agent_id, body="load sent:1",
    )  # fmt: skip
    assert sent.status_code == 201, sent.text
    assert (
        signed_call(client, waiter, "GET", f"{path}/events", f"after={cursor}").status_code == 200
    )
    made = signed_call(client, writer, "POST", f"{path}/tasks", title="load card")
    assert made.status_code == 201, made.text
    assert signed_call(client, writer, "GET", f"{path}/tasks").status_code == 200
    client.cookies.set("maity_session", one["session"])
    assert client.get("/api/v1/me/notifications", params={"limit": 0}).status_code == 200


@pytest.fixture
def real(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """Someone else on the same hub, with a project, an agent and a message of their own."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    flow.agent(make_client, owner)
    return owner


def test_purge_leaves_no_trace_of_the_accounts_and_keeps_everything_else(
    make_client: ClientFactory, migrated: Engine, real: flow.Human
) -> None:
    before = everything(migrated)
    seeded = [loadtest.seed_one(migrated, n) for n in range(2)]
    for one in seeded:
        busy(make_client, one)
    found = secrets_of(seeded, migrated)
    assert any(
        any(s in row for s in found) for rows in everything(migrated).values() for row in rows
    )
    counted = loadtest.purge(migrated, change=False)
    assert counted["human"] == 2 and counted["project"] == 2
    assert loadtest.purge(migrated, change=True) == counted
    after = everything(migrated)
    left = {
        name: [row for row in rows if any(s in row for s in found)] for name, rows in after.items()
    }
    assert {name: rows for name, rows in left.items() if rows} == {}
    for name, rows in before.items():  # what was there before the seed is all still there
        missing = [row for row in rows if row not in after[name]]
        assert missing == [], name
    assert loadtest.purge(migrated, change=False) == {}


def test_purge_counts_without_changing(make_client: ClientFactory, migrated: Engine) -> None:
    loadtest.seed_one(migrated, 0)
    before = everything(migrated)
    assert loadtest.purge(migrated, change=False)["human"] == 1
    assert everything(migrated) == before


def test_purge_takes_only_lt_and_a_number(migrated: Engine, make_client: ClientFactory) -> None:
    """A human called `lt-x` or `lt-` is someone's real handle, not the seed's."""
    flow.human(make_client, migrated, "lt-x")
    assert loadtest.purge(migrated, change=True) == {}
    with migrated.connect() as conn:
        assert conn.execute(select(t.human.c.id).where(t.human.c.handle == "lt-x")).first()


def test_purge_leaves_a_real_account_called_lt_and_a_number(
    migrated: Engine, make_client: ClientFactory
) -> None:
    """An account made before the reservation, called `lt-7` with a real password hash and a
    project of its own, is not the seed's: `purge` still requires the password marker."""
    person = flow.human(make_client, migrated, "lt-7")
    flow.project(person)
    before = everything(migrated)
    loadtest.seed_one(migrated, 8)
    assert loadtest.purge(migrated, change=True)["human"] == 1
    assert everything(migrated) == before


def test_purge_refuses_a_project_with_a_real_member(
    make_client: ClientFactory, migrated: Engine, real: flow.Human
) -> None:
    one = loadtest.seed_one(migrated, 0)
    with migrated.begin() as conn:
        project = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == loadtest.SLUG)
        ).scalar_one()
        member = conn.execute(
            select(t.membership).where(t.membership.c.human_id == real.id)
        ).first()
        assert member is not None
        conn.execute(
            update(t.membership).where(t.membership.c.id == member.id).values(project_id=project)
        )
    before = everything(migrated)
    with pytest.raises(loadtest.Refused, match="not a load test account"):
        loadtest.purge(migrated, change=True)
    assert everything(migrated) == before
    assert one["handle"] == "lt-0"


def test_purge_refuses_an_account_that_is_a_member_elsewhere(
    make_client: ClientFactory, migrated: Engine, real: flow.Human
) -> None:
    loadtest.seed_one(migrated, 0)
    with migrated.begin() as conn:
        theirs = conn.execute(
            select(t.project.c.id).where(t.project.c.owner_id == real.id)
        ).scalar_one()
        mine = conn.execute(
            select(t.membership.c.id)
            .join(t.human, t.human.c.id == t.membership.c.human_id)
            .where(t.human.c.handle == "lt-0")
        ).scalar_one()
        conn.execute(
            update(t.membership).where(t.membership.c.id == mine).values(project_id=theirs)
        )
    with pytest.raises(loadtest.Refused, match="is a member of project"):
        loadtest.purge(migrated, change=True)


def test_the_command_counts_unless_applied_and_refuses_an_unnamed_hub(
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from maity_hub import cli

    loadtest.seed_one(migrated, 0)
    monkeypatch.setenv("MAITY_DATABASE_URL", migrated.url.render_as_string(hide_password=False))
    monkeypatch.setenv("MAITY_PUBLIC_URL", "https://maity.team")
    monkeypatch.setenv("LOADTEST_CONFIRMED_TEST_SYSTEM", "maity.team")
    monkeypatch.delenv("LOADTEST_CONFIRMED_PRODUCTION", raising=False)
    assert cli.main(["loadtest", "purge", "--apply"]) == 2  # production needs its own name
    monkeypatch.setenv("LOADTEST_CONFIRMED_PRODUCTION", "maity.team")
    assert cli.main(["loadtest", "purge"]) == 0
    assert "would delete the rows of 1 humans" in capsys.readouterr().out
    assert loadtest.purge(migrated, change=False)["human"] == 1
    assert cli.main(["loadtest", "purge", "--apply"]) == 0
    assert "deleted the rows of 1 humans" in capsys.readouterr().out
    assert loadtest.purge(migrated, change=False) == {}


def test_purge_refuses_a_row_that_is_also_someone_elses(
    make_client: ClientFactory, migrated: Engine, real: flow.Human
) -> None:
    """An event of a real project that names a load test member as its actor: deleting it with
    the member would take a piece of the real project's history."""
    loadtest.seed_one(migrated, 0)
    with migrated.begin() as conn:
        theirs = conn.execute(
            select(t.project.c.id).where(t.project.c.owner_id == real.id)
        ).scalar_one()
        event = conn.execute(
            select(t.event.c.seq).where(t.event.c.project_id == theirs).limit(1)
        ).scalar_one()
        mine = conn.execute(
            select(t.membership.c.id)
            .join(t.human, t.human.c.id == t.membership.c.human_id)
            .where(t.human.c.handle == "lt-0")
        ).scalar_one()
        conn.execute(update(t.event).where(t.event.c.seq == event).values(actor_membership=mine))
    before = everything(migrated)
    with pytest.raises(loadtest.Refused, match="refers to a load test account and to"):
        loadtest.purge(migrated, change=True)
    assert everything(migrated) == before
