"""Mentions: `@handle` of an active member, resolved at write time (docs/api.md §8.6).

The hub scans a text once, when it is written, and stores what it found on the object:
`{member_id, handle, name, instance, field, offset, length}` with offsets in code
points. A mention is `@` plus the longest run of `[a-z0-9-]` (a trailing `-` is not
part of it), or an agent's global name `@owner/handle` (§6.3), with a word boundary
before and after, outside inline code spans and fenced code blocks, naming an active
membership of the project. A short handle two active agent members share is refused,
naming the global names it could mean; a human with that handle comes first. Group
words are never mentions.

Which texts are scanned and who is pinged is the caller's; this module resolves, caps
and counts pings against the writer's rate.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable
from typing import Any, NamedTuple

from sqlalchemy import Connection, or_, select
from sqlalchemy.orm import aliased

from maity_hub import instances
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.events import on_rollback
from maity_hub.ratelimit import Limiter

MAX_MEMBERS = 10
MAX_OCCURRENCES = 50
PINGS_PER_WINDOW, PING_WINDOW = 30, 600.0
GROUP_WORDS = frozenset({"all", "here", "everyone", "owner"})

_RUN = re.compile(r"[a-z0-9-]+")
_SUFFIX = re.compile(r"#([2-9a-hjkmnp-z]{4,5})")  # an instance id (§6.17)
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


class Candidate(NamedTuple):
    offset: int
    length: int  # the `@` and the name
    handle: str
    owner: str | None  # the owner's handle in a global name `@owner/handle`, else None
    instance: str | None = None  # `#id` directly after the name: one instance (§6.17)


def candidates(text: str) -> list[Candidate]:
    """Every `@handle` and `@owner/handle` the rule accepts, before the membership
    check, each with an optional `#id`. A run followed by `/` and a second run is the
    global name, judged whole: a boundary missing after it makes it no mention at all,
    never a short one. An instance id directly after the name, itself followed by a
    boundary, belongs to the candidate; a `#` followed by anything else is a boundary."""
    found = []
    code = code_ranges(text)  # sorted and disjoint
    starts = [start for start, _ in code]
    for at in (i for i, c in enumerate(text) if c == "@"):
        if at > 0 and _NOT_BEFORE.match(text[at - 1]):
            continue
        run = _RUN.match(text, at + 1)
        if run is None:
            continue
        owner: str | None = None
        handle = run.group().rstrip("-")
        second = _RUN.match(text, run.end() + 1) if text[run.end() : run.end() + 1] == "/" else None
        if second is not None and second.group().rstrip("-"):
            owner, handle = run.group(), second.group().rstrip("-")
            after = second.start() + len(handle)
        else:
            after = at + 1 + len(handle)
        if not handle:
            continue
        instance: str | None = None
        suffix = _SUFFIX.match(text, after)
        if suffix is not None and not (
            suffix.end() < len(text) and _NOT_AFTER.match(text[suffix.end()])
        ):
            instance, after = suffix.group(1), suffix.end()
        if after < len(text) and _NOT_AFTER.match(text[after]):
            continue
        if owner is None and (
            handle in GROUP_WORDS
            or (handle in ("role", "trust") and text[after : after + 1] == ":")
        ):
            continue
        inside = bisect_right(starts, at) - 1
        if inside >= 0 and at < code[inside][1]:
            continue
        found.append(Candidate(at, after - at, handle, owner, instance))
    return found


def global_name(owner_handle: str, handle: str) -> str:
    """An agent's name across owners and projects (§6.3); computed, never stored."""
    return f"{owner_handle}/{handle}"


