"""A project's links to issues, wiki, discussions and chat (docs/api.md §6.11, §16.9).

A project carries `links: {issues, wiki, discussions, chat}`, each null or an absolute
https URL without user part or port, whose host is a DNS name as for a person's website
(§16.9: no IP literal, no localhost), of at most 500 characters, on any host.

Set with `PATCH /projects/{owner}/{slug}` under `project:admin`, merging as `social` does:
a key given sets or (null) clears that link, a key left out stays, `links: null` clears all four.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from maity_hub.errors import invalid

KEYS = ("issues", "wiki", "discussions", "chat")
MAX_LENGTH = 500

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = rf"{_LABEL}(?:\.{_LABEL})+"
_HOST_MAX = 253


def _dns(host: str) -> bool:
    """A DNS name of the `<host>` form: at least one dot, ASCII labels, and a last label that
    is not all digits (so no IPv4 literal)."""
    return (
        len(host) <= _HOST_MAX
        and re.fullmatch(_HOST, host) is not None
        and not host.rsplit(".", 1)[1].isdigit()
    )


def link_problem(value: str) -> str | None:
    """`too_long` or `format` for a link that may not be stored, else None."""
    if len(value) > MAX_LENGTH:
        return "too_long"
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        return "format"
    try:
        parts = urlsplit(value)
        host = parts.hostname
        parts.port  # noqa: B018  (a port that is no number raises)
    except ValueError:
        return "format"
    # `netloc` is the host alone: no user part, no port, no IPv6 brackets.
    if (
        parts.scheme != "https"
        or not host
        or parts.port is not None
        or parts.username is not None
        or parts.password is not None
        or parts.netloc.lower() != host
        or not _dns(host)
    ):
        return "format"
    return None


def checked(links: Any, stored: dict[str, str] | None) -> dict[str, str]:
    """The merged links to store, or `invalid` naming every field that fails (§6.11).

    `links: null` clears all four; otherwise keys merge (key with null clears it,
    key left out stays). A non-dict is `details.fields.links: "format"`.
    """
    if links is None:
        return {}
    if not isinstance(links, dict):
        raise invalid({"links": "format"})
    merged = dict(stored or {})
    errors: dict[str, str] = {}
    for key, value in links.items():
        if key not in KEYS:
            errors[f"links.{key}"] = "unknown"
        elif value is None:
            merged.pop(key, None)
        elif not isinstance(value, str):
            errors[f"links.{key}"] = "format"
        else:
            problem = link_problem(value)
            if problem is not None:
                errors[f"links.{key}"] = problem
            else:
                merged[key] = value
    if errors:
        raise invalid(errors)
    return merged


def view(stored: dict[str, str] | None) -> dict[str, str | None]:
    """The four keys as read by everyone who reads the project: always present, null when unset."""
    stored = stored or {}
    return {key: stored.get(key) for key in KEYS}


def is_under_repository(link_url: str, repository_url: str | None) -> bool:
    """Whether `link_url` is on the repository's host (without case) and its path lies
    under the repository's own path, compared segment by segment and without case (§16.9)."""
    if not repository_url:
        return False
    try:
        repo_parts = urlsplit(repository_url)
        link_parts = urlsplit(link_url)
    except ValueError:
        return False
    if not repo_parts.hostname or not link_parts.hostname:
        return False
    if repo_parts.hostname.lower() != link_parts.hostname.lower():
        return False
    repo_segments = [s.lower() for s in repo_parts.path.strip("/").split("/") if s]
    link_segments = [s.lower() for s in link_parts.path.strip("/").split("/") if s]
    if len(link_segments) < len(repo_segments):
        return False
    return link_segments[: len(repo_segments)] == repo_segments


def link_visible_on_public_page(
    link_url: str, repository_url: str | None, repository_public: bool | None
) -> bool:
    """Whether this link is shown on the public project page (§16.9): a link into a
    repository's path on the forge only while the repository is public; other links always."""
    if is_under_repository(link_url, repository_url):
        return repository_public is True
    return True


def visible_on_public_page(
    stored: dict[str, str] | None, repository_url: str | None, repository_public: bool | None
) -> list[str]:
    """The URLs to show on the public page in canonical order, filtered by visibility."""
    if not stored:
        return []
    res: list[str] = []
    for key in KEYS:
        url = stored.get(key)
        if url and link_visible_on_public_page(url, repository_url, repository_public):
            res.append(url)
    return res
