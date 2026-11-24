"""docs/api.md §2.3: trust × role, as the contract's tables print them."""

from __future__ import annotations

import pytest

from maity_hub.scopes import (
    GOVERNANCE,
    OUTSIDE,
    ROLES,
    TRUSTS,
    has_scope,
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
    "expert": {"project:read", "events:post"},  # §2.3 "The expert"
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


def test_a_proxy_relays_answers_and_holds_no_other_governance_scope_of_its_own() -> None:
    """The coder's scopes and `requests:answer`; the owner's go opens another scope for one
    call (`Maity-On-Request`, tests/test_proxy_go.py), never in this list."""
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
    assert tokens_of("admin", "coder", "coder") == {"role:coder", "trust:admin"}
    assert tokens_of("admin", "proxy", "proxy") == {"role:proxy"}
    assert tokens_of("owner", "coder", "coder") == {"role:coder", "trust:owner"}
    assert not in_admin_team("admin", "proxy")
    assert in_admin_team("owner", "designer")


def test_a_proxy_agent_is_never_listed_with_members_admin() -> None:
    assert "members:admin" in listed_scopes("admin", "coder", "agent")
    assert "members:admin" not in listed_scopes("admin", "proxy", "agent")


def _known(trust: str, role: str) -> set[str]:
    """What a known trust grants with a role, as the contract's tables print it (§2.3)."""
    if trust == "guest":
        return {"project:read"}
    if trust == OUTSIDE:
        return ROLE_TABLE[role] - {"line:lead"}
    if role == "proxy":
        return CODER | {"requests:answer"}
    if trust in ("owner", "admin"):
        return ROLE_TABLE[role] | set(GOVERNANCE)
    return ROLE_TABLE[role]


@pytest.mark.parametrize("kind", ["human", "agent"])
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("trust", [*TRUSTS, OUTSIDE])
def test_each_known_trust_gives_its_role_the_scopes_the_tables_print(
    trust: str, role: str, kind: str
) -> None:
    expected = _known(trust, role) - (HUMAN_ONLY if kind == "agent" else set())
    assert set(scopes_for(trust, role, kind)) == expected


@pytest.mark.parametrize("kind", ["human", "agent"])
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("trust", [None, "", "superuser", "Owner", "trust:owner"])
def test_a_membership_whose_trust_the_hub_does_not_know_gets_no_scopes(
    trust: str | None, role: str, kind: str
) -> None:
    assert scopes_for(trust, role, kind) == []  # type: ignore[arg-type]
    assert listed_scopes(trust, role, kind) == []  # type: ignore[arg-type]
    assert not has_scope(trust, role, kind, "project:read")  # type: ignore[arg-type]
    assert not has_scope(trust, role, kind, "tasks:write")  # type: ignore[arg-type]


def test_an_unknown_role_is_still_the_callers_fault_whatever_the_trust() -> None:
    for trust in (None, "superuser", "member"):
        with pytest.raises(ValueError):
            scopes_for(trust, "outsider", "human")  # type: ignore[arg-type]


def test_a_human_proxy_decides_no_jour_fixe_proposal() -> None:
    from types import SimpleNamespace

    from maity_hub.jourfixe.triage import may_decide

    round_row = SimpleNamespace(config={"circle": "all"})
    for kind, role, decides in (("human", "coder", True), ("human", "proxy", False)):
        mine = SimpleNamespace(kind=kind, trust="admin", role=role)
        assert may_decide(None, round_row, mine) is decides  # type: ignore[arg-type]
    mine = SimpleNamespace(kind="agent", trust="admin", role="proxy")
    assert not may_decide(None, round_row, mine)  # type: ignore[arg-type]
