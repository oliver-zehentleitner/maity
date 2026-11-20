"""The account's own lists cost the same statements for 3 rows as for 30 (tests/list_rows.py):
the caller's agents, sessions, contacts, chats across projects, reports, projects, and the
versions of a soul and of the preferences."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select

from maity_hub import avatars, clock
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.list_rows import flat_rows, same_for_3_and_30
from tests.test_chat_access import allow, deny, profile
from tests.test_cross_chats import create


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project_id(engine: Engine, slug: str = "maity") -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == slug)
        ).scalar_one()
    return found


def _humans(engine: Engine, n: int) -> list[str]:
    return [factory.human(engine, f"person-{new_id('human')[4:]}") for _ in range(n)]


@flat_rows("/agents")
def test_the_agents_cost_the_same_for_3_and_for_30(owner: flow.Human, migrated: Engine) -> None:
    def grow(n: int) -> None:
        for i in range(n):
            agent_id = profile(migrated, owner.id, f"agent-{new_id('agent')[4:]}")
            if i % 2:  # every second with its generated picture
                with migrated.begin() as conn:
                    avatars.store_generated(conn, agent_id)

    same_for_3_and_30(migrated, "/agents", lambda: owner.get("/agents"), grow)


@flat_rows("/agents/{}/soul/versions")
def test_a_soul_s_versions_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    agent = factory.agent(migrated, _project_id(migrated), owner.id)
    written = [0]

    def grow(n: int) -> None:
        with migrated.begin() as conn:
            for _ in range(n):
                written[0] += 1
                by_agent = written[0] % 2 == 0
                conn.execute(
                    insert(t.soul_version).values(
                        agent_id=agent.agent_id,
                        version=written[0],
                        markdown=f"soul {written[0]}",
                        by_kind="agent" if by_agent else "human",
                        by_id=agent.agent_id if by_agent else owner.id,
                        confirmed_by=owner.id if by_agent else None,
                        at=clock.now(),
                    )
                )

    route = "/agents/{}/soul/versions"
    same_for_3_and_30(
        migrated, route, lambda: owner.get(f"/agents/{agent.agent_id}/soul/versions"), grow
    )


@flat_rows("/auth/sessions")
def test_the_sessions_cost_the_same_for_3_and_for_30(owner: flow.Human, migrated: Engine) -> None:
    with migrated.connect() as conn:
        template = conn.execute(
            select(t.human_session).where(t.human_session.c.human_id == owner.id)
        ).one()

    def grow(n: int) -> None:
        with migrated.begin() as conn:
            for i in range(n):
                row = dict(template._mapping)
                row.update(
                    id_hash=secrets.token_hex(32),
                    public_id=new_id("human_session"),
                    created_at=clock.now() - timedelta(minutes=i + 1),
                    approved_by=template.public_id if i % 2 else None,
                    method="device_code" if i % 2 else template.method,
                )
                conn.execute(insert(t.human_session).values(row))

    same_for_3_and_30(migrated, "/auth/sessions", lambda: owner.get("/auth/sessions"), grow)


@flat_rows("/me/chat-access/history")
def test_the_chat_access_history_costs_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    def grow(n: int) -> None:
        for other in _humans(migrated, n):
            mine = profile(migrated, owner.id, f"agent-{new_id('agent')[4:]}")
            made = allow(owner, agents=[mine], owner_id=other, duration="day")
            assert made.status_code == 201, made.text  # one history entry: "created"

    same_for_3_and_30(
        migrated,
        "/me/chat-access/history",
        lambda: owner.get("/me/chat-access/history", params={"limit": 200}),
        grow,
    )


def _contacts(engine: Engine, owner_id: str, n: int, reverse: bool) -> None:
    others = _humans(engine, n)
    with engine.begin() as conn:
        for i, other in enumerate(others):
            pair = (other, owner_id) if reverse else (owner_id, other)
            since = clock.now() - timedelta(seconds=i)
            conn.execute(
                insert(t.contact).values(human_id=pair[0], contact_id=pair[1], since=since)
            )


@flat_rows("/me/contacts")
def test_the_contacts_cost_the_same_for_3_and_for_30(owner: flow.Human, migrated: Engine) -> None:
    same_for_3_and_30(
        migrated,
        "/me/contacts",
        lambda: owner.get("/me/contacts", params={"limit": 200}),
        lambda n: _contacts(migrated, owner.id, n, reverse=False),
    )


@flat_rows("/me/contact-of")
def test_the_contact_of_list_costs_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    same_for_3_and_30(
        migrated,
        "/me/contact-of",
        lambda: owner.get("/me/contact-of", params={"limit": 200}),
        lambda n: _contacts(migrated, owner.id, n, reverse=True),
    )


@flat_rows("/me/conversations")
def test_the_chats_across_projects_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "second")
    projects = {slug: _project_id(migrated, slug) for slug in ("maity", "second")}
    added = [0]

    def grow(n: int) -> None:
        for _ in range(n):
            added[0] += 1
            slug = ("maity", "second")[added[0] % 2]  # a direct chat in either project
            agent = factory.agent(migrated, projects[slug], owner.id)
            path = f"/projects/maintainer/{slug}/conversations/{agent.agent_id}/messages"
            sent = owner.post(path, {"body": "hello"})
            assert sent.status_code == 201, sent.text

    same_for_3_and_30(
        migrated,
        "/me/conversations",
        lambda: owner.get("/me/conversations", params={"limit": 200}),
        grow,
    )


@flat_rows("/me/cross-chats")
def test_the_cross_chats_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "other")
    home = flow.agent(make_client, owner, "maity")
    away = flow.agent(make_client, owner, "other")

    def grow(n: int) -> None:
        for i in range(n):
            made = create(owner, home.id, away.id, title=f"room {i}")
            assert made.status_code == 201, made.text
            if i % 2:  # every second with a message, its preview and unread count
                said = home.post(f"/me/cross-chats/{made.json()['id']}/messages", {"body": "hi"})
                assert said.status_code == 201, said.text

    same_for_3_and_30(
        migrated,
        "/me/cross-chats",
        lambda: owner.get("/me/cross-chats", params={"limit": 200}),
        grow,
    )


@flat_rows("/me/cross-chats/{}/messages")
def test_a_cross_chat_s_messages_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "other")
    home = flow.agent(make_client, owner, "maity")
    away = flow.agent(make_client, owner, "other")
    made = create(owner, home.id, away.id)
    assert made.status_code == 201, made.text
    chat = f"/me/cross-chats/{made.json()['id']}/messages"
    writers: list[Any] = [owner, home, away]
    sent = [0]

    def grow(n: int) -> None:
        for _ in range(n):
            sent[0] += 1
            said = writers[sent[0] % 3].post(chat, {"body": f"message {sent[0]}"})
            assert said.status_code == 201, said.text

    same_for_3_and_30(
        migrated,
        "/me/cross-chats/{}/messages",
        lambda: owner.get(chat, params={"limit": 200}),
        grow,
    )


@flat_rows("/me/preferences/versions")
def test_the_preferences_versions_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    version = [0]

    def grow(n: int) -> None:
        for _ in range(n):
            body: dict[str, Any] = {"markdown": f"version {version[0] + 1}"}
            if version[0]:
                body["base_version"] = version[0]
            put = owner.client.put(
                "/api/v1/me/preferences", json=body, headers={"X-CSRF-Token": owner.csrf}
            )
            assert put.status_code == 200, put.text
            version[0] = put.json()["version"]

    same_for_3_and_30(
        migrated,
        "/me/preferences/versions",
        lambda: owner.get("/me/preferences/versions", params={"limit": 200}),
        grow,
    )


@flat_rows("/me/reports")
def test_the_own_reports_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    project_id = _project_id(migrated)
    with migrated.connect() as conn:
        member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == owner.id)
        ).scalar_one()
    kinds = ("card", "profile", "project", "message")

    def grow(n: int) -> None:
        targets = {
            "card": lambda: factory.card(migrated, project_id, member),
            "profile": lambda: _humans(migrated, 1)[0],
            "project": lambda: project_id,
            "message": lambda: f"{project_id}/1",
        }
        with migrated.connect() as conn:
            mine = t.abuse_report.c.account_id == owner.id
            done = int(conn.execute(select(func.count()).where(mine)).scalar_one())
        for i in range(n):
            kind = kinds[(done + i) % len(kinds)]
            target = targets[kind]()
            with migrated.begin() as conn:
                conn.execute(
                    insert(t.abuse_report).values(
                        id=new_id("abuse_report"),
                        reporter=owner.id,
                        account_id=owner.id,
                        target_type=kind,
                        target_id=target,
                        project_id=project_id,
                        reason="spam",
                        status="open",
                        created_at=clock.now() - timedelta(seconds=done + i),
                    )
                )

    same_for_3_and_30(
        migrated, "/me/reports", lambda: owner.get("/me/reports", params={"limit": 200}), grow
    )


@flat_rows("/projects")
def test_the_projects_cost_the_same_for_3_and_for_30(owner: flow.Human, migrated: Engine) -> None:
    def grow(n: int) -> None:
        for _ in range(n):
            project_id = factory.project(migrated, f"p-{new_id('project')[4:]}".lower())
            factory.membership(migrated, project_id, "owner", human_id=owner.id)

    same_for_3_and_30(migrated, "/projects", lambda: owner.get("/projects"), grow)


# The lists below sit under a key of their own, not `items` (ub25's review of #2039): `rows=`
# counts the list there.


def _under(*keys: str) -> Any:
    """`rows` for `same_for_3_and_30`: the rows of the answer's lists under `keys`, together."""

    def rows(answer: Any) -> int:
        body = answer.json()
        assert all(isinstance(body[key], list) for key in keys), answer.text
        return sum(len(body[key]) for key in keys)

    return rows


