"""docs/api.md §6.2: a briefing's versions, who wrote each, and who reads them."""

from __future__ import annotations

import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import briefings
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def history(who: Any, member_id: str) -> Any:
    return who.get(f"/projects/maity/members/{member_id}/briefings")


def latest_member_updated(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == "member_updated").order_by(t.event.c.seq.desc())
        ).first()


def test_the_join_is_version_1_by_whoever_made_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, briefing="the hub")
    view = owner.get(f"/projects/maity/members/{agent.id}").json()
    assert (view["briefing"], view["briefing_version"]) == ("the hub", 1)
    assert view["briefing_by"] == {"kind": "human", "id": owner.id, "handle": "maintainer"}
    assert view["briefing_updated_at"] is not None
    [first] = history(owner, agent.id).json()["items"]
    assert (first["version"], first["text"], first["by"]["id"]) == (1, "the hub", owner.id)


def test_a_change_is_a_new_version_and_its_event_says_only_that(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, briefing="the hub")
    changed = owner.patch(f"/projects/maity/members/{agent.id}", {"briefing": "the hub, and CI"})
    assert changed.json()["briefing_version"] == 2
    event = latest_member_updated(migrated)
    assert (event.payload["changed"], event.payload["briefing_version"]) == (["briefing"], 2)
    assert "briefing" not in event.payload and "the hub" not in str(event.payload)
    items = history(owner, agent.id).json()["items"]
    assert [(i["version"], i["text"]) for i in items] == [(2, "the hub, and CI"), (1, "the hub")]
    same = owner.patch(f"/projects/maity/members/{agent.id}", {"briefing": "the hub, and CI"})
    assert same.json()["briefing_version"] == 2  # unchanged text: no new version


def test_an_admin_agents_change_names_the_agent(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    assert (
        admin.patch(f"/projects/maity/members/{member.id}", {"briefing": "docs"}).status_code == 200
    )
    [latest, _] = history(owner, member.id).json()["items"]
    assert latest["by"] == {"kind": "agent", "id": admin.id, "handle": latest["by"]["handle"]}


def test_who_reads_the_versions(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, briefing="the hub")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    member = flow.human(make_client, migrated, "plain")
    factory.membership(migrated, project_id, "member", human_id=member.id)
    stranger = flow.human(make_client, migrated, "stranger")
    admin_agent = flow.agent(make_client, owner, role="admin")
    assert history(owner, agent.id).status_code == 200
    assert history(member, agent.id).json()["error"]["details"] == {"scope": "members:admin"}
    assert history(agent, agent.id).status_code == 403  # the agent reads its current text only
    assert history(admin_agent, agent.id).status_code == 403  # humans only
    assert history(stranger, agent.id).status_code == 404
    assert history(owner, member.id).status_code == 404  # a human has no briefing
    assert history(owner, "agt-nobody").status_code == 404


def test_its_owner_reads_them_without_being_a_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside = flow.human(make_client, migrated, "outside")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    theirs = factory.agent(migrated, project_id, outside.id)  # its owner is no member
    found = history(outside, theirs.agent_id)
    assert found.status_code == 200, found.text


def test_two_admins_at_once_get_two_versions(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both edits land, each its own version: neither reads the version the other is
    about to write (on MariaDB the second one failed as a 500). Each write waits after
    its read for the other to read too; under the lock the other cannot, and the wait
    gives up."""
    agent = flow.agent(make_client, owner, briefing="v1")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    admin = flow.human(make_client, migrated, "co-admin")
    factory.membership(migrated, project_id, "admin", human_id=admin.id)
    both_read = threading.Barrier(2)
    real_update = update

    def after_both_read(*args: Any) -> Any:
        with contextlib.suppress(threading.BrokenBarrierError):
            both_read.wait(timeout=2)
        return real_update(*args)

    monkeypatch.setattr(briefings, "update", after_both_read)
    url = f"/projects/maity/members/{agent.id}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda who: who.patch(url, {"briefing": who.id}), [owner, admin]))
    assert [a.status_code for a in answers] == [200, 200], [a.text for a in answers]
    versions = [i["version"] for i in history(owner, agent.id).json()["items"]]
    assert versions == [3, 2, 1]


def test_the_packet_names_the_briefings_writer_and_version(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """§5.2: a membership's own briefing comes with who wrote it and its version."""
    agent = flow.agent(make_client, owner, briefing="the hub")
    owner.patch(f"/projects/maity/members/{agent.id}", {"briefing": "the hub, and CI"})
    block = agent.resume().json()["membership"]
    assert (block["briefing"], block["briefing_source"], block["briefing_version"]) == (
        "the hub, and CI",
        "membership",
        2,
    )
    assert block["briefing_by"] == {"kind": "human", "id": owner.id, "handle": "maintainer"}
