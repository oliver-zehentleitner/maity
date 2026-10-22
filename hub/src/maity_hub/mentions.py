"""Mentions: `@handle` of an active member, resolved at write time (docs/api.md §8.6).

The hub scans a text once, when it is written, and stores what it found on the object:
`{member_id, handle, field, offset, length}` with offsets in code points. A mention is
`@` plus the longest run of `[a-z0-9-]` (a trailing `-` is not part of it), with a word
boundary before and after, outside inline code spans and fenced code blocks, naming
exactly one active membership of the project. Group words are never mentions.

Which texts are scanned and who is pinged is the caller's; this module resolves, caps
and counts pings against the writer's rate.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.errors import invalid, rate_limited

MAX_MEMBERS = 10
MAX_OCCURRENCES = 50
PINGS_PER_WINDOW, PING_WINDOW = 30, 600.0
GROUP_WORDS = frozenset({"all", "here", "everyone", "owner"})

_RUN = re.compile(r"[a-z0-9-]+")
_NOT_BEFORE = re.compile(r"[A-Za-z0-9_.@/+-]")
_NOT_AFTER = re.compile(r"[A-Za-z0-9_]")
_FENCE = re.compile(r"^(`{3,}|~{3,})")
_TICKS = re.compile(r"`+")


def _fenced(text: str) -> list[tuple[int, int]]:
    """(start, end) of every fenced code block: from an opening fence line to its closing
    fence (same character, at least as long) or the end of the text."""
    blocks = []
    position = 0
    opening: tuple[str, int, int] | None = None  # character, length, start
    for line in text.splitlines(keepends=True):
        fence = _FENCE.match(line)
        if opening is None:
            if fence:
                opening = (fence.group(1)[0], len(fence.group(1)), position)
        elif fence and fence.group(1)[0] == opening[0] and len(fence.group(1)) >= opening[1]:
            blocks.append((opening[2], position + len(line)))
            opening = None
        position += len(line)
    if opening is not None:
        blocks.append((opening[2], len(text)))
    return blocks


def _inline(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Inline code spans in text[start:end] as CommonMark pairs them: a backtick string
    closes at the next backtick string of the same length; an unmatched one is text."""
    spans = []
    runs = list(_TICKS.finditer(text, start, end))
    i = 0
    while i < len(runs):
        opener = runs[i]
        closer = next(
            (j for j in range(i + 1, len(runs)) if len(runs[j].group()) == len(opener.group())),
            None,
        )
        if closer is None:
            i += 1
            continue
        spans.append((opener.start(), runs[closer].end()))
        i = closer + 1
    return spans


def code_ranges(text: str) -> list[tuple[int, int]]:
    """Where nothing is a mention: fenced blocks, and inline spans outside them."""
    fenced = _fenced(text)
    ranges = list(fenced)
    cursor = 0
    for block_start, block_end in [*fenced, (len(text), len(text))]:
        ranges.extend(_inline(text, cursor, block_start))
        cursor = block_end
    return sorted(ranges)


def candidates(text: str) -> list[tuple[int, int, str]]:
    """(offset, length, handle) of every `@handle` the rule accepts, before the
    membership check."""
    found = []
    code = code_ranges(text)
    for at in (i for i, c in enumerate(text) if c == "@"):
        if at > 0 and _NOT_BEFORE.match(text[at - 1]):
            continue
        run = _RUN.match(text, at + 1)
        if run is None:
            continue
        handle = run.group().rstrip("-")
        if not handle:
            continue
        after = at + 1 + len(handle)
        if after < len(text) and _NOT_AFTER.match(text[after]):
            continue
        if handle in GROUP_WORDS or (handle == "role" and text[after : after + 1] == ":"):
            continue
        if any(start <= at < end for start, end in code):
            continue
        found.append((at, len(handle) + 1, handle))
    return found


def resolve(
    conn: Connection, project_id: str, text: str | None, field: str
) -> list[dict[str, Any]]:
    """The mentions of one text field, oldest offset first; `invalid` past the caps.
    A handle that names no active member, or more than one, stays text."""
    if not text:
        return []
    found = candidates(text)
    if not found:
        return []
    handles = {handle for _, _, handle in found}
    rows = conn.execute(
        select(
            t.membership.c.agent_id,
            t.membership.c.human_id,
            t.agent_profile.c.handle.label("agent_handle"),
            t.human.c.handle.label("human_handle"),
        )
        .select_from(t.membership)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .outerjoin(t.human, t.human.c.id == t.membership.c.human_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            (t.agent_profile.c.handle.in_(handles)) | (t.human.c.handle.in_(handles)),
        )
    ).all()
    members: dict[str, list[str]] = {}
    for row in rows:
        handle = row.agent_handle or row.human_handle
        members.setdefault(handle, []).append(row.agent_id or row.human_id)
    mentions = [
        {"member_id": members[h][0], "handle": h, "field": field, "offset": o, "length": n}
        for o, n, h in found
        if len(members.get(h, [])) == 1
    ]
    if len({m["member_id"] for m in mentions}) > MAX_MEMBERS or len(mentions) > MAX_OCCURRENCES:
        raise invalid({field: "too_many_mentions"}, "too many mentions in one text")
    return mentions


def members(mentions: list[dict[str, Any]]) -> list[str]:
    """The distinct members mentioned, in order of first appearance."""
    return list(dict.fromkeys(m["member_id"] for m in mentions))


class PingRate:
    """At most PINGS_PER_WINDOW pings by one membership in PING_WINDOW seconds (§8.6).
    In-process, like the other limits of one replica."""

    def __init__(self, limit: int = PINGS_PER_WINDOW, window: float = PING_WINDOW) -> None:
        self._limit, self._window = limit, window
        self._sent: dict[int, deque[float]] = {}
        self._lock = threading.Lock()

    def charge(self, membership_id: int, count: int) -> None:
        """Count `count` pings, or refuse the whole write with `rate_limited`."""
        if count <= 0:
            return
        now = time.monotonic()
        with self._lock:
            sent = self._sent.setdefault(membership_id, deque())
            while sent and sent[0] <= now - self._window:
                sent.popleft()
            if len(sent) + count > self._limit:
                oldest = sent[0] if sent else now
                raise rate_limited(max(1, int(oldest + self._window - now) + 1))
            sent.extend([now] * count)

    def reset(self) -> None:
        with self._lock:
            self._sent.clear()


PINGS = PingRate()
