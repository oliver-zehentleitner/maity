"""docs/api.md §2.3: every built-in role is in one list, with its scopes, and every place
that names roles derives from it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events, merged, scopes
from maity_hub import tables as t
from maity_hub.views import principal_id
from tests import factory, flow
from tests.conftest import ClientFactory

CONTRACT_ROLES = (
    "coder",
    "reviewer",
    "tester",
    "designer",
    "ops",
    "writer",
    "proxy",
    "manager",
    "red-team",
    "blue-team",
    "purple-team",
)
CODER = {"project:read", "tasks:write", "requests:ask", "events:post"}
TESTER = {*CODER, "tasks:test"}
REVIEWER = {*CODER, "tasks:review", "releases:write"}
# The scopes of a member of each role, as the table of §2.3 gives them.
SCOPES = {
    "coder": CODER,
    "reviewer": REVIEWER,
    "tester": TESTER,
    "designer": CODER,
    "writer": CODER,
    "ops": {*CODER, "releases:write", "agents:propose", "ticker:post"},
    "proxy": {*CODER, "requests:answer"},
    "manager": {*CODER, "line:lead"},
    "red-team": TESTER,
    "blue-team": CODER,
    "purple-team": REVIEWER,
}


def test_the_list_holds_every_role_of_the_contract() -> None:
    assert set(scopes.ROLES) == set(CONTRACT_ROLES)
    assert len(scopes.ROLES) == len(set(scopes.ROLES))


@pytest.mark.parametrize("role", CONTRACT_ROLES)
def test_a_member_of_each_role_has_the_scopes_of_its_row(role: str) -> None:
    assert set(scopes.scopes_for("member", role, "agent")) == SCOPES[role]
    assert scopes.token_known(f"role:{role}")
    assert scopes.tokens_of("member", role) == {f"role:{role}"}  # never widened to its base
    assert scopes.has_scope("member", role, "agent", "tasks:review") == (
        role in ("reviewer", "purple-team")
    )
    assert scopes.has_scope("member", role, "agent", "tasks:test") == (
        role in ("tester", "red-team")
    )


def test_the_derived_lists() -> None:
    assert scopes.WORK_ROLES == (
        "coder",
        "reviewer",
        "tester",
        "designer",
        "writer",
        "red-team",
        "blue-team",
        "purple-team",
    )
    assert (*scopes.WORK_ROLES, "manager") == scopes.MEMBER_RULE_ROLES
    assert set(scopes.SENSITIVE_ROLES) == {"reviewer", "tester", "red-team", "purple-team"}
    assert {r: scopes.counts_as(r) for r in scopes.ROLES if scopes.counts_as(r) != r} == {
        "red-team": "tester",
        "blue-team": "coder",
        "purple-team": "reviewer",
    }


@pytest.mark.parametrize("role", CONTRACT_ROLES)
def test_an_invitation_names_each_role(
    make_client: ClientFactory, migrated: Engine, role: str
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    trust = "admin" if role == "proxy" else "member"
    made = owner.post("/projects/maintainer/maity/invitations", {"role": role, "trust": trust})
    assert made.status_code == 201, made.text
    assert (made.json()["trust"], made.json()["role"]) == (trust, role)
    refused = owner.post("/projects/maintainer/maity/invitations", {"role": f"{role}-x"})
    assert refused.status_code == 400, refused.text


@pytest.mark.parametrize("role", [r for r in CONTRACT_ROLES if r != "proxy"])
def test_a_join_names_each_role(make_client: ClientFactory, migrated: Engine, role: str) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    body: dict[str, Any] = {
        "agent": {"handle": "bot", "display_name": "Bot"},
        "trust": "member",
        "role": role,
    }
    made = owner.post("/projects/maintainer/maity/joins", body)
    assert made.status_code == 201, made.text


@pytest.mark.parametrize(
    ("role", "authority", "wakes"),
    [
        ("reviewer", "reviewer", True),
        ("purple-team", "reviewer", True),
        ("tester", "reviewer", False),
        ("red-team", "reviewer", False),
        ("blue-team", "reviewer", False),
        ("tester", "tester", True),
        ("red-team", "tester", True),
        ("purple-team", "tester", False),
        ("red-team", "reviewer_and_tester", True),
        ("purple-team", "reviewer_and_tester", True),
        ("blue-team", "reviewer_and_tester", False),
        ("coder", "reviewer_and_tester", False),
    ],
)
def test_a_merge_wakes_the_holders_of_the_done_authority_a_security_team_counts_as_its_base(
    role: str, authority: str, wakes: bool
) -> None:
    row = SimpleNamespace(payload={"done_authority": authority}, audience=[], wakes=None)
    member = SimpleNamespace(trust="member", role=role)
    assert events._merge_wakes(row, member, "agt-x", None) is wakes


@pytest.mark.parametrize(
    ("authority", "woken"),
    [
        ("reviewer", {"reviewer", "purple-team"}),
        ("tester", {"tester", "red-team"}),
        ("reviewer_and_tester", {"reviewer", "purple-team", "tester", "red-team"}),
    ],
)
def test_a_merge_and_a_report_reach_the_security_team_built_on_the_role(
    migrated: Engine, authority: str, woken: set[str]
) -> None:
    """End to end through `read_waking`: the audience of a merge and of a report names the
    role and the teams built on it, so the member is let read the event and then woken; a
    team built on another role, and a coder, are not."""
    human = factory.human(migrated)
    project_id = factory.project(migrated, owner_id=human)
    roles = ("reviewer", "purple-team", "tester", "red-team", "blue-team", "coder")
    held = {r: factory.agent(migrated, project_id, human, r) for r in roles}
    with events.transaction(migrated) as conn:
        events.emit(
            conn,
            project_id,
            "task_merged",
            merged.AUTHORITY[authority],
            {"done_authority": authority, "closed": False},
        )
        events.emit(
            conn,
            project_id,
            "task_reported",
            [*scopes.role_tokens("reviewer"), "trust:admin"],
            {},
        )
    seen: dict[str, set[str]] = {}
    with migrated.connect() as conn:
        for role, agent in held.items():
            row = conn.execute(
                select(t.membership).where(t.membership.c.id == agent.membership_id)
            ).one()
            who = principal_id(conn, agent.membership_id)
            assert who is not None
            rows, _ = events.read_waking(conn, project_id, row, who, 0, 50)
            seen[role] = {r.kind for r in rows}
    for role in roles:
        merge_wakes = "task_merged" in seen[role]
        assert merge_wakes == (role in woken), (role, authority, seen[role])
        assert ("task_reported" in seen[role]) == (role in ("reviewer", "purple-team")), role