def _shared_projects(engine: Engine, n: int, *human_ids: str) -> None:
    """n more projects, each with every one of `human_ids` as an active member (the first as
    the owner)."""
    for _ in range(n):
        project_id = factory.project(engine, f"p-{new_id('project')[4:]}".lower())
        for i, human_id in enumerate(human_ids):
            factory.membership(
                engine, project_id, "owner" if i == 0 else "member", human_id=human_id
            )


@flat_rows("/me/chat-access")
def test_the_chat_access_lists_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    made = [0]

    def grow(n: int) -> None:
        for other in _humans(migrated, n):
            made[0] += 1
            mine = profile(migrated, owner.id, f"agent-{new_id('agent')[4:]}")
            rule = (allow, deny)[made[0] % 2]  # every second one a deny
            answer = rule(owner, agents=[mine], owner_id=other)
            assert answer.status_code == 201, answer.text

    same_for_3_and_30(
        migrated,
        "/me/chat-access",
        lambda: owner.get("/me/chat-access"),
        grow,
        rows=_under("allow", "deny"),
    )


@flat_rows("/me")
def test_the_caller_s_projects_in_me_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    same_for_3_and_30(
        migrated,
        "/me",
        lambda: owner.get("/me"),
        lambda n: _shared_projects(migrated, n, owner.id),
        rows=_under("projects"),
    )


