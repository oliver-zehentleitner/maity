"""What a membership may do: its trust × its role (docs/api.md §2.3)."""

from __future__ import annotations

TRUSTS = ("owner", "admin", "member", "guest")
# The tokens a request, a message or a setting names (§7, §8.2): `trust:<trust>`
# for the two governing trusts, `role:<role>` for every role.
TOKEN_TRUSTS = ("owner", "admin")

_CODER = ("project:read", "tasks:write", "requests:ask", "events:post")
_TESTER = (*_CODER, "tasks:test")
_REVIEWER = (*_CODER, "tasks:review", "releases:write")
# Every built-in role of §2.3 and its scopes, in one place: the other lists below, the
# roles an invitation or a join names and the tokens a role gives are derived from it.
_ROLE_SCOPES: dict[str, tuple[str, ...]] = {
    "coder": _CODER,
    "reviewer": _REVIEWER,
    "tester": _TESTER,
    "designer": _CODER,
    "ops": (*_CODER, "releases:write", "agents:propose", "ticker:post"),
    "writer": _CODER,
    "proxy": _CODER,
    # The manager leads its line (§2.3 "The manager"): `line:lead` is no governance scope.
    "manager": (*_CODER, "line:lead"),
    # The security teams (§2.3): the scopes of the role they count as.
    "red-team": _TESTER,
    "blue-team": _CODER,
    "purple-team": _REVIEWER,
}
ROLES = tuple(_ROLE_SCOPES)
# Where the hub resolves a built-in role to find who holds done authority, whom a change
# waits for the owner's go, a substitute (§6.12), a security team counts as the role whose
# scopes it has (§2.3). A `role:` token in an address is not widened that way.
COUNTS_AS = {"red-team": "tester", "blue-team": "coder", "purple-team": "reviewer"}
# The roles below governance: what a member's own agent may hold (§3.1), and what an
# admin agent sets on the memberships it manages (§2.3 ᵃ) besides `ops`.
WORK_ROLES = tuple(role for role in ROLES if role not in ("ops", "proxy", "manager"))
# What a member brings with their own agent (§3.1): the work roles and the manager.
MEMBER_RULE_ROLES = (*WORK_ROLES, "manager")
# A change of these members waits for a human's go (§2.3 ᵃ): the roles that decide `done`.
SENSITIVE_ROLES = tuple(
    role for role in ROLES if COUNTS_AS.get(role, role) in ("reviewer", "tester")
)


def role_tokens(role: str) -> list[str]:
    """The `role:` tokens an event names to reach the holders of a built-in role (§2.3):
    the role's own and those of the security teams built on it, so that a merge or a
    report reaches `purple-team` as it reaches `reviewer`. A request or a message addressed
    to `role:reviewer` is not widened: it names the token, and uses no such list."""
    return [f"role:{role}", *(f"role:{team}" for team, base in COUNTS_AS.items() if base == role)]


def counts_as(role: str) -> str:
    """The built-in role whose scopes `role` has, for the places that resolve a role by
    name (§2.3): a security team counts as the role it is built on, any other as itself."""
    return COUNTS_AS.get(role, role)


# Trust `owner` and `admin` add these on top of the role's (§2.3).
GOVERNANCE = (
    "tasks:review",
    "tasks:test",
    "releases:write",
    "agents:propose",
    "ticker:post",
    "project:admin",
    "members:admin",
    "tasks:admin",
    "requests:answer",
    "events:admin",
    "jour_fixe:start",
    "credentials:admin",
)
# A guest reads; its notes and chat are checked where they are posted (§2.3 "Guest").
_GUEST = ("project:read",)
# Granted only to a human's membership, whatever the trust (ʰ).
HUMAN_ONLY = {"project:admin", "members:admin", "events:admin", "credentials:admin"}

SCOPES = (
    "project:read",
    "project:admin",
    "members:admin",
    "tasks:write",
    "tasks:review",
    "tasks:test",
    "tasks:admin",
    "releases:write",
    "requests:ask",
    "requests:answer",
    "events:post",
    "events:admin",
    "ticker:post",
    "jour_fixe:start",
    "credentials:admin",
    "agents:propose",
    "line:lead",
)


def _granted(trust: str, role: str) -> set[str]:
    if trust == "guest":
        return set(_GUEST)
    granted = set(_ROLE_SCOPES.get(role, _CODER))
    if role == "proxy":
        # Until the owner's go per call (`Maity-On-Request`) is in place, a proxy relays
        # answers and holds no other governance scope, as under the single role.
        return granted | {"requests:answer"}
    if trust in ("owner", "admin"):
        granted |= set(GOVERNANCE)
    return granted


def scopes_for(trust: str, role: str, kind: str) -> list[str]:
    """The scopes of a membership, in the contract's order."""
    granted = _granted(trust, role)
    return [
        scope
        for scope in SCOPES
        if scope in granted and (kind == "human" or scope not in HUMAN_ONLY)
    ]


def listed_scopes(trust: str, role: str, kind: str) -> list[str]:
    """The scopes a membership is shown to hold (§5.2): an admin agent (never a proxy) is
    listed with `members:admin`, which it holds only within ᵃ, checked per endpoint and
    never granted by `has_scope`."""
    limited = {"members:admin"} if kind == "agent" and in_admin_team(trust, role) else set()
    return [s for s in SCOPES if s in scopes_for(trust, role, kind) or s in limited]


def has_scope(trust: str, role: str, kind: str, scope: str) -> bool:
    return scope in scopes_for(trust, role, kind)


def in_admin_team(trust: str, role: str) -> bool:
    """Trust `owner` or `admin`, but never a proxy (§2.3 "The admin team")."""
    return trust in ("owner", "admin") and role != "proxy"


def token_known(token: str) -> bool:
    """`trust:owner`, `trust:admin` or `role:<role>`; any other token is unknown (§2.3)."""
    if token.startswith("trust:"):
        return token.removeprefix("trust:") in TOKEN_TRUSTS
    if token.startswith("role:"):
        return token.removeprefix("role:") in ROLES
    return False


def tokens_of(trust: str, role: str) -> set[str]:
    """The `role:` and `trust:` tokens a membership answers to (§8.2): `trust:admin`
    resolves to the admin team's admins, never a proxy."""
    tokens = {f"role:{role}"}
    if trust == "owner":
        tokens.add("trust:owner")
    if trust == "admin" and role != "proxy":
        tokens.add("trust:admin")
    return tokens
