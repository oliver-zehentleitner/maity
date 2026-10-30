"""Handles and their aliases (docs/api.md §6.24).

A human or an agent profile has a fixed id and a handle that can change; a handle given up stays
with the id as an alias, which nobody else can take. A handle is unique among all humans, and
among the live profiles of one owner (§6.3). Every path that gives a handle (registration, the
operator's `owner create`, `POST /agents`, a join, a placement) asks `ensure_free` under the
handle's lock; a rename is `rename`.

The lock is a row per (scope, handle) in `handle_lock`, taken after the renamed id's own row: two
claims of one handle in one scope run one after the other, and the second sees the first's
result. Nothing reads under it, and a rename of another handle never waits for it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, delete, insert, select, true, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, mentions, paths
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid, not_found, rate_limited

ALIAS_MAX = 8
RENAME_LIMIT = 3
RENAME_WINDOW = timedelta(hours=24)
HUMANS = "human"  # the scope of every human's handle
FORMAT = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")


def scope_of(owner_id: str | None) -> str:
    """Where a handle is unique: all humans (`None`), or one owner's profiles."""
    return HUMANS if owner_id is None else owner_id


def aliases(
    conn: Connection, ids: Iterable[str], *, include_retired: bool = False
) -> dict[str, list[str]]:
    """Per id its aliases, oldest first (the order the handles were given up); `[]` for none.
    A deleted profile's aliases are retired (`live` NULL, they left its owner's scope): only
    the tombstone's own view asks for them, which keeps them for the record (§6.3, §6.24)."""
    wanted = set(ids)
    found: dict[str, list[str]] = {i: [] for i in wanted}
    if not wanted:
        return found
    rows = conn.execute(
        select(t.handle_alias.c.human_id, t.handle_alias.c.agent_id, t.handle_alias.c.handle)
        .where(
            (t.handle_alias.c.human_id.in_(wanted)) | (t.handle_alias.c.agent_id.in_(wanted)),
            true() if include_retired else t.handle_alias.c.live.is_(True),
        )
        .order_by(t.handle_alias.c.id)
    )
    for row in rows:
        found[row.human_id or row.agent_id].append(row.handle)
    return found


def human_id_of(conn: Connection, handle: str) -> str | None:
    """The human whose current handle or alias is `handle`: unique among all humans (§6.24)."""
    found = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
    if found is None:
        found = conn.execute(
            select(t.handle_alias.c.human_id).where(
                t.handle_alias.c.scope == HUMANS,
                t.handle_alias.c.handle == handle,
                t.handle_alias.c.live.is_(True),
            )
        ).scalar()
    return None if found is None else str(found)


def lock(conn: Connection, scope: str, handle: str) -> None:
    """Take the lock of `handle` in `scope`, making its row first when there is none."""
    try:
        with conn.begin_nested():
            conn.execute(insert(t.handle_lock).values(scope=scope, handle=handle))
    except IntegrityError:
        pass  # there already
    conn.execute(
        select(t.handle_lock.c.handle)
        .where(t.handle_lock.c.scope == scope, t.handle_lock.c.handle == handle)
        .with_for_update()
    ).first()


def holder(conn: Connection, scope: str, handle: str) -> str | None:
    """The id that has `handle` in `scope` as its handle or as an alias (for the humans' scope
    an organisation's id too: they share it, §6.26); `"placement"` while
    an active placement will create a profile of the owner with it (§15.5); else `None`."""
    if scope == HUMANS:
        # The register holds the current handle of every human and organisation, a deleted
        # one's included (§6.26); the account row covers a human the register lacks.
        current = conn.execute(
            select(t.handle_register.c.owner_id).where(t.handle_register.c.handle == handle)
        ).scalar()
        if current is None:
            current = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
    else:
        current = conn.execute(
            select(t.agent_profile.c.id).where(
                t.agent_profile.c.owner_id == scope,
                t.agent_profile.c.handle == handle,
                t.agent_profile.c.live.is_(True),
            )
        ).scalar()
    if current is not None:
        return str(current)
    alias = conn.execute(
        select(t.handle_alias.c.human_id, t.handle_alias.c.agent_id).where(
            t.handle_alias.c.scope == scope,
            t.handle_alias.c.handle == handle,
            t.handle_alias.c.live.is_(True),
        )
    ).first()
    if alias is not None:
        return str(alias.human_id or alias.agent_id)
    if scope != HUMANS:
        reserved = conn.execute(
            select(t.placement.c.id).where(
                t.placement.c.created_by == scope,
                t.placement.c.new_handle == handle,
                t.placement.c.active.is_(True),
                t.placement.c.membership_id.is_(None),
            )
        ).first()
        if reserved is not None:
            return "placement"
    return None


