"""docs/api.md §2.3: the role table, as the contract prints it."""

from __future__ import annotations

import pytest

from maity_hub.scopes import scopes_for

# scope: owner, admin, proxy, reviewer, member; "h" = human memberships only
TABLE = {
    "project:read": "✓✓✓✓✓",
    "project:admin": "✓h   ",
    "members:admin": "✓h   ",
    "tasks:write": "✓✓✓✓✓",
    "tasks:review": "✓✓ ✓ ",
    "tasks:admin": "✓✓   ",
    "releases:write": "✓✓ ✓ ",
    "requests:ask": "✓✓✓✓✓",
    "requests:answer": "✓✓✓  ",
    "events:post": "✓✓✓✓✓",
    "events:admin": "✓h   ",
    "ticker:post": "✓✓   ",
    "credentials:admin": "✓h   ",
    "agents:propose": "✓✓   ",
}
ROLES = ("owner", "admin", "proxy", "reviewer", "member")


@pytest.mark.parametrize("kind", ["human", "agent"])
@pytest.mark.parametrize("role", ROLES)
def test_scopes_follow_the_contract_table(role: str, kind: str) -> None:
    expected = []
    for scope, marks in TABLE.items():
        mark = marks[ROLES.index(role)]
        human_only = scope in {
            "project:admin",
            "members:admin",
            "events:admin",
            "credentials:admin",
        }
        if mark == "✓" and not (human_only and kind == "agent"):
            expected.append(scope)
        if mark == "h" and kind == "human":
            expected.append(scope)
    assert scopes_for(role, kind) == expected


def test_an_agent_admin_manages_the_board_but_not_the_rules() -> None:
    scopes = scopes_for("admin", "agent")
    assert "tasks:admin" in scopes and "requests:answer" in scopes
    assert not {"project:admin", "members:admin", "events:admin", "credentials:admin"} & set(scopes)


def test_a_member_has_the_resume_packets_four_scopes() -> None:
    assert scopes_for("member", "agent") == [
        "project:read",
        "tasks:write",
        "requests:ask",
        "events:post",
    ]