@flat_rows("/me/broadcasts")
def test_the_broadcast_choice_s_agents_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    chosen: list[str] = []

    def grow(n: int) -> None:
        chosen.extend(profile(migrated, owner.id, f"agent-{new_id('agent')[4:]}") for _ in range(n))
        answer = owner.patch("/me/broadcasts", {"mode": "accept_only", "agents": chosen})
        assert answer.status_code == 200, answer.text

    same_for_3_and_30(
        migrated,
        "/me/broadcasts",
        lambda: owner.get("/me/broadcasts"),
        grow,
        rows=_under("agents"),
    )


@flat_rows("/me/preferences")
def test_the_preferences_projects_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    same_for_3_and_30(
        migrated,
        "/me/preferences",
        lambda: owner.get("/me/preferences"),
        lambda n: _shared_projects(migrated, n, owner.id),
        rows=_under("projects"),
    )


@flat_rows("/people/{}")
def test_a_person_s_projects_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    """Another person's projects that the caller shares with them. Their `agents` are listed
    only where the person's public page is served (§16.9); that list is not measured here."""
    other = factory.human(migrated, "colleague")
    _shared_projects(migrated, 1, other, owner.id)  # with nothing shared, the person is not found
    same_for_3_and_30(
        migrated,
        "/people/{}",
        lambda: owner.get("/people/colleague"),
        lambda n: _shared_projects(migrated, n, other, owner.id),
        rows=_under("projects"),
    )
