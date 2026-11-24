"""A human's stars (docs/api.md §5.1 "Stars"): the public projects they keep as tabs without
being a member, in the order starred, named by the project's fixed id so that a rename or a
transfer keeps them. One JSON list on the human's row (`human.starred`), as `start_tabs`.

An entry whose project is not public now is kept but hidden: the read leaves it out, a `PATCH`
cannot name it and keeps it in its place, and it counts toward `max_starred_per_human`. Only a
membership of the human drops an entry. Stars are private: no count, no event, no notice.

Whether a project is public is `public_projects.served`, asked for every entry at once
(`public_for_outsiders`): `GET /me` reads the stars on every poll, so their cost does not grow
with their number. While the instance serves no public pages (`MAITY_PUBLIC_PAGES` off) no
project is public: every stored entry is hidden and a `PATCH` naming one is `not_public`."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import namespace
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid

FIELD = "starred"


def _member_of(conn: Connection, human_id: str, project_ids: Collection[str]) -> set[str]:
    """Of `project_ids`, the projects the human holds an active membership in (`access`'s
    rule: a removed member is no member and may star the project again)."""
    if not project_ids:
        return set()
    m = t.membership.c
    return set(
        conn.execute(
            select(m.project_id).where(
                m.human_id == human_id,
                m.active.is_(True),
                m.project_id.in_(sorted(set(project_ids))),
            )
        ).scalars()
    )


def _shown(conn: Connection, stored: list[str], members: Collection[str]) -> list[str]:
    """The stored entries a read shows: public now and no membership of the human's."""
    from maity_hub import public_projects  # the public pages' modules; `drop` needs none

    candidates = [entry for entry in stored if entry not in members]
    public = public_projects.public_for_outsiders(conn, candidates)
    return [entry for entry in candidates if entry in public]


def visible(conn: Connection, stored: list[str] | None, members: Collection[str]) -> list[Any]:
    """`starred` as `GET /me` shows it (§5.1): `[{id, full_name}]` in the stored order, hidden
    entries left out. `members` are the project ids of the human's memberships, which the
    caller has read already. A fixed number of statements, none without a star."""
    if not stored:
        return []
    shown = _shown(conn, stored, set(members))
    names = namespace.full_names(conn, shown)
    return [{"id": entry, "full_name": names[entry]} for entry in shown if entry in names]


def visible_of(conn: Connection, human_id: str, stored: list[str] | None) -> list[Any]:
    """`visible` where the caller has not read the human's memberships (the export, §2.9)."""
    if not stored:
        return []
    return visible(conn, stored, _member_of(conn, human_id, stored))


def _too_many(hidden: int) -> ApiError:
    """`invalid` with `details.hidden`: the entries the human cannot see that count (§5.1)."""
    return ApiError(
        400,
        "invalid",
        "more starred projects than the hub keeps for one human",
        {"fields": {FIELD: "too_many"}, "hidden": hidden},
    )


def _placed(stored: list[str], shown: set[str], given: list[str]) -> list[str]:
    """`given` with every hidden entry of `stored` kept in its place: right after the visible
    entry it followed. When that entry is not in `given` any more, the hidden one follows the
    nearest earlier visible entry that is, and goes first when none is; hidden entries that
    follow the same entry keep their stored order (hub/context/persistence.md c0e833f1)."""
    kept = set(given)
    after: dict[str | None, list[str]] = {}
    anchor: str | None = None
    for entry in stored:
        if entry in shown:
            if entry in kept:
                anchor = entry
        else:
            after.setdefault(anchor, []).append(entry)
    placed = list(after.get(None, []))
    for entry in given:
        placed.append(entry)
        placed.extend(after.get(entry, []))
    return placed


def checked(conn: Connection, human_id: str, given: list[str] | None, bound: int) -> list[str]:
    """`PATCH /me`'s `starred` (§5.1), always the whole list: the list to store, or `invalid`
    with `details.fields.starred` `duplicate`, `member`, `not_public` or `too_many` (with
    `details.hidden`). An id that names no project is `not_public`: the answer does not say
    whether a private project of that id exists. `bound` is `max_starred_per_human`; a list
    that adds no project is accepted at any length, so a lowered bound takes no star away."""
    from maity_hub import public_projects

    if given is None:
        raise invalid({FIELD: "required"}, "starred is a list; [] keeps no star")
    if len(set(given)) != len(given):
        raise invalid({FIELD: "duplicate"}, "a project is in the list twice")
    # The human's row first, as a new membership's `drop` takes it: a membership made
    # meanwhile is then either seen here or drops its project from what this stores.
    row = conn.execute(
        select(t.human.c.starred).where(t.human.c.id == human_id).with_for_update()
    ).one()
    stored: list[str] = list(row.starred or [])
    adds = len(given) > len(stored)  # some entry is new, so the list grows past `stored`
    if adds and len(given) > bound:
        # Refused before `given` is looked up: an overlong body never becomes an IN list.
        hidden = len(stored) - len(_shown(conn, stored, _member_of(conn, human_id, stored)))
        raise _too_many(hidden)
    members = _member_of(conn, human_id, [*stored, *given])
    if members & set(given):
        raise invalid({FIELD: "member"}, "a project you are a member of is a tab already")
    public = public_projects.public_for_outsiders(conn, [*stored, *given])
    if not set(given) <= public:
        raise invalid({FIELD: "not_public"}, "a project that is not public")
    shown = {entry for entry in stored if entry in public and entry not in members}
    placed = _placed(stored, shown, given)
    if set(given) - set(stored) and len(placed) > bound:
        raise _too_many(len(stored) - len(shown))
    return placed


def store(conn: Connection, human_id: str, starred: list[str]) -> None:
    conn.execute(update(t.human).where(t.human.c.id == human_id).values(starred=starred))


def drop(conn: Connection, human_id: str, project_id: str) -> None:
    """A new membership of the human drops its project from their stars: it is a membership tab
    from then on (§5.1). Called wherever a human's membership is made, in its transaction."""
    row = conn.execute(
        select(t.human.c.starred).where(t.human.c.id == human_id).with_for_update()
    ).first()
    if row is None or not row.starred or project_id not in row.starred:
        return
    store(conn, human_id, [entry for entry in row.starred if entry != project_id])
