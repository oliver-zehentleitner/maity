"""The paths of the public host (docs/api.md §16.11): which ones the hub answers itself,
which first segments no handle may take, and the `next` a login may carry.

The reserved list is written here once. `tests/test_paths.py` compares it with the list in
§16.11, so the contract and the code cannot drift apart; the dashboard keeps a copy of its
own that its tests compare with the same section.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote_to_bytes

# A human's or an organisation's handle is never one of these (§16.11), now or later.
# `components`, `health` and `imprint` name no route today and are held back so that they
# stay free for one.
RESERVED_FIRST = frozenset(
    {
        "account", "admin", "agents", "all", "api", "assets", "badge", "chats", "components",
        "explore", "for", "health", "impressum", "imprint", "inbox", "invite", "join", "login",
        "mail", "new", "notifications", "observe", "privacy", "register", "requests", "runners",
        "settings", "sign-in", "terms",
    }
)  # fmt: skip

# Read in a by-line these speak for the hub or for a reader's own human, in every scope: an agent
# named `hub` reads as well as a human named so. They name no path, and those who hold one already
# keep it, so the migration's check of the reserved words does not ask for them.
MISLEADING_HANDLES = frozenset({"hub", "human", "maity", "system"})

# The load-test seed names its accounts `lt-<n>` and purge deletes them (§16.11). Not a member of
# `RESERVED_FIRST`: that set is path words, also read by the robots list, the join host and the
# migration's holder check. An account that already holds one keeps it, and may take that
# alias back: the reservation stops a new claimant, not the id's own old name.
LOADTEST_HANDLE = re.compile(r"lt-[0-9]+")


def handle_reserved(handle: str, *, of_agent: bool = False) -> bool:
    """Whether nobody may take `handle`: the one check of every path that gives one (§6.25). An
    agent's handle is no first segment of a path, so only the misleading words hold for it.
    `lt-<digits>` is reserved for a person or an organisation, for the load-test accounts."""
    if handle in MISLEADING_HANDLES:
        return True
    if of_agent:
        return False
    return handle in RESERVED_FIRST or LOADTEST_HANDLE.fullmatch(handle) is not None


# The views of a project in the dashboard (§16.11): `/<owner>/<slug>/<view>…`. A slug is never
# one of them, so that `/<owner>/<word>` stays free for pages of an owner's own. `members` is
# no view since the Team view moved to `team`, and stays reserved (the maintainer, 2026-11-10).
# `placements` is the tab "Where they run" (tsk-3s3eb6bsp15n, context/routing.md).
PROJECT_VIEWS = frozenset(
    {
        "agents", "board", "chat", "contract", "events", "inbox", "jour-fixe", "members",
        "memory", "message", "messages", "organisation", "overview", "placements", "runners",
        "settings", "tasks", "team", "ticker", "why",
    }
)  # fmt: skip

# The first segments the hub answers itself (§16.11, "Hub paths"). A path under one of them
# that names nothing is `not_found`, never the app shell. `r` and the files for crawlers
# are not handles anyway; the legal pages are the reserved words `impressum`, `privacy`,
# `terms`.
HUB_FIRST = frozenset(
    {"api", "assets", "join", "r", "mail", "badge", "impressum", "privacy", "terms"}
)
_HUB_FILE = re.compile(r"/(?:robots\.txt|sitemap\.xml|sitemap-\d+\.xml)\Z")

# The reserved first words that name no route yet (§16.11): an address under one of them can never
# be a page, so it is `404` with the shell, not the shell's `200`.
NO_ROUTE_FIRST = frozenset({"components", "health", "imprint"})

# The depth of the deepest route, `/<owner>/<slug>/team/<id>/sessions/<instance>` (§16.11). A
# path below a project's Why is never too deep: a topic's file path goes into it segment by
# segment. A release that adds a deeper route raises this number in the same change.
DEEPEST = 6

_HANDLE = re.compile(r"[a-z0-9][a-z0-9-]{1,30}")  # §6.24


def _segment(raw: str) -> str:
    """One segment as the dashboard reads it: percent-decoded, or as sent where an escape does
    not decode (§16.11)."""
    try:
        return unquote_to_bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        return raw


def never_a_page(raw_path: str) -> bool:
    """Whether the shell answers this path with `404`: an address that can never be a page
    (§16.11). `raw_path` is the path as sent, split at its slashes before a segment is decoded,
    so an encoded slash stays in its segment. The path's words alone decide it, never a lookup,
    so the status tells nobody whether a name exists; a handle- or project-shaped address stays
    the shell's `200`. Not for a hub path."""
    segments = [_segment(part) for part in raw_path.split("/") if part]
    if not segments:
        return False
    first = segments[0]
    if not _HANDLE.fullmatch(first) or first in NO_ROUTE_FIRST:
        return True
    # Below the dashboard's own first words the hub routes nothing: only the depth counts there.
    shaped = first not in RESERVED_FIRST
    if shaped and len(segments) == 2 and segments[1] == "agents":
        return True  # `/<handle>/agents` names nothing (§16.9)
    if shaped and len(segments) >= 3 and segments[1] != "agents":
        if segments[2] not in PROJECT_VIEWS - {"members"}:
            return True  # a project's view word that is no view
        if segments[2] == "why":
            return False  # a topic's file path: no bound on the depth
    return len(segments) > DEEPEST


NEXT_MAX = 512
_NEXT_BAD = re.compile(r"[\\\s#\x00-\x1f\x7f]|//")


def first_segment(path: str) -> str:
    return path.lstrip("/").partition("/")[0]


def is_hub_path(path: str) -> bool:
    """Whether the hub answers `path` itself: it is never the app shell."""
    return first_segment(path) in HUB_FIRST or bool(_HUB_FILE.fullmatch(path))


def safe_next(value: str | None) -> str:
    """A login's `next` (§2.6.5): a path on the public host that starts with `/`, at most
    512 characters, without a backslash, whitespace, a control or format character, a `#`
    or `//`, whose first segment is not a hub path. Anything else becomes `/`, silently."""
    if (
        not value
        or not value.startswith("/")
        or len(value) > NEXT_MAX
        or _NEXT_BAD.search(value)
        # C1 controls, bidi overrides, zero-width and other format characters.
        or any(unicodedata.category(c) in ("Cc", "Cf") for c in value)
        or is_hub_path(value.partition("?")[0])
    ):
        return "/"
    return value