def ensure_free(
    conn: Connection,
    owner_id: str | None,
    handle: str,
    *,
    exclude: str | None = None,
    field: str = "handle",
) -> None:
    """`invalid` / `taken` when `handle` is the handle or an alias of another id in the scope
    (or a human handle the hub or the dashboard keeps, `reserved`, §16.11). Takes the handle's
    lock first, so the answer holds until the transaction ends. `exclude`: the id that may have
    it (itself)."""
    scope = scope_of(owner_id)
    if owner_id is None and handle in paths.RESERVED_FIRST:
        raise invalid({field: "reserved"})
    lock(conn, scope, handle)
    taken = holder(conn, scope, handle)
    if taken is not None and taken != exclude:
        raise invalid({field: "taken"})


def retire(conn: Connection, agent_id: str) -> None:
    """A deleted profile's aliases leave its owner's scope with its handle (§6.3)."""
    conn.execute(
        update(t.handle_alias).where(t.handle_alias.c.agent_id == agent_id).values(live=None)
    )


class AliasLimit(ApiError):
    def __init__(self, current: Sequence[str]) -> None:
        super().__init__(
            409,
            "alias_limit",
            f"a handle keeps at most {ALIAS_MAX} aliases",
            {"limit": ALIAS_MAX, "aliases": list(current)},
        )


def rename(
    conn: Connection, subject_id: str, owner_id: str | None, handle: str
) -> tuple[str, str] | None:
    """Give the human (`owner_id` None) or the profile `subject_id` a new handle; the old one
    becomes an alias, an alias of its own taken back leaves the list. `(old, new)`, or `None`
    for the id's own current handle (§6.24: a no-op, nothing changes, no event). The caller has
    checked who may rename."""
    if not FORMAT.fullmatch(handle):
        raise invalid({"handle": "format"})
    table = t.human if owner_id is None else t.agent_profile
    # The id's own row first, then the handle's lock: the order every rename takes.
    row = conn.execute(select(table).where(table.c.id == subject_id).with_for_update()).one()
    # The caller looked at the profile before this lock: a delete that won the lock in between
    # has freed its handle and aliases, and a rename now would take them back for a tombstone.
    if owner_id is not None and row.live is not True:
        raise not_found()
    if row.handle == handle:
        return None
    ensure_free(conn, owner_id, handle, exclude=subject_id)
    scope = scope_of(owner_id)
    own = aliases(conn, [subject_id])[subject_id]
    back = handle in own
    if not back and len(own) >= ALIAS_MAX:
        raise AliasLimit(own)
    now = clock.now()
    recent = (
        conn.execute(
            select(t.handle_change.c.created_at)
            .where(
                t.handle_change.c.subject_id == subject_id,
                t.handle_change.c.created_at > now - RENAME_WINDOW,
            )
            .order_by(t.handle_change.c.created_at)
        )
        .scalars()
        .all()
    )
    if len(recent) >= RENAME_LIMIT:
        wait = recent[len(recent) - RENAME_LIMIT] + RENAME_WINDOW - now
        raise rate_limited(max(1, int(wait.total_seconds()) + 1))
    column = t.handle_alias.c.human_id if owner_id is None else t.handle_alias.c.agent_id
    if back:
        conn.execute(
            delete(t.handle_alias).where(
                column == subject_id,
                t.handle_alias.c.handle == handle,
                t.handle_alias.c.live.is_(True),
            )
        )
    conn.execute(update(table).where(table.c.id == subject_id).values(handle=handle))
    if owner_id is None:  # the register follows the account's current handle (§6.26)
        try:
            with conn.begin_nested():
                conn.execute(
                    update(t.handle_register)
                    .where(t.handle_register.c.owner_id == subject_id)
                    .values(handle=handle)
                )
        except IntegrityError:  # an organisation or an account took it between check and update
            raise invalid({"handle": "taken"}) from None
    conn.execute(
        insert(t.handle_alias).values(
            human_id=subject_id if owner_id is None else None,
            agent_id=None if owner_id is None else subject_id,
            scope=scope,
            handle=row.handle,
            created_at=now,
        )
    )
    conn.execute(insert(t.handle_change).values(subject_id=subject_id, created_at=now))
    return str(row.handle), handle


