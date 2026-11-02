"""docs/api.md §19.3.1: what an agent is told, as far as the caller may read it."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update

from maity_hub import commitment, rules
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
        return str(conn.execute(select(t.project.c.id)).scalar_one())


def _read(who: Any, agent_id: str, **query: str) -> Any:
    return who.get(f"{PROJECT}/members/{agent_id}/briefing", params=query)


def _admin(make_client: ClientFactory, engine: Engine) -> flow.Human:
    admin = flow.human(make_client, engine, "second-admin")
    factory.membership(engine, _project(engine), "admin", human_id=admin.id)
    return admin


def _outsider_owner(make_client: ClientFactory, engine: Engine) -> tuple[flow.Human, str]:
    from tests.test_mentions import second_owners_agent

    human = flow.human(make_client, engine, "anna")
    return human, second_owners_agent(engine, "anna", "builder")


def test_the_owner_reads_the_parts_that_say_who_it_is_and_nothing_of_its_work(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    response = _read(owner, agent.id)
    assert response.status_code == 200, response.text
    view = response.json()
    assert {"generated_at", "me", "membership", "rules", "preferences", "memory"} <= set(view)
    assert "keep_the_why" in view and view["rules"]["markdown"]
    assert view["me"]["member_id"] == agent.id and "session" not in view["me"]
    assert view["membership"]["guide"]["role"]
    for work in ("events", "claims", "assigned", "requests", "handover", "ticker", "session"):
        assert work not in view


def test_reading_it_changes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)

    def state() -> tuple[int, int]:
        with migrated.connect() as conn:
            events = conn.execute(select(func.count()).select_from(t.event)).scalar_one()
            sessions = conn.execute(select(func.count()).select_from(t.agent_session)).scalar_one()
        return int(events), int(sessions)

    before = state()
    assert _read(owner, agent.id).status_code == 200
    assert state() == before


def test_who_may_ask(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    agent = flow.agent(make_client, owner)
    refused = _read(agent, agent.id)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    not_agent = _read(owner, owner.id)
    assert not_agent.json()["error"]["details"]["fields"] == {"member": "not_an_agent"}
    member = flow.human(make_client, migrated, "plain")
    factory.membership(migrated, _project(migrated), "member", human_id=member.id)
    assert _read(member, agent.id).status_code == 403
    stranger = flow.human(make_client, migrated, "stranger")
    assert _read(stranger, agent.id).status_code == 404
    unknown = _read(owner, agent.id, instance="nope")
    assert unknown.json()["error"]["details"]["fields"] == {"instance": "not_an_instance"}


def test_an_admin_gets_the_outline_of_the_soul_and_the_owners_preferences(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    written = owner.client.put(
        f"/api/v1/agents/{agent.id}/soul",
        json={"markdown": "the soul"},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert written.status_code == 200, written.text
    mine = _read(owner, agent.id).json()
    assert mine["memory"]["soul"]["markdown"] == "the soul"
    admin = _read(_admin(make_client, migrated), agent.id).json()
    assert "markdown" not in admin["memory"]["soul"]
    assert admin["memory"]["soul"]["version"] == mine["memory"]["soul"]["version"]


def test_an_owner_outside_the_project_reads_only_what_it_may_read_of_the_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna, agent_id = _outsider_owner(make_client, migrated)
    view = _read(anna, agent_id).json()
    assert set(view) == {"generated_at", "me", "membership"}
    assert {"briefing", "owner_preferences", "team", "paused"} <= set(view["membership"])
    assert "trust" not in view["membership"]


def test_a_humans_preferences_keep_their_text_for_that_human_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    written = owner.client.put(
        "/api/v1/me/preferences",
        json={"markdown": "be brief"},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert written.status_code == 200, written.text
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent.id)
            .values(owner_preferences=True)
        )
    mine = _read(owner, agent.id).json()["membership"]["owner_preferences"]
    assert mine["markdown"] == "be brief"
    admin = _read(_admin(make_client, migrated), agent.id).json()["membership"]
    assert "markdown" not in admin["owner_preferences"]
    assert admin["owner_preferences"]["human"]["id"] == owner.id


def test_a_store_the_caller_does_not_read_is_only_its_count(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_mentions import second_owners_agent

    anna = flow.human(make_client, migrated, "anna")
    factory.membership(migrated, _project(migrated), "reviewer", human_id=anna.id)
    agent_id = second_owners_agent(migrated, "anna", "builder")
    view = _read(anna, agent_id).json()["memory"]
    assert set(view["team"]) >= {"items", "total"}  # its owner reads its team
    assert set(view["role"]) == {"role", "total"}  # another role's, and no admin


@pytest.mark.parametrize("enabled", [True, False])
def test_the_keep_the_why_instruction_is_the_one_the_agent_gets(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, enabled: bool
) -> None:
    agent = flow.agent(make_client, owner)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(keep_the_why=enabled))
    block = _read(owner, agent.id).json()["keep_the_why"]
    assert block["instruction"] == (rules.KEEP_THE_WHY if enabled else None)


def test_an_outline_never_names_where_a_proposal_came_from(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    written = owner.client.put(
        "/api/v1/me/preferences",
        json={"markdown": "be brief"},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert written.status_code == 200, written.text
    origin = {"project": "someone/private", "request_id": "req-1"}
    with migrated.begin() as conn:
        conn.execute(update(t.preferences).values(proposed_by=origin))
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent.id)
            .values(owner_preferences=True)
        )
    outline = _read(_admin(make_client, migrated), agent.id).json()["membership"]
    assert set(outline["owner_preferences"]) == {
        "human", "version", "by", "confirmed_by", "updated_at"
    }  # fmt: skip
    assert "someone/private" not in str(outline)


def test_the_commitment_shows_for_one_instance_only(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = flow.agent(make_client, owner)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(keep_the_why=True))
    monkeypatch.setattr(commitment, "required", lambda project: True)
    assert "commitment" not in _read(owner, agent.id).json()["keep_the_why"]
    block = _read(owner, agent.id, instance=agent.instance).json()["keep_the_why"]
    assert block["commitment"] == "required" and block["ack"]
