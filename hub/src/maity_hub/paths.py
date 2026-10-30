"""The paths of the public host (docs/api.md §16.11): which ones the hub answers itself,
which first segments no handle may take, and the `next` a login may carry.

The reserved list is written here once. `tests/test_paths.py` compares it with the list in
§16.11, so the contract and the code cannot drift apart; the dashboard keeps a copy of its
own that its tests compare with the same section.
"""

from __future__ import annotations

import re
import unicodedata

# A human's or an organisation's handle is never one of these (§16.11), now or later.
# `components`, `health` and `imprint` name no route today and are held back so that they
# stay free for one.
RESERVED_FIRST = frozenset(
    {
        "account", "admin", "agents", "all", "api", "assets", "badge", "chats", "components",
        "explore", "health", "impressum", "imprint", "inbox", "invite", "join", "login", "mail",
        "new", "notifications", "observe", "privacy", "register", "requests", "runners",
        "settings", "sign-in", "terms",
    }
)  # fmt: skip

# The views of a project in the dashboard (§16.11): `/<owner>/<slug>/<view>…`. A slug is never
# one of them, so that `/<owner>/<word>` stays free for pages of an owner's own.
PROJECT_VIEWS = frozenset(
    {
        "agents", "board", "chat", "inbox", "jour-fixe", "members", "message", "messages",
        "my-settings", "organisation", "overview", "runners", "settings", "swarm", "tasks",
        "ticker", "why",
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
