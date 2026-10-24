"""Project working language (§6.1 and §5.2); personal language is separate."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

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
    owner.patch("/projects/maity", {"settings": {"release_checklist": ["keep this"]}})
    with migrated.connect() as conn:
        before = conn.execute(select(t.project.c.rules_version)).scalar_one()
    response = owner.patch("/projects/maity", {"settings": {"language": "de"}})
    assert response.json()["settings"] == {"language": "de", "release_checklist": ["keep this"]}
    owner.patch("/projects/maity", {"settings": {"language": "de"}})
    owner.patch("/projects/maity", {"settings": {}})
    owner.patch("/projects/maity", {"settings": {"language": None}})
    owner.patch("/projects/maity", {"settings": {"language": None}})
    with migrated.connect() as conn:
        events = conn.execute(
            select(t.event).where(t.event.c.kind == "project_updated").order_by(t.event.c.seq)
        ).all()
        project = conn.execute(select(t.project)).one()
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