def resolve(
    conn: Connection,
    project_id: str,
    text: str | None,
    field: str,
    *,
    among: set[str] | None = None,
) -> list[dict[str, Any]]:
    """The mentions of one text field, oldest offset first; `invalid` past the caps and
    for a short handle two active members share (`ambiguous_mention`, with the global
    names it could mean in `details.mentions`). `among` narrows the members a mention
    may name (a group chat's participants); anyone else's handle stays text, as an
    unknown one does."""
    if not text:
        return []
    found = candidates(text)
    if not found:
        return []
    from maity_hub import handles as handle_book  # a module of its own; not at import

    owner = t.human.alias("owner")
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.agent_id,
            t.membership.c.human_id,
            t.agent_profile.c.handle.label("agent_handle"),
            t.agent_profile.c.owner_id.label("owner_id"),
            t.human.c.handle.label("human_handle"),
            owner.c.handle.label("owner_handle"),
        )
        .select_from(t.membership)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .outerjoin(owner, owner.c.id == t.agent_profile.c.owner_id)
        .outerjoin(t.human, t.human.c.id == t.membership.c.human_id)
        .where(t.membership.c.project_id == project_id, t.membership.c.active.is_(True))
    ).all()
    rows = [r for r in rows if among is None or (r.agent_id or r.human_id) in among]
    # A member answers to its current handle and its aliases (§6.24, §8.6); an agent's long
    # form takes its owner's the same way.
    aliased = handle_book.aliases(
        conn, [r.agent_id or r.human_id for r in rows] + [r.owner_id for r in rows if r.owner_id]
    )
    memberships: dict[str, int] = {}  # agent member id -> membership row id
    members: list[_Candidate] = []
    current_human: dict[str, str] = {}  # a human's current handle -> member id
    for row in rows:
        member_id = row.agent_id or row.human_id
        if row.agent_id:
            memberships[row.agent_id] = row.id
            shown = global_name(row.owner_handle, row.agent_handle)
            owners = {row.owner_handle, *aliased[row.owner_id]}
            names = {row.agent_handle, *aliased[member_id]}
            members.append(_Candidate(member_id, False, row.agent_handle, shown, names, owners))
        else:
            current_human[row.human_handle] = member_id
            names = {row.human_handle, *aliased[member_id]}
            members.append(
                _Candidate(member_id, True, row.human_handle, row.human_handle, names, set())
            )

    def matches(c: Any) -> list[tuple[str, bool, str]]:
        """(member id, is human, shown name) of the members the candidate could mean."""
        return [
            (m.member_id, m.human, m.shown)
            for m in members
            if c.handle in m.names and (c.owner is None or (not m.human and c.owner in m.owners))
        ]

    resolved: dict[tuple[str | None, str], tuple[str, str] | None] = {}
    shared: dict[str, list[str]] = {}
    for c in sorted(found, key=lambda c: c.handle):
        candidates_of = matches(c)
        # Several candidates are refused, unless exactly one is a human whose current handle
        # it is: then that human comes first (§8.6).
        first = [m for m in candidates_of if m[1] and current_human.get(c.handle) == m[0]]
        pick = candidates_of if len(candidates_of) <= 1 else (first if len(first) == 1 else None)
        if pick is None:
            if c.owner is None:
                shared[c.handle] = sorted(name for _, _, name in candidates_of)
            else:
                shared[f"{c.owner}/{c.handle}"] = sorted(name for _, _, name in candidates_of)
            continue
        resolved[(c.owner, c.handle)] = (pick[0][0], pick[0][2]) if pick else None
    if shared:
        raise ApiError(
            400,
            "invalid",
            "a short handle names more than one member: use the global name",
            {"fields": {field: "ambiguous_mention"}, "mentions": shared},
        )
    known = _known_instances(conn, memberships, {c.instance for c in found if c.instance})
    handle_of = {m.member_id: m.handle for m in members}
    mentions = []
    for c in found:
        named: tuple[str, str | None] | None = None
        hit = resolved.get((c.owner, c.handle))
        if hit is not None:
            named = (
                hit[0],
                None if hit[0] in current_human.values() else hit[1],
            )  # a human has no global name
        if named is not None and c.instance is not None and (named[0], c.instance) not in known:
            named = None  # never an instance of that member: the whole text stays text
        if named is not None:
            mentions.append(
                {
                    "member_id": named[0],
                    "handle": handle_of[named[0]],  # now, also where the text names an alias
                    "name": named[1],
                    "instance": c.instance,  # null: the team (§8.6)
                    "field": field,
                    "offset": c.offset,
                    "length": c.length,
                }
            )
    if len({m["member_id"] for m in mentions}) > MAX_MEMBERS or len(mentions) > MAX_OCCURRENCES:
        raise invalid({field: "too_many_mentions"}, "too many mentions in one text")
    return mentions


