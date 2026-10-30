"""docs/api.md §6.1 and §6.9: projects, state, policy, absence, rules."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
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
        memory={"provider": "keep-the-why"},
    )
    assert set(body) == {
        "id",
        "owner",
        "full_name",
        "slug",
        "aliases",
        "name",
        "state",
        "released_at",
        "state_note",
        "state_changed_at",
        "repository",
        "logo",
        "banner",
        "memory",
        "setup",
        "keep_the_why_export",
        "attachments",
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
        "probe_via": None,
        "owner_confirmed": False,
        "confirmed_by": None,
    }
    assert body["policy"] == {
        "preset": "hierarchical",
        "claim_policy": "self-claim",
        "done_authority": "reviewer",
        "contract_arbiter": "trust:admin",
        "tag_authority": "human",
        "steward_writes": "cards_only",
        "lease_seconds": 7200,
        "signing": "optional",
        "spawn_requests": "consent",
        "spawn_consent_by": "human",
        "max_placements": 8,
        "coordinator": "trust:admin",
        "coordinator_substitute": None,
        "on_runner_revoke": "inherit",  # the instance setting decides (§15.3)
        "badge": "off",
        "subtasks": "proposed",
        "swarm_public": "off",
        "keep_the_why": "required",
        "keep_the_why_defaults": "adopt",
        "merged_closes": "notify",  # §6.6: a merge wakes the done authority
        "jour_fixe": None,
        "jour_fixe_moderators": None,
        "takeover_window_minutes": 60,
        "member_agents": "on",
        "member_agents_max": 3,
    }
    assert body["absence"] is None and body["rules_version"] == 1
    me = owner.get("/me").json()
    assert me["projects"][0]["trust"] == "owner"


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
    for path in (
        "/projects/maintainer/maity",
        "/projects/maintainer/maity/rules",
        "/projects/maintainer/maity/members",
    ):
        response = stranger.get(path)
        assert response.status_code == 404 and response.headers["Maity-Error"] == "not_found", path
    assert stranger.get("/projects").json()["items"] == []


def test_an_agent_lists_only_its_project(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "maity")
    flow.project(owner, "other")
    agent = flow.agent(make_client, owner, "maity")
    assert [p["slug"] for p in agent.get("/projects").json()["items"]] == ["maity"]
    assert agent.get("/projects/maintainer/other").headers["Maity-Error"] == "not_found"


def test_a_state_change_needs_a_reason_and_bumps_the_rules(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    missing = owner.patch("/projects/maintainer/maity", {"state": "review"})
    assert missing.json()["error"]["details"]["fields"] == {"reason": "required"}
    response = owner.patch(
        "/projects/maintainer/maity",
        {"state": "review", "state_note": "release week", "reason": "0.1.0"},
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["state_note"], body["rules_version"]) == (
        "review",
        "release week",
        2,
    )
    event = _events(migrated, "state_changed")[-1]
    assert event.audience == ["all"]
    assert event.payload == {"old": "build", "new": "review", "reason": "0.1.0", "rules_version": 2}
    assert _project_row(migrated, "maity").rules_changed_seq == event.seq


def test_an_unknown_state_is_invalid(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    response = owner.patch("/projects/maintainer/maity", {"state": "paused", "reason": "x"})
    assert response.json()["error"]["details"]["fields"] == {"state": "unknown"}


@pytest.mark.parametrize("state", ["freeze", "fixes-only", "accepted"])
def test_the_states_before_2026_10_27_are_unknown(owner: flow.Human, state: str) -> None:
    flow.project(owner, "maity")
    response = owner.patch("/projects/maintainer/maity", {"state": state, "reason": "x"})
    assert response.json()["error"]["details"]["fields"] == {"state": "unknown"}


def test_only_a_human_owner_moves_a_project_to_launch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    deputy = flow.human(make_client, migrated, "deputy")
    factory.membership(migrated, _project_row(migrated, "maity").id, "admin", human_id=deputy.id)
    refused = deputy.patch("/projects/maintainer/maity", {"state": "launch", "reason": "go"})
    assert refused.status_code == 403
    assert _project_row(migrated, "maity").state == "build"
    launched = owner.patch("/projects/maintainer/maity", {"state": "launch", "reason": "go"})
    assert launched.status_code == 200 and launched.json()["state"] == "launch"
    assert _events(migrated, "state_changed")[-1].payload["new"] == "launch"
    # Leaving launch is any transition with a reason.
    back = deputy.patch("/projects/maintainer/maity", {"state": "build", "reason": "next"})
    assert back.status_code == 200 and back.json()["state"] == "build"


def test_a_policy_preset_fills_the_fields_and_is_announced(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"preset": "solo"}, "reason": "alone"}
    )
    policy = response.json()["policy"]
    assert policy["preset"] == "solo" and policy["done_authority"] == "holder"
    assert policy["contract_arbiter"] == owner.id  # solo: the owner arbitrates
    event = _events(migrated, "policy_changed")[-1]
    assert event.payload["old"]["preset"] == "hierarchical"
    assert event.payload["new"]["preset"] == "solo"
    assert event.payload["reason"] == "alone" and event.payload["rules_version"] == 2


def test_a_preset_keeps_who_answers_a_placements_consent(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    owner.patch(
        "/projects/maintainer/maity", {"policy": {"spawn_consent_by": "role"}, "reason": "agreed"}
    )
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"preset": "solo"}, "reason": "alone"}
    )
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
    response = owner.patch("/projects/maintainer/maity", {"policy": policy, "reason": "x"})
    assert field in response.json()["error"]["details"]["fields"]


def test_the_absence_is_the_owners_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "maity")
    body = {"absence": {"until": "2026-11-01T00:00:00Z", "scope": "fixes may ship"}}
    response = owner.patch("/projects/maintainer/maity", body)
    assert response.json()["absence"] == {
        "until": "2026-11-01T00:00:00Z",
        "scope": "fixes may ship",
    }
    assert _events(migrated, "absence_changed")[-1].payload["new"]["scope"] == "fixes may ship"
    admin_agent = flow.agent(make_client, owner, role="admin")
    refused = admin_agent.patch("/projects/maintainer/maity", body)
    assert refused.status_code == 403 and refused.headers["Maity-Error"] == "forbidden"
    cleared = owner.patch("/projects/maintainer/maity", {"absence": None})
    assert cleared.json()["absence"] is None


def test_an_admin_agent_cannot_change_state_or_policy(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner, "maity")
    admin_agent = flow.agent(make_client, owner, role="admin")
    response = admin_agent.patch("/projects/maintainer/maity", {"state": "review", "reason": "x"})
    assert response.status_code == 403
    assert response.json()["error"]["details"] == {"scope": "project:admin"}


def test_owner_text_and_keep_the_why_bump_the_rules_with_rules_changed(
    owner: flow.Human, migrated: Engine
) -> None:
    flow.project(owner, "maity", memory={"provider": "none"})
    owner.patch(
        "/projects/maintainer/maity", {"rules_markdown": "Commit in English.", "reason": "style"}
    )
    owner.patch("/projects/maintainer/maity", {"memory": {"provider": "keep-the-why"}})
    events = _events(migrated, "rules_changed")
    assert [e.payload for e in events] == [{"version": 2, "reason": "style"}, {"version": 3}]
    assert all(e.audience == ["all"] for e in events)
    project = _project_row(migrated, "maity")
    assert (project.rules_version, project.rules_changed_seq) == (3, events[-1].seq)
    unchanged = owner.patch("/projects/maintainer/maity", {"memory": {"provider": "keep-the-why"}})
    assert unchanged.json()["rules_version"] == 3


def test_the_rules_are_generated_per_role(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "maity", memory={"provider": "keep-the-why"})
    owner.patch("/projects/maintainer/maity", {"rules_markdown": "Commit in English."})
    rules = owner.get("/projects/maintainer/maity/rules")
    assert rules.headers["content-type"] == "text/markdown; charset=utf-8"
    assert rules.headers["ETag"] == '"2"'
    text = rules.text
    assert text.startswith("# Rules for Maity")
    assert "You own the project" in text
    assert "keep-the-why skill" in text and "Commit in English." in text
    member = flow.agent(make_client, owner, role="member")
    mine = member.get("/projects/maintainer/maity/rules").text
    assert "You are a member" in mine and "Your role is coder" in mine  # trust, then role


def test_settings_carry_the_release_checklist(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    response = owner.patch(
        "/projects/maintainer/maity",
        {"settings": {"release_checklist": ["CHANGELOG has the version"]}},
    )
    assert response.json()["settings"] == {
        "language": "en",
        "release_checklist": ["CHANGELOG has the version"],
        "onboarding": {"check_in_with": "coordinator"},
    }
    unknown = owner.patch("/projects/maintainer/maity", {"settings": {"other": 1}})
    assert unknown.headers["Maity-Error"] == "invalid"


def test_the_name_and_a_note_are_rules_inputs(owner: flow.Human, migrated: Engine) -> None:
    flow.project(owner, "maity")
    assert (
        owner.patch("/projects/maintainer/maity", {"name": "Maity hub"}).json()["rules_version"]
        == 2
    )
    assert (
        owner.patch("/projects/maintainer/maity", {"state_note": "busy week"}).json()[
            "rules_version"
        ]
        == 3
    )
    assert (
        owner.patch("/projects/maintainer/maity", {"name": "Maity hub"}).json()["rules_version"]
        == 3
    )
    assert [e.payload["version"] for e in _events(migrated, "rules_changed")] == [2, 3]
    both = owner.patch(
        "/projects/maintainer/maity", {"state": "review", "state_note": "0.1.0", "reason": "r"}
    )
    assert both.json()["rules_version"] == 4  # the state change's own event marks it
    assert len(_events(migrated, "rules_changed")) == 2
    assert "Maity hub" in owner.get("/projects/maintainer/maity/rules").text
