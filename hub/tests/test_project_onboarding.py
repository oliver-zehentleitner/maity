"""§6.1 project onboarding and the once-per-membership advisory check-in."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from maity_hub.db import downgrade, migrate
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def put(owner: flow.Human, value: Any) -> Any:
    return owner.patch("/projects/maity", {"settings": {"onboarding": value}})


def test_default_checkin_and_no_briefing(owner: flow.Human, make_client: ClientFactory) -> None:
    assert owner.get("/projects/maity").json()["settings"]["onboarding"] == {
        "check_in_with": "coordinator"
    }
    agent = flow.agent(make_client, owner)
    packet = agent.resume().json()
    assert packet["membership"]["briefing"] is None
    assert packet["membership"]["briefing_source"] is None
    assert packet["onboarding"]["check_in_with"]["member_id"] == owner.id
    assert packet["onboarding"]["check_in_with"]["kind"] == "human"
    assert "before taking any work" in packet["onboarding"]["instruction"]
    assert put(owner, {}).status_code == 200
    assert "onboarding" not in agent.resume().json()
    assert put(owner, None).status_code == 200
    assert agent.resume().json()["onboarding"]["check_in_with"]["member_id"] == owner.id


def test_metadata_versions_reset_and_no_text_in_events(owner: flow.Human, migrated: Engine) -> None:
    before = owner.get("/projects/maity").json()["rules_version"]
    first = put(
        owner,
        {
            "briefing": "private instructions",
            "check_in_with": "coordinator",
            "version": "ignore",
            "by": ["ignore"],
            "updated_at": False,
        },
    )
    assert first.status_code == 200
    ob = first.json()["settings"]["onboarding"]
    assert ob["version"] == 1 and ob["by"]["id"] == owner.id
    assert ob["by"]["kind"] == "human" and ob["by"]["handle"]
    assert ob["updated_at"].endswith("Z")
    assert put(owner, ob).json()["settings"]["onboarding"] == ob
    assert put(owner, None).json()["settings"]["onboarding"] == {"check_in_with": "coordinator"}
    assert put(owner, {"briefing": "next"}).json()["settings"]["onboarding"]["version"] == 3
    assert owner.get("/projects/maity").json()["rules_version"] == before
    with migrated.connect() as conn:
        events = (
            conn.execute(select(t.event.c.payload).where(t.event.c.kind == "project_updated"))
            .scalars()
            .all()
        )
    changes = [event["fields"]["settings.onboarding"] for event in events]
    assert len(changes) == 3 and changes[1] is None
    assert changes[0]["version"] == 1 and changes[2]["version"] == 3
    assert "private instructions" not in str(events) and "next" not in str(events)
    assert all("briefing" not in (change or {}) for change in changes)


def test_admin_agent_can_only_patch_onboarding(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    result = agent.patch(
        "/projects/maity", {"settings": {"onboarding": {"briefing": "team startup"}}}
    )
    assert result.status_code == 200
    assert result.json()["settings"]["onboarding"]["by"]["id"] == agent.id
    extras: list[dict[str, Any]] = [
        {"name": "changed"},
        {"reason": "mixed"},
        {"keep_the_why": True},
    ]
    for extra in extras:
        assert (
            agent.patch("/projects/maity", {"settings": {"onboarding": {}}, **extra}).status_code
            == 403
        )
    assert (
        agent.patch(
            "/projects/maity", {"settings": {"onboarding": {}, "release_checklist": ["bad"]}}
        ).status_code
        == 403
    )
    assert (
        owner.get("/projects/maity").json()["settings"]["onboarding"]["briefing"] == "team startup"
    )
    assert agent.patch("/projects/maity", {"settings": {"onboarding": None}}).status_code == 200
    member = flow.agent(make_client, owner)
    assert member.patch("/projects/maity", {"settings": {"onboarding": {}}}).status_code == 403


def test_project_briefing_is_live_and_never_copied(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    fallback = flow.agent(make_client, owner)
    own = flow.agent(make_client, owner, briefing="my own job")
    put(owner, {"briefing": "first"})
    membership = fallback.resume().json()["membership"]
    assert membership["briefing"] == "first" and membership["briefing_source"] == "project"
    assert membership["briefing_version"] == 1 and membership["briefing_by"]["id"] == owner.id
    assert owner.get(f"/projects/maity/members/{fallback.id}").json()["briefing"] is None
    assert own.resume().json()["membership"]["briefing"] == "my own job"
    assert own.resume().json()["membership"]["briefing_source"] == "membership"
    put(owner, {"briefing": "second"})
    assert fallback.resume().json()["membership"]["briefing"] == "second"
    assert own.resume().json()["membership"]["briefing"] == "my own job"


@pytest.mark.parametrize("token", ["agt-not-a-member", "hum-not-a-member", "role:nonsense"])
def test_invalid_target(owner: flow.Human, token: str) -> None:
    result = put(owner, {"check_in_with": token})
    assert result.status_code == 400
    assert "settings.onboarding.check_in_with" in result.json()["error"]["details"]["fields"]


def test_role_and_coordinator_resolution_is_live(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    later = flow.agent(
        make_client, owner, role="admin", agent={"handle": "z-lead", "display_name": "Z lead"}
    )
    first = flow.agent(
        make_client, owner, role="admin", agent={"handle": "a-lead", "display_name": "A lead"}
    )
    human = flow.human(make_client, migrated, "0-lead")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=human.id)
    member = flow.agent(make_client, owner)
    assert member.resume().json()["onboarding"]["check_in_with"]["member_id"] == first.id
    put(owner, {"check_in_with": "role:admin"})
    assert member.resume().json()["onboarding"]["check_in_with"]["member_id"] == human.id
    put(owner, {"check_in_with": later.id})
    assert member.resume().json()["onboarding"]["check_in_with"]["member_id"] == later.id
    put(owner, {"check_in_with": member.id})
    assert "onboarding" not in member.resume().json()
    put(owner, {"check_in_with": "role:reviewer"})
    assert member.resume().json()["onboarding"]["check_in_with"]["member_id"] == first.id


@pytest.mark.parametrize("address", ["direct", "role", "chat"])
def test_first_target_message_checks_in_permanently(
    owner: flow.Human, make_client: ClientFactory, address: str
) -> None:
    member = flow.agent(make_client, owner)
    assert (
        member.post(
            "/projects/maity/events",
            {"kind": "message", "to": "all", "type": "notice", "body": "broadcast"},
        ).status_code
        == 201
    )
    assert "onboarding" in member.resume().json()
    body = {"kind": "message", "type": "notice", "body": "I joined"}
    if address == "chat":
        body.update(type="chat", conversation_id=member.id)
    else:
        body["to"] = owner.id if address == "direct" else "role:owner"
    assert member.post("/projects/maity/events", body).status_code == 201
    assert "onboarding" not in member.resume().json()
    put(owner, {"check_in_with": member.id})
    put(owner, None)
    assert "onboarding" not in member.resume().json()


def test_claim_marks_work_started_even_after_release(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    member = flow.agent(make_client, owner)
    task = owner.post("/projects/maity/tasks", {"title": "first", "body": "work"}).json()
    assert member.post(f"/projects/maity/tasks/{task['id']}/claim", {}).status_code == 200
    assert "onboarding" not in member.resume().json()
    assert member.post(f"/projects/maity/tasks/{task['id']}/release", {}).status_code == 200
    assert "onboarding" not in member.resume().json()
    # An upgrade also recognizes a historical claim, including one no longer held.
    downgrade(migrated, "0039")
    migrate(migrated)
    with migrated.connect() as conn:
        assert (
            conn.execute(
                select(t.membership.c.onboarded_at).where(t.membership.c.agent_id == member.id)
            ).scalar_one()
            is not None
        )


def test_removal_resets_named_target_without_losing_briefing(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    target = flow.agent(make_client, owner)
    member = flow.agent(make_client, owner)
    put(owner, {"briefing": "keep me", "check_in_with": target.id})
    assert owner.delete(f"/projects/maity/members/{target.id}").status_code == 200
    setting = owner.get("/projects/maity").json()["settings"]["onboarding"]
    assert setting["briefing"] == "keep me" and setting["check_in_with"] == "coordinator"
    assert setting["version"] == 2
    assert member.resume().json()["onboarding"]["check_in_with"]["member_id"] == owner.id


def test_group_chat_does_not_count_but_target_instance_does(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
) -> None:
    from maity_hub.events import Actor, emit, transaction

    target = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        mine = conn.execute(select(t.membership).where(t.membership.c.agent_id == member.id)).one()
    with transaction(migrated) as conn:
        emit(
            conn,
            mine.project_id,
            "message",
            ["all"],
            {"type": "chat", "to": target.id, "conversation_id": "cnv-group", "body": "joined"},
            actor=Actor(membership_id=mine.id),
        )
    assert "onboarding" in member.resume().json()
    # The event writer has already validated the address. Instance-targeted messages
    # arrive here once their producer is merged; check-in is still per membership.
    with transaction(migrated) as conn:
        emit(
            conn,
            mine.project_id,
            "message",
            [f"member:{target.id}"],
            {"type": "notice", "to": f"{target.id}#{target.instance}", "body": "joined"},
            actor=Actor(membership_id=mine.id),
        )
    assert "onboarding" not in member.resume().json()


def test_settings_validation_and_whole_object_replacement(owner: flow.Human) -> None:
    assert put(owner, {"briefing": "x" * 16385}).status_code == 400
    assert put(owner, {"briefing": "valid", "check_in_with": "coordinator"}).status_code == 200
    setting = put(owner, {"briefing": "replacement"}).json()["settings"]["onboarding"]
    assert "check_in_with" not in setting and setting["version"] == 2
    assert put(owner, {"unexpected": True}).status_code == 400


def test_onboarding_merge_and_version_use_the_locked_row(
    owner: flow.Human,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import Connection, update

    from maity_hub import events
    from maity_hub.routes import projects

    def changed_since_membership(conn: Connection, project_id: str) -> Any:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(
                onboarding_version=7,
                settings={
                    "onboarding": {"briefing": "concurrent", "version": 7},
                    "release_checklist": ["keep concurrent"],
                },
            )
        )
        return events.lock_project(conn, project_id)

    monkeypatch.setattr(projects, "lock_project", changed_since_membership)
    settings = put(owner, {"briefing": "mine"}).json()["settings"]
    assert settings["onboarding"]["version"] == 8
    assert settings["release_checklist"] == ["keep concurrent"]