class _Candidate(NamedTuple):
    """A member of the project a mention could mean (§8.6)."""

    member_id: str
    human: bool
    handle: str  # its current handle
    shown: str  # a human's handle, an agent's global name
    names: set[str]  # the handle and the aliases it answers to
    owners: set[str]  # an agent's owner's handle and aliases: the first half of its long form


def _known_instances(
    conn: Connection, memberships: dict[str, int], wanted: set[str]
) -> set[tuple[str, str]]:
    """(member id, instance id) of the wanted ids that name an instance of these agent
    members: one with a credential not revoked, or a replaced one, whose mention pings its
    successor (§6.17, §8.2). A revoked instance nobody replaced is no instance here."""
    if not wanted or not memberships:
        return set()
    by_row = {row_id: member_id for member_id, row_id in memberships.items()}
    successor = aliased(t.credential)
    replaced = (
        select(successor.c.id)
        .where(
            successor.c.membership_id == t.credential.c.membership_id,
            successor.c.replaces == t.credential.c.instance,
        )
        .exists()
    )
    rows = conn.execute(
        select(t.credential.c.membership_id, t.credential.c.instance).where(
            t.credential.c.membership_id.in_(list(by_row)),
            t.credential.c.instance.in_(wanted),
            or_(t.credential.c.revoked_at.is_(None), replaced),
        )
    )
    return {(by_row[r.membership_id], r.instance) for r in rows}


def tokens(
    conn: Connection, project_id: str, mentions: list[dict[str, Any]], members: Iterable[str]
) -> list[str]:
    """The audience tokens that ping `members` as these mentions name them: an instance
    mention pings that instance only (`instance:<member>#<id>`; the instance that replaced
    it when it was replaced, §8.2), a mention of the handle alone the team (`member:<id>`,
    woken by its wake rule, §8.2)."""
    wanted = set(members)
    found = [
        instance_token(conn, project_id, m["member_id"], m.get("instance"))
        for m in mentions
        if m["member_id"] in wanted
    ]
    return list(dict.fromkeys(found))


def instance_token(conn: Connection, project_id: str, member_id: str, instance: str | None) -> str:
    """The token one mention pings: the team's `member:<id>` when no instance is named,
    else the named instance resolved as an address in a `to` is (`instances.addressed`)."""
    if instance is None:
        return instances.token(member_id, None)
    row = conn.execute(
        # The active row: a member who was removed and joined again has two (§6.2).
        select(t.membership.c.id).where(
            t.membership.c.project_id == project_id,
            t.membership.c.agent_id == member_id,
            t.membership.c.active.is_(True),
        )
    ).scalar_one()
    return instances.addressed(conn, row, member_id, instance, "mentions")


def members(mentions: list[dict[str, Any]]) -> list[str]:
    """The distinct members mentioned, in order of first appearance."""
    return list(dict.fromkeys(m["member_id"] for m in mentions))


# At most PINGS_PER_WINDOW pings by one membership in PING_WINDOW seconds (§8.6).
# In-process, like the other limits of one replica.
PINGS = Limiter(PINGS_PER_WINDOW, PING_WINDOW, name="mentions.PINGS")


def charge(conn: Connection, membership_id: int, count: int) -> None:
    """Count `count` pings of one write, or refuse the whole write with `rate_limited`
    and the seconds until all of them fit. A write that does not commit (a retry, a
    later error) gives them back."""
    if count <= 0:
        return
    key = str(membership_id)
    wait, mark = PINGS.place(key, count)
    if wait:
        raise rate_limited(wait)
    on_rollback(conn, lambda: PINGS.release(key, mark, count))
