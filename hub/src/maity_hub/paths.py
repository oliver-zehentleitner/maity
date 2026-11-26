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

# A new person or organisation may not take a handle this short or one of `PRODUCT_WORDS`
# (§16.11), so that `/<word>` stays free for the product's own pages (the maintainer,
# 2026-11-25, tsk-3ykgt3t9jd57). Like `lt-<n>` these are no members of `RESERVED_FIRST`: they
# name no route, so the robots list, the join host, the dashboard and `never_a_page` read them
# as any handle, and whoever holds one already keeps it, its page and its alias. A word that
# gets a page of ours later moves to `RESERVED_FIRST` in that change, which deals with its holder.
# `owner` and `owners` stay free: every scripted hub, harness and doc creates `owner`, and
# `maity-hub owner create`, the operator's command, is held to the words but not to the length
# (the maintainer, 2026-11-25, req-x0efaacq8zyh: handles are 6 characters at least).
SHORT_HANDLE = 5  # §6.24 allows 2 to 31 characters
PRODUCT_WORDS = frozenset(
    {
        "about", "account-recovery", "accounts", "administrator", "administrators", "admins",
        "ads", "affiliate", "affiliates", "agent", "analytics", "announcements", "apps",
        "archive", "area", "areas", "attachment", "attachments", "auth", "authorize", "billing",
        "blog", "blogs", "board", "boards", "bot", "bots", "brand", "branding", "briefing",
        "briefings", "business", "callback", "card", "cards", "career", "careers", "cart",
        "changelog", "chat", "checkout", "claim", "cli", "coder", "coders", "commit",
        "community", "compare", "compliance", "confirm", "contact", "contacts", "context",
        "contract", "contribute", "contribution", "conversation", "conversations", "cookies",
        "copyright", "customer", "customers", "dashboard", "default", "demo", "deploy",
        "design", "designer", "dev", "developer", "developers", "discord", "discuss",
        "discussions", "doc", "docs", "documentation", "domain", "domains", "donate",
        "download", "downloads", "edit", "email", "enterprise", "event", "events", "example",
        "examples", "expert", "faq", "faqs", "feature", "features", "feed", "feedback", "file",
        "files", "fork", "forks", "forum", "forums", "gdpr", "github", "gitlab", "guide",
        "guides", "help", "home", "hooks", "hosting", "info", "instance", "instances",
        "integration", "integrations", "investors", "invitation", "invitations", "issue",
        "issues", "job", "jobs", "joins", "jour-fixe", "jourfixe", "keep-the-why",
        "knowledge-base", "knowledgebase", "ktw", "landing", "learn", "legal", "licence",
        "licences", "license", "licenses", "link", "links", "list", "lists", "log-in",
        "log-out", "logout", "manager", "marketplace", "me", "media", "member", "members",
        "memory", "mention", "mentions", "merge", "message", "messages", "moderator",
        "moderators", "news", "newsletter", "note", "notes", "notification", "oauth",
        "official", "onboarding", "org", "organisation", "organisations", "organization",
        "organizations", "orgs", "outsider", "outsiders", "overview", "page", "pages",
        "partner", "partners", "password", "payment", "payments", "placement", "placements",
        "plan", "plans", "platform", "policies", "policy", "popular", "pr", "press", "pricing",
        "pro", "product", "products", "profile", "profiles", "project", "projects", "proxy",
        "prs", "public", "pull", "pulls", "readme", "release", "releases", "repo", "report",
        "reports", "repos", "repositories", "repository", "request", "reset", "review",
        "reviewer", "reviewers", "reviews", "roadmap", "role", "roles", "root", "rss",
        "runner", "sales", "sdk", "search", "security", "server", "service", "services",
        "setup", "shop", "showcase", "sign-out", "sign-up", "signin", "signout", "signup",
        "site", "sitemap", "sites", "soul", "source", "sponsor", "sponsors", "staff", "stats",
        "status", "steward", "store", "stream", "subscribe", "subscription", "subscriptions",
        "support", "takeover", "task", "tasks", "team", "teams", "terms-of-service",
        "terms-of-use", "test", "tester", "testers", "testing", "thread", "threads", "ticker",
        "ticket", "tickets", "tos", "tour", "tracker", "trackers", "trending", "trust",
        "tutorial", "tutorials", "unsubscribe", "update", "updates", "upgrade", "upload",
        "uploads", "user", "users", "verify", "wait", "webhook", "webhooks", "welcome", "why",
        "wiki", "writer", "www",
    }
)  # fmt: skip


