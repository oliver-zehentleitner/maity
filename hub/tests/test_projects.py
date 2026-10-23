"""docs/api.md §6.1 and §6.9: projects, state, policy, absence, rules."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _project_row(engine: Engine, slug: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.project).where(t.project.c.slug == slug)).one()


def test_a_created_project_has_the_contract_shape(owner: flow.Human) -> None:
    body = flow.project(
        owner,
        "maity",
        repository={"url": "https://github.com/oliver-zehentleitner/maity"},
        keep_the_why=True,
    )
    assert set(body) == {
        "slug",
        "name",
        "state",
        "state_note",
        "state_changed_at",
        "repository",
        "logo",
        "banner",
        "keep_the_why",
        "keep_the_why_export",
        "policy",
        "absence",
        "settings",
        "rules_version",
        "created_at",
    }
    assert body["state"] == "build"
    assert body["logo"] == body["banner"] == {"available": False, "source": None}
    assert body["repository"] == {
        "url": "https://github.com/oliver-zehentleitner/maity",
        "default_branch": "main",
        "forge": "github",
        "probe_configured": False,
    }
    assert body["policy"] == {
        "preset": "hierarchical",
        "claim_policy": "self-claim",
        "done_authority": "reviewer",
        "contract_arbiter": "role:admin",
        "tag_authority": "human",
        "steward_writes": "cards_only",
        "lease_seconds": 7200,
        "signing": "optional",
        "spawn_requests": "consent",
        "spawn_consent_by": "human",
        "max_placements": 8,
        "on_runner_revoke": "inherit",  # the instance setting decides (§15.3)
    }
    assert body["absence"] is None and body["rules_version"] == 1
    me = owner.get("/me").json()
    assert me["projects"][0]["role"] == "owner"


def test_probe_configured_says_whether_the_hub_holds_a_token(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    client = make_client(forge_github_token="ghp_not_real")
    client.cookies.update(owner.client.cookies)
    response = client.post(
        "/api/v1/projects",
        json={"slug": "probed", "name": "P", "repository": {"url": "https://github.com/a/b"}},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert response.json()["repository"]["probe_configured"] is True
    assert "ghp_not_real" not in response.text


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/a/b",
        "http://github.com/a/b",
        "https://github.com/a",
        "https://evil.example/a/b",
    ],
)
def test_a_repository_must_be_on_a_configured_forge(owner: flow.Human, url: str) -> None:
    response = owner.post("/projects", {"slug": "x1", "name": "X", "repository": {"url": url}})
    assert response.json()["error"]["details"]["fields"] == {
        "repository.url": "not_a_configured_forge"
    }


def test_a_slug_is_unique_and_shaped(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    taken = owner.post("/projects", {"slug": "maity", "name": "Again"})
    assert taken.json()["error"]["details"]["fields"] == {"slug": "taken"}
    shaped = owner.post("/projects", {"slug": "Not A Slug", "name": "X"})
    assert shaped.headers["Maity-Error"] == "invalid"


def test_a_project_is_invisible_to_non_members(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    stranger = flow.human(make_client, migrated, "stranger")
    for path in ("/projects/maity", "/projects/maity/rules", "/projects/maity/members"):
        response = stranger.get(path)
        assert response.status_code == 404 and response.headers["Maity-Error"] == "not_found", path
    assert stranger.get("/projects").json()["items"] == []


def test_an_agent_lists_only_its_project(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "maity")
    flow.project(owner, "other")
    agent = flow.agent(make_client, owner, "maity")
    assert [p["slug"] for p in agent.get("/projects").json()["items"]] == ["maity"]
    assert agent.get("/projects/other").headers["Maity-Error"] == "not_found"


def test_a_state_change_needs_a_reason_and_bumps_the_rules(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    missing = owner.patch("/projects/maity", {"state": "freeze"})
    assert missing.json()["error"]["details"]["fields"] == {"reason": "required"}
    response = owner.patch(
        "/projects/maity", {"state": "freeze", "state_note": "release week", "reason": "0.1.0"}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["state_note"], body["rules_version"]) == (
        "freeze",
        "release week",
        2,
    )
    event = _events(migrated, "state_changed")[-1]
    assert event.audience == ["all"]
    assert event.payload == {"old": "build", "new": "freeze", "reason": "0.1.0", "rules_version": 2}
    assert _project_row(migrated, "maity").rules_changed_seq == event.seq


def test_an_unknown_state_is_invalid(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    response = owner.patch("/projects/maity", {"state": "paused", "reason": "x"})
    assert response.json()["error"]["details"]["fields"] == {"state": "unknown"}


def test_a_policy_preset_fills_the_fields_and_is_announced(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    response = owner.patch("/projects/maity", {"policy": {"preset": "solo"}, "reason": "alone"})
    policy = response.json()["policy"]
    assert policy["preset"] == "solo" and policy["done_authority"] == "holder"
    assert policy["contract_arbiter"] == owner.id  # solo: the owner arbitrates
    event = _events(migrated, "policy_changed")[-1]
    assert event.payload["old"]["preset"] == "hierarchical"
    assert event.payload["new"]["preset"] == "solo"
    assert event.payload["reason"] == "alone" and event.payload["rules_version"] == 2


def test_a_preset_keeps_who_answers_a_placements_consent(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    owner.patch("/projects/maity", {"policy": {"spawn_consent_by": "role"}, "reason": "agreed"})
    response = owner.patch("/projects/maity", {"policy": {"preset": "solo"}, "reason": "alone"})
    assert response.json()["policy"]["spawn_consent_by"] == "role"


@pytest.mark.parametrize(
    ("policy", "field"),
    [
        ({"claim_policy": "grab"}, "policy.claim_policy"),
        ({"lease_seconds": 599}, "policy.lease_seconds"),
        ({"lease_seconds": 86401}, "policy.lease_seconds"),
        ({"contract_arbiter": "agt-nobody"}, "policy.contract_arbiter"),
        ({"preset": "anarchy"}, "policy.preset"),
        ({"spawn_consent_by": "anyone"}, "policy.spawn_consent_by"),
    ],
)
def test_policy_values_are_checked(owner: flow.Human, policy: dict[str, Any], field: str) -> None:
    flow.project(owner, "maity")
    response = owner.patch("/projects/maity", {"policy": policy, "reason": "x"})
    assert field in response.json()["error"]["details"]["fields"]


def test_the_absence_is_the_owners_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    body = {"absence": {"until": "2026-11-01T00:00:00Z", "scope": "fixes may ship"}}
    response = owner.patch("/projects/maity", body)
    assert response.json()["absence"] == {
        "until": "2026-11-01T00:00:00Z",
        "scope": "fixes may ship",
    }
    assert _events(migrated, "absence_changed")[-1].payload["new"]["scope"] == "fixes may ship"
    admin_agent = flow.agent(make_client, owner, role="admin")
    refused = admin_agent.patch("/projects/maity", body)
    assert refused.status_code == 403 and refused.headers["Maity-Error"] == "forbidden"
    cleared = owner.patch("/projects/maity", {"absence": None})
    assert cleared.json()["absence"] is None


def test_an_admin_agent_cannot_change_state_or_policy(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner, "maity")
    admin_agent = flow.agent(make_client, owner, role="admin")
    response = admin_agent.patch("/projects/maity", {"state": "freeze", "reason": "x"})
    assert response.status_code == 403
    assert response.json()["error"]["details"] == {"scope": "project:admin"}


def test_owner_text_and_keep_the_why_bump_the_rules_with_rules_changed(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    owner.patch("/projects/maity", {"rules_markdown": "Commit in English.", "reason": "style"})
    owner.patch("/projects/maity", {"keep_the_why": True})
    events = _events(migrated, "rules_changed")
    assert [e.payload for e in events] == [{"version": 2, "reason": "style"}, {"version": 3}]
    assert all(e.audience == ["all"] for e in events)
    project = _project_row(migrated, "maity")
    assert (project.rules_version, project.rules_changed_seq) == (3, events[-1].seq)
    unchanged = owner.patch("/projects/maity", {"keep_the_why": True})
    assert unchanged.json()["rules_version"] == 3


def test_the_rules_are_generated_per_role(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "maity", keep_the_why=True)
    owner.patch("/projects/maity", {"rules_markdown": "Commit in English."})
    rules = owner.get("/projects/maity/rules")
    assert rules.headers["content-type"] == "text/markdown; charset=utf-8"
    assert rules.headers["ETag"] == '"2"'
    text = rules.text
    assert text.startswith("# Rules for Maity")
    assert "You own the project" in text
    assert "keep-the-why skill" in text and "Commit in English." in text
    member = flow.agent(make_client, owner, role="member")
    assert "You are a member" in member.get("/projects/maity/rules").text


def test_settings_carry_the_release_checklist(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    response = owner.patch(
        "/projects/maity", {"settings": {"release_checklist": ["CHANGELOG has the version"]}}
    )
    assert response.json()["settings"] == {
        "language": "en",
        "release_checklist": ["CHANGELOG has the version"],
        "onboarding": {"check_in_with": "coordinator"},
    }
    unknown = owner.patch("/projects/maity", {"settings": {"other": 1}})
    assert unknown.headers["Maity-Error"] == "invalid"


def test_the_name_and_a_note_are_rules_inputs(owner: flow.Human, migrated: Engine) -> None:
    flow.project(owner, "maity")
    assert owner.patch("/projects/maity", {"name": "Maity hub"}).json()["rules_version"] == 2
    assert owner.patch("/projects/maity", {"state_note": "busy week"}).json()["rules_version"] == 3
    assert owner.patch("/projects/maity", {"name": "Maity hub"}).json()["rules_version"] == 3
    assert [e.payload["version"] for e in _events(migrated, "rules_changed")] == [2, 3]
    both = owner.patch("/projects/maity", {"state": "freeze", "state_note": "0.1.0", "reason": "r"})
    assert both.json()["rules_version"] == 4  # the state change's own event marks it
    assert len(_events(migrated, "rules_changed")) == 2
    assert "Maity hub" in owner.get("/projects/maity/rules").text
