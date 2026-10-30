"""docs/api.md §2.3: trust × role, as the contract's tables print them."""

from __future__ import annotations

import pytest

from maity_hub.scopes import (
    GOVERNANCE,
    ROLES,
    TRUSTS,
    in_admin_team,
    listed_scopes,
    scopes_for,
    tokens_of,
)

CODER = {"project:read", "tasks:write", "requests:ask", "events:post"}
# The role table: what each role grants on its own, before any trust.
ROLE_TABLE = {
    "coder": CODER,
    "reviewer": CODER | {"tasks:review", "releases:write"},
    "tester": CODER | {"tasks:test"},
    "designer": CODER,
    "ops": CODER | {"releases:write", "agents:propose", "ticker:post"},
    "writer": CODER,
    "proxy": CODER,
    "manager": CODER | {"line:lead"},  # §2.3 "The manager"
    # The security teams have the scopes of the role they are built on (§2.3).
    "red-team": CODER | {"tasks:test"},
    "blue-team": CODER,
    "purple-team": CODER | {"tasks:review", "releases:write"},
}
HUMAN_ONLY = {"project:admin", "members:admin", "events:admin", "credentials:admin"}


@pytest.mark.parametrize("kind", ["human", "agent"])
@pytest.mark.parametrize("role", [r for r in ROLES if r != "proxy"])
@pytest.mark.parametrize("trust", TRUSTS)
def test_scopes_are_trust_times_role(trust: str, role: str, kind: str) -> None:
    if trust == "guest":
        expected = {"project:read"}
    elif trust in ("owner", "admin"):
        expected = ROLE_TABLE[role] | set(GOVERNANCE)
    else:
        expected = ROLE_TABLE[role]
    if kind == "agent":
        expected -= HUMAN_ONLY
    assert set(scopes_for(trust, role, kind)) == expected


def test_a_proxy_relays_answers_and_holds_no_other_governance_scope_yet() -> None:
    """Until the owner's go per call (`Maity-On-Request`) lands, a proxy keeps what the
    single role gave it: the coder's scopes and `requests:answer`."""
    assert set(scopes_for("admin", "proxy", "agent")) == CODER | {"requests:answer"}


def test_an_agent_admin_manages_the_board_but_not_the_rules() -> None:
    scopes = scopes_for("admin", "coder", "agent")
    assert "tasks:admin" in scopes and "requests:answer" in scopes
    assert not HUMAN_ONLY & set(scopes)


def test_a_reviewer_with_trust_guest_holds_nothing_of_the_reviewer() -> None:
    assert scopes_for("guest", "reviewer", "agent") == ["project:read"]


def test_a_member_coder_has_the_resume_packets_four_scopes() -> None:
    assert scopes_for("member", "coder", "agent") == [
        "project:read",
        "tasks:write",
        "requests:ask",
        "events:post",
    ]


def test_trust_admin_never_resolves_to_a_proxy() -> None:
    assert tokens_of("admin", "coder") == {"role:coder", "trust:admin"}
    assert tokens_of("admin", "proxy") == {"role:proxy"}
    assert tokens_of("owner", "coder") == {"role:coder", "trust:owner"}
    assert not in_admin_team("admin", "proxy")
    assert in_admin_team("owner", "designer")


def test_a_proxy_agent_is_never_listed_with_members_admin() -> None:
    assert "members:admin" in listed_scopes("admin", "coder", "agent")
    assert "members:admin" not in listed_scopes("admin", "proxy", "agent")


def test_a_human_proxy_decides_no_jour_fixe_proposal() -> None:
    from types import SimpleNamespace

    from maity_hub.jourfixe.triage import may_decide

    assert may_decide(SimpleNamespace(kind="human", trust="admin", role="coder"))
    assert not may_decide(SimpleNamespace(kind="human", trust="admin", role="proxy"))
    assert not may_decide(SimpleNamespace(kind="agent", trust="admin", role="proxy"))