def announce(
    conn: Connection,
    caller: Any,
    subject_id: str,
    owner_id: str | None,
    old: str,
    new: str,
) -> None:
    """What a rename emits in every project where the id holds an active membership (§6.24):
    `member_updated` with `changed: ["handle"]` and a ticker item `rename`; for a human's
    rename also `changed: ["name"]` and an item for each of their agents' memberships, whose
    global name changed with it. The actor is the renaming human's member in that project,
    none where they are not a member."""
    from maity_hub import public_pages, public_people, ticker
    from maity_hub.events import emit
    from maity_hub.views import member_view

    def memberships(column: Any, ids: Sequence[str]) -> list[Any]:
        return list(
            conn.execute(
                select(t.membership)
                .where(column.in_(ids), t.membership.c.active.is_(True))
                .order_by(t.membership.c.project_id, t.membership.c.id)
            )
        )

    human_id = subject_id if owner_id is None else owner_id
    mine = {
        m.project_id: m.id
        for m in conn.execute(
            select(t.membership.c.project_id, t.membership.c.id).where(
                t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
            )
        )
    }

    def actor_in(project_id: str) -> Any:
        own = mine.get(project_id)
        return caller.actor(own) if own is not None and caller.kind == "human" else None

    def one(row: Any, changed: str, before: str, after: str) -> None:
        view = member_view(conn, row)
        view["changed"] = [changed]
        actor = actor_in(row.project_id)
        emit(
            conn,
            row.project_id,
            "member_updated",
            ["all"],
            view,
            actor=actor,
            subject=("member", view["id"]),
        )
        ticker.write_rename(
            conn, row.project_id, before, after, actor, caller.principal_id if actor else None
        )

    column = t.membership.c.human_id if owner_id is None else t.membership.c.agent_id
    if owner_id is None:  # the person's page is addressed by the handle (§16.9): render it again
        public_pages.touch(conn, public_people.KIND, subject_id)
    shown = (old, new)
    if owner_id is not None:  # an agent is named by its global name (§6.3)
        owner_handle = _owner_handle(conn, owner_id)
        shown = (mentions.global_name(owner_handle, old), mentions.global_name(owner_handle, new))
    for row in memberships(column, [subject_id]):
        one(row, "handle", *shown)
    if owner_id is None:
        agents = list(
            conn.execute(
                select(t.agent_profile.c.id, t.agent_profile.c.handle).where(
                    t.agent_profile.c.owner_id == subject_id,
                    t.agent_profile.c.live.is_(True),
                )
            )
        )
        by_id = {a.id: a.handle for a in agents}
        for row in memberships(t.membership.c.agent_id, list(by_id)):
            handle = by_id[row.agent_id]
            one(row, "name", mentions.global_name(old, handle), mentions.global_name(new, handle))


def _owner_handle(conn: Connection, owner_id: str) -> str:
    return str(conn.execute(select(t.human.c.handle).where(t.human.c.id == owner_id)).scalar_one())
