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
    "credentials:admin": {"owner", "admin"},
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


def has_scope(role: str, kind: str, scope: str) -> bool:
    return scope in scopes_for(role, kind)
