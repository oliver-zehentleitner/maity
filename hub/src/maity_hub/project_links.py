"""A project's own links (docs/api.md §6.11, §16.9): where its people talk and write.

`project.links` holds four keys, `issues`, `wiki`, `discussions` and `chat`, each an https URL
or absent. A value is checked as a person's `website` is (`person_links.website_problem`), with
500 characters instead of 200; the two rules are one function so they cannot drift apart. A
PATCH merges as a person's `social` does. The public page shows a link into the repository's
own path only while the repository is public, every other link as the admin set it.
"""

from __future__ import annotations

import posixpath
from typing import Any
from urllib.parse import unquote, urlsplit

from maity_hub.errors import invalid
from maity_hub.person_links import website_problem

KEYS = ("issues", "wiki", "discussions", "chat")
LINK_MAX = 500


def view(stored: dict[str, Any] | None) -> dict[str, str | None]:
    """All four keys, `null` where none is set: what the project view carries."""
    links = stored or {}
    return {key: links.get(key) for key in KEYS}


def checked(given: Any, stored: dict[str, Any] | None) -> dict[str, str]:
    """The links to store after a PATCH, or `invalid` naming each field that fails. A key
    given sets or (null, "") clears that link, a key left out stays, `null` clears all four."""
    if given is None:
        return {}
    if not isinstance(given, dict):
        raise invalid({"links": "format"})
    errors: dict[str, str] = {}
    merged = {k: v for k, v in (stored or {}).items() if k in KEYS and v}
    for key, value in given.items():
        if key not in KEYS:
            errors[f"links.{key}"] = "unknown"
        elif value is None or value == "":
            merged.pop(key, None)
        elif not isinstance(value, str):
            errors[f"links.{key}"] = "format"
        else:
            problem = website_problem(value, LINK_MAX)
            if problem is not None:
                errors[f"links.{key}"] = problem
            else:
                merged[key] = value
    if errors:
        raise invalid(errors)
    return merged


def _segments(path: str) -> list[str]:
    """A path's segments as a browser resolves them: percent-escapes decoded, `.` and `..`
    resolved, compared without case; so `x/../maity` and `%6Daity` are `maity`."""
    resolved = posixpath.normpath("/" + unquote(path))
    return [part.lower() for part in resolved.split("/") if part]


def public(
    stored: dict[str, Any] | None, repository_url: str | None, repository_public: bool | None
) -> list[str]:
    """The links a public project's page shows (§16.9), in the order of `KEYS`: one on the
    repository's host whose path lies under the repository's own path (compared without case,
    segment by segment) only while the repository is public, every other one as set."""
    shown: list[str] = []
    repo = urlsplit(repository_url) if repository_url else None
    repo_host = (repo.hostname or "").lower() if repo else ""
    repo_path = _segments(repo.path) if repo else []
    for key in KEYS:
        value = (stored or {}).get(key)
        if not value:
            continue
        link = urlsplit(value)
        inside = (
            bool(repo_host)
            and (link.hostname or "").lower() == repo_host
            and _segments(link.path)[: len(repo_path)] == repo_path
        )
        if inside and repository_public is not True:
            continue
        shown.append(value)
    return shown
