"""Project working language (§6.1 and §5.2); personal language is separate."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Connection, Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def test_new_existing_and_resume_language_defaults(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    assert owner.get("/projects/maity").json()["settings"]["language"] == "en"
    assert owner.get("/projects").json()["items"][0]["settings"]["language"] == "en"
    agent = flow.agent(make_client, owner)
    assert agent.resume().json()["project"]["language"] == "en"
    assert owner.patch("/projects/maity", {"settings": {"language": "de"}}).status_code == 200
    assert agent.resume().json()["project"]["language"] == "de"
    assert (
        owner.patch("/projects/maity", {"settings": {"language": None}}).json()["settings"][
            "language"
        ]
        == "en"
    )
    assert agent.resume().json()["project"]["language"] == "en"


def test_language_merges_and_emits_only_effective_changes(
    owner: flow.Human, migrated: Engine
) -> None:
    owner.patch("/projects/maity", {"settings": {"language": "en"}})
    owner.patch("/projects/maity", {"settings": {"release_checklist": ["keep this"]}})
    with migrated.connect() as conn:
        before = conn.execute(select(t.project.c.rules_version)).scalar_one()
    response = owner.patch("/projects/maity", {"settings": {"language": "de"}})
    assert response.json()["settings"] == {
        "language": "de",
        "release_checklist": ["keep this"],
        "onboarding": {"check_in_with": "coordinator"},
    }
    owner.patch("/projects/maity", {"settings": {"language": "de"}})
    owner.patch("/projects/maity", {"settings": {}})
    owner.patch("/projects/maity", {"settings": {"language": None}})
    owner.patch("/projects/maity", {"settings": {"language": None}})
    with migrated.connect() as conn:
        events = conn.execute(
            select(t.event).where(t.event.c.kind == "project_updated").order_by(t.event.c.seq)
        ).all()
        project = conn.execute(select(t.project)).one()
    events = [e for e in events if "settings.language" in e.payload.get("fields", {})]
    assert [e.payload for e in events] == [
        {"fields": {"settings.language": "de"}},
        {"fields": {"settings.language": "en"}},
    ]
    assert all(e.audience == ["all"] for e in events)
    assert project.settings == {"release_checklist": ["keep this"]}
    assert project.rules_version == before


@pytest.mark.parametrize("language", ["fr", "EN", "", 1, True, [], {}])
def test_unknown_language_has_contract_error(owner: flow.Human, language: Any) -> None:
    response = owner.patch("/projects/maity", {"settings": {"language": language}})
    assert response.headers["Maity-Error"] == "invalid"
    assert response.json()["error"]["details"]["fields"] == {
        "settings.language": "unknown_language"
    }
    assert owner.get("/projects/maity").json()["settings"]["language"] == "en"


@pytest.mark.parametrize("role", ["admin", "member"])
def test_agents_cannot_change_or_reset_language(
    owner: flow.Human, make_client: ClientFactory, role: str
) -> None:
    agent = flow.agent(make_client, owner, role=role)
    for language in ["de", None]:
        response = agent.patch("/projects/maity", {"settings": {"language": language}})
        assert response.status_code == 403
        assert response.json()["error"]["details"]["reason"] == "humans_only"


@pytest.mark.parametrize(("role", "status"), [("admin", 200), ("member", 403)])
def test_only_human_project_admins_can_set_language(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, role: str, status: int
) -> None:
    human = flow.human(make_client, migrated, "other")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, role, human_id=human.id)
    assert human.patch("/projects/maity", {"settings": {"language": "de"}}).status_code == status


@pytest.mark.parametrize("checklist_write", [True, False])
def test_settings_merge_uses_the_row_read_under_the_project_lock(
    owner: flow.Human,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    checklist_write: bool,
) -> None:
    from maity_hub import events
    from maity_hub.routes import projects

    locked: list[str] = []

    def changed_since_membership(conn: Connection, project_id: str) -> Any:
        # Deterministically model a writer committing after membership() read its snapshot
        # but before this PATCH acquires the lock. SQLite serializes real writers at BEGIN.
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(settings={"language": "de", "release_checklist": ["concurrent"]})
        )
        locked.append(project_id)
        return events.lock_project(conn, project_id)

    monkeypatch.setattr(projects, "lock_project", changed_since_membership, raising=False)
    if checklist_write:
        response = owner.patch("/projects/maity", {"settings": {"release_checklist": ["new"]}})
        expected = {"language": "de", "release_checklist": ["new"]}
    else:
        response = owner.patch("/projects/maity", {"settings": {"language": "en"}})
        expected = {"language": "en", "release_checklist": ["concurrent"]}
    assert response.status_code == 200
    assert locked
    assert response.json()["settings"] == {
        **expected,
        "onboarding": {"check_in_with": "coordinator"},
    }
    with migrated.connect() as conn:
        language_events = (
            conn.execute(select(t.event.c.payload).where(t.event.c.kind == "project_updated"))
            .scalars()
            .all()
        )
    language_events = [p for p in language_events if "settings.language" in p.get("fields", {})]
    assert language_events == ([] if checklist_write else [{"fields": {"settings.language": "en"}}])
