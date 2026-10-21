"""The forge the probe reads (docs/api.md §11): which host, and whether a token is held.

The token comes from the operator's environment only and is set here once at
startup; nothing a project member sets can change where it is sent.
"""

from __future__ import annotations

HOSTS = {"github.com": "github"}  # host -> forge kind
_token: str | None = None


def configure(token: str | None) -> None:
    global _token
    _token = token or None


def token() -> str | None:
    return _token


def kind_of(url: str | None) -> str | None:
    if not url:
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    return HOSTS.get(host)


def configured_for(url: str | None) -> bool:
    """Whether the hub can observe this repository: a known forge and a token for it."""
    return kind_of(url) == "github" and _token is not None
