"""What a role may do (docs/api.md §2.3)."""

from __future__ import annotations

ROLES = ("owner", "admin", "proxy", "reviewer", "member")

_ALL = set(ROLES)
_GRANTS: dict[str, set[str]] = {
    "project:read": _ALL,
    "project:admin": {"owner", "admin"},
    "members:admin": {"owner", "admin"},
    "tasks:write": _ALL,
    "tasks:review": {"owner", "admin", "reviewer"},
    "tasks:admin": {"owner", "admin"},
    "releases:write": {"owner", "admin", "reviewer"},
    "requests:ask": _ALL,
    "requests:answer": {"owner", "admin", "proxy"},
    "events:post": _ALL,
    "events:admin": {"owner", "admin"},
    # A manual ticker post (§17.6); agents included.
    "ticker:post": {"owner", "admin"},
    # Start a jour fixe round now (§20.1); agents included: it changes no policy.
    "jour_fixe:start": {"owner", "admin"},
    "credentials:admin": {"owner", "admin"},
    # Propose placements and stop, start, restart or delete them (§15.6); agents included.
    "agents:propose": {"owner", "admin"},
}
# Granted only to a human's membership, whatever the role.
HUMAN_ONLY = {"project:admin", "members:admin", "events:admin", "credentials:admin"}

SCOPES = tuple(_GRANTS)


def scopes_for(role: str, kind: str) -> list[str]:
    """The scopes of a membership, in the contract's order."""
    return [
        scope
        for scope in SCOPES
        if role in _GRANTS[scope] and (kind == "human" or scope not in HUMAN_ONLY)
    ]


# Held by an agent with `admin` only within §2.3 ᵃ, checked per endpoint: listed for it,
# never granted by `has_scope`.
LIMITED_FOR_AGENTS = {"admin": {"members:admin"}}


def listed_scopes(role: str, kind: str) -> list[str]:
    """The scopes a membership is shown to hold (§5.2), the limited ones included."""
    limited = LIMITED_FOR_AGENTS.get(role, set()) if kind == "agent" else set()
    return [s for s in SCOPES if s in scopes_for(role, kind) or s in limited]


def has_scope(role: str, kind: str, scope: str) -> bool:
    return scope in scopes_for(role, kind)
