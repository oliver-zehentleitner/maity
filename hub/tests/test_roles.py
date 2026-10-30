"""docs/api.md §2.3: every built-in role is in one list, with its scopes, and every place
that names roles derives from it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import events, scopes
from tests import flow
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
