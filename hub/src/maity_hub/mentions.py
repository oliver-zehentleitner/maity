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
from bisect import bisect_right
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.errors import invalid, rate_limited
from maity_hub.events import on_rollback
from maity_hub.ratelimit import Limiter

MAX_MEMBERS = 10
MAX_OCCURRENCES = 50
PINGS_PER_WINDOW, PING_WINDOW = 30, 600.0
GROUP_WORDS = frozenset({"all", "here", "everyone", "owner"})

_RUN = re.compile(r"[a-z0-9-]+")
_NOT_BEFORE = re.compile(r"[A-Za-z0-9_.@/+-]")
_NOT_AFTER = re.compile(r"[A-Za-z0-9_]")
_FENCE = re.compile(r"^(`{3,}|~{3,})")
_TICKS = re.compile(r"`+")
_LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")


def _fenced(text: str) -> list[tuple[int, int]]:
    """(start, end) of every fenced code block: from an opening fence line to its closing
    fence (same character, at least as long) or the end of the text."""
    blocks = []
    position = 0
    opening: tuple[str, int, int] | None = None  # character, length, start
    # Lines end at `\n` (a `\r\n` keeps its `\r`) and nowhere else: `str.splitlines`
    # would also break at \x0b, \x85 or U+2028, which are no line ends in Markdown.
    for line in _LINE.findall(text):
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
    by_length: dict[int, list[int]] = {}
    for index, run in enumerate(runs):
        by_length.setdefault(len(run.group()), []).append(index)
    i = 0
    while i < len(runs):
        same = by_length[len(runs[i].group())]
        after = bisect_right(same, i)
        if after == len(same):  # no closer of this length: the run is text
            i += 1
            continue
        closer = same[after]
        spans.append((runs[i].start(), runs[closer].end()))
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
    code = code_ranges(text)  # sorted and disjoint
    starts = [start for start, _ in code]
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
        inside = bisect_right(starts, at) - 1
        if inside >= 0 and at < code[inside][1]:
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


# At most PINGS_PER_WINDOW pings by one membership in PING_WINDOW seconds (§8.6).
# In-process, like the other limits of one replica.
PINGS = Limiter(PINGS_PER_WINDOW, PING_WINDOW)


def charge(conn: Connection, membership_id: int, count: int) -> None:
    """Count `count` pings of one write, or refuse the whole write with `rate_limited`
    and the seconds until all of them fit. A write that does not commit (a retry, a
    later error) gives them back."""
    if count <= 0:
        return
    key = str(membership_id)
    wait = PINGS.take(key, count)
    if wait:
        raise rate_limited(wait)
    on_rollback(conn, lambda: PINGS.give_back(key, count))