def kept_from_new_claims(handle: str, *, by_operator: bool = False) -> bool:
    """Whether `handle` is reserved for a new person or organisation only (§16.11): of the form
    `lt-<digits>`, at most `SHORT_HANDLE` characters, or one of `PRODUCT_WORDS`. Whoever holds
    one already keeps it and may take it back as their alias (§6.24). `by_operator`: for
    `maity-hub owner create`, which the length does not bind."""
    return (
        LOADTEST_HANDLE.fullmatch(handle) is not None
        or (not by_operator and len(handle) <= SHORT_HANDLE)
        or handle in PRODUCT_WORDS
    )


def handle_reserved(handle: str, *, of_agent: bool = False, by_operator: bool = False) -> bool:
    """Whether nobody may take `handle`: the one check of every path that gives one (§6.25). An
    agent's handle is no first segment of a path, so only the misleading words hold for it.
    For a person or an organisation the first segments hold, and `kept_from_new_claims`;
    `by_operator` (`maity-hub owner create`) is not held to the length."""
    if handle in MISLEADING_HANDLES:
        return True
    if of_agent:
        return False
    return handle in RESERVED_FIRST or kept_from_new_claims(handle, by_operator=by_operator)


# The views of a project in the dashboard (§16.11): `/<owner>/<slug>/<view>…`. A slug is never
# one of them, so that `/<owner>/<word>` stays free for pages of an owner's own. `members` is
# no view since the Team view moved to `team`, and stays reserved (the maintainer, 2026-11-10);
# `runners` likewise since the project's runners became the Settings tab `settings/runners`
# (tsk-ert2k23kr5m4, no redirect).
# `placements` is the tab "Where they run" (tsk-3s3eb6bsp15n, context/routing.md).
PROJECT_VIEWS = frozenset(
    {
        "agents", "board", "chat", "contract", "events", "inbox", "jour-fixe", "members",
        "memory", "message", "messages", "organisation", "overview", "placements", "runners",
        "settings", "tasks", "team", "ticker", "why",
    }
)  # fmt: skip

# Reserved as slugs, but no view any more: `404` with the shell, as any word that is no view.
RESERVED_NO_VIEW = frozenset({"members", "runners"})

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


_NO_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _segment(raw: str) -> str:
    """One segment as the dashboard reads it: percent-decoded, or as sent where an escape does
    not decode (§16.11). Strict, like the dashboard's `decodeURIComponent`: any `%` that starts
    no escape leaves the whole segment as sent, not only that escape."""
    if _NO_ESCAPE.search(raw):
        return raw
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
        if segments[2] not in PROJECT_VIEWS - RESERVED_NO_VIEW:
            return True  # a project's view word that is no view
        if segments[2] == "why":
            return False  # a topic's file path: no bound on the depth
    return len(segments) > DEEPEST


def is_invitation(raw_path: str) -> bool:
    """Whether the dashboard draws an invitation at this path, `/invite/{token}` (§16.11):
    read as the dashboard reads it (`web/js/app.js`, the no-referrer check in `render()`),
    empty segments skipped and the first one decoded, so `//invite/{token}` and
    `/%69nvite/{token}` are invitations too. `raw_path` as for `never_a_page`."""
    segments = [part for part in raw_path.split("/") if part]
    return len(segments) > 1 and _segment(segments[0]) == "invite"


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
