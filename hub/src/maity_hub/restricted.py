"""A card's restricted text and the project's restricted-access set (docs/api.md §6.4
"Restricted text", §6.1 "Restricted access").

The set is resolved on every call from `settings.restricted_access` and the project's
memberships, never stored resolved. Only this module, `routes/restricted.py` and the export's
one exception (`export.py`, the caller's own texts of a set they are in, §2.9) read
`task_restricted`; no read of a card does, so none can carry the text."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import clock
from maity_hub import tables as t

MODES = ("nobody_except", "all_except")
GUEST = "guest"


def access(project: Any) -> dict[str, Any] | None:
    """The stored `restricted_access`, or None: no key or `null` is a closed set (§6.1)."""
    value = (project.settings or {}).get("restricted_access")
    if not isinstance(value, dict) or value.get("mode") not in MODES:
        return None
    return value


def _seated(row: Any) -> bool:
    """An active member with trust above `guest`."""
    return row is not None and row.removed_at is None and row.trust != GUEST


def resolve(conn: Connection, project: Any) -> set[int]:
    """The membership row ids in the project's set now (§6.1 "Who is in the set")."""
    setting = access(project)
    if setting is None:
        return set()
    listed = set(setting.get("members") or [])
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.human_id,
            t.membership.c.agent_id,
            t.membership.c.trust,
            t.membership.c.removed_at,
            t.membership.c.isolated_since,
            t.agent_profile.c.owner_id,
        )
        .select_from(t.membership)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.membership.c.project_id == project.id, t.membership.c.removed_at.is_(None))
    ).all()
    humans = {row.human_id: row for row in rows if row.agent_id is None}
    all_except = setting["mode"] == "all_except"

    def named(member_id: str) -> bool:
        return (member_id not in listed) if all_except else (member_id in listed)

    def eligible(row: Any) -> bool:
        return _seated(row) and row.isolated_since is None

    def human_in(row: Any) -> bool:
        return eligible(row) and named(row.human_id)

    found: set[int] = set()
    for row in rows:
        if row.agent_id is None:
            if human_in(row):
                found.add(row.id)
            continue
        owner = humans.get(row.owner_id)
        if not (eligible(row) and _seated(owner) and named(row.agent_id)):
            continue
        # Under `all_except` an agent is in only while its owner is (§6.1); under
        # `nobody_except` it is listed itself and needs no listing of its owner.
        if all_except and not human_in(owner):
            continue
        found.add(row.id)
    return found


def in_set(conn: Connection, project: Any, membership_id: int) -> bool:
    return membership_id in resolve(conn, project)


def cards_with_text(conn: Connection, project_id: str) -> int:
    """How many cards of the project have a restricted text now (§6.1, the quota of §6.4)."""
    count: int = conn.execute(
        select(func.count())
        .select_from(t.task_restricted)
        .where(t.task_restricted.c.project_id == project_id, t.task_restricted.c.text.is_not(None))
    ).scalar_one()
    return count


# --- who is told (§6.4 "The change event", "When the set changes without the setting") ------

CARD_TOKEN = "restricted:"  # `restricted:<task id>`
SET_TOKEN = "restricted:set"
KIND = "restricted_changed"
# The account record of the notice (§18.1): written at most once per card and human, and per
# human and project for the set, in 10 minutes; read only while the human reads the event.
NOTICE = "restricted_changed"
NOTICE_GAP = timedelta(minutes=10)
CAUSES = ("setting", "joined", "trust_raised", "isolation_ended", "owner_changed")


def people(conn: Connection, membership_ids: set[int]) -> dict[int, dict[str, Any]]:
    """`{kind, id, handle}` per membership, an agent with its `owner` `{id, handle}`; a
    deleted account without its handle (§2.9)."""
    if not membership_ids:
        return {}
    owner = t.human.alias("restricted_owner")
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.human_id,
            t.membership.c.agent_id,
            t.human.c.handle.label("human_handle"),
            t.human.c.deleted_at,
            t.agent_profile.c.handle.label("agent_handle"),
            t.agent_profile.c.owner_id,
            owner.c.handle.label("owner_handle"),
            owner.c.deleted_at.label("owner_deleted_at"),
        )
        .select_from(t.membership)
        .outerjoin(t.human, t.human.c.id == t.membership.c.human_id)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .outerjoin(owner, owner.c.id == t.agent_profile.c.owner_id)
        .where(t.membership.c.id.in_(membership_ids))
    ).all()
    found: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.agent_id:
            found[row.id] = {
                "kind": "agent",
                "id": row.agent_id,
                "handle": row.agent_handle,
                "owner": {
                    "id": row.owner_id,
                    "handle": None if row.owner_deleted_at is not None else row.owner_handle,
                },
            }
        else:
            handle = None if row.deleted_at is not None else row.human_handle
            found[row.id] = {"kind": "human", "id": row.human_id, "handle": handle}
    return found


def person(conn: Connection, membership_id: int) -> dict[str, Any] | None:
    """`by` of an event: `{kind, id, handle}`, as a history entry names its author."""
    found = people(conn, {membership_id}).get(membership_id)
    if found is None:
        return None
    return {k: v for k, v in found.items() if k != "owner"}


def human_person(conn: Connection, human_id: str) -> dict[str, Any]:
    """`by` for a human who may be no member of the project (an organisation's owner, §6.26)."""
    row = conn.execute(
        select(t.human.c.handle, t.human.c.deleted_at).where(t.human.c.id == human_id)
    ).first()
    handle = None if row is None or row.deleted_at is not None else row.handle
    return {"kind": "human", "id": human_id, "handle": handle}


def _project(conn: Connection, project_id: str) -> Any:
    return conn.execute(select(t.project).where(t.project.c.id == project_id)).one()


def snapshot(conn: Connection, project_id: str) -> set[int]:
    """The set now, read before a change that may let members in (§6.4)."""
    return resolve(conn, _project(conn, project_id))


def _humans(conn: Connection, membership_ids: list[int]) -> dict[int, str]:
    if not membership_ids:
        return {}
    return {
        row.id: row.human_id
        for row in conn.execute(
            select(t.membership.c.id, t.membership.c.human_id).where(
                t.membership.c.id.in_(membership_ids), t.membership.c.agent_id.is_(None)
            )
        )
    }


def _notified_lately(
    conn: Connection, human_id: str, project_id: str, task_id: str | None, now: datetime
) -> bool:
    data = t.account_record.c.data
    query = select(t.account_record.c.n).where(
        t.account_record.c.human_id == human_id,
        t.account_record.c.type == NOTICE,
        t.account_record.c.at > now - NOTICE_GAP,
        data["project_id"].as_string() == project_id,
    )
    if task_id is None:
        query = query.where(data["task_id"].as_string().is_(None))
    else:
        query = query.where(data["task_id"].as_string() == task_id)
    return conn.execute(query.limit(1)).first() is not None


def _notify(
    conn: Connection,
    project_id: str,
    task_id: str | None,
    seq: int,
    listed: list[int],
    left_out: set[int],
) -> None:
    """One `inbox` notice per human on the list but those left out, at most one per card
    (or, for the set, per project) and human in 10 minutes (§6.4, §18.1). The notice holds
    ids only; whether it is listed is decided again at every read (`notifications.items`)."""
    from maity_hub.notifications import records

    now = clock.now()
    for membership_id, human_id in sorted(_humans(conn, listed).items()):
        if membership_id in left_out:
            continue
        if _notified_lately(conn, human_id, project_id, task_id, now):
            continue
        records.write(
            conn, human_id, NOTICE, {"project_id": project_id, "task_id": task_id, "seq": seq}
        )


def card_changed(
    conn: Connection,
    project: Any,
    task_id: str,
    version: int,
    action: str,
    writer: int,
    actor: Any,
    at: datetime,
) -> int:
    """`restricted_changed` for a write that changed a card's text (§6.4 "The change event"):
    to `restricted:<task id>`, its private list the set as it is now, the writer included;
    never the text or its length. The humans on the list but the writer get the notice."""
    from maity_hub import events

    listed = sorted(resolve(conn, project))
    payload = {
        "task_id": task_id,
        "version": version,
        "action": action,
        "by": person(conn, writer),
        "at": clock.rfc3339(at),
    }
    seq = events.emit(
        conn,
        project.id,
        KIND,
        [f"{CARD_TOKEN}{task_id}"],
        payload,
        actor=actor,
        restricted_list=listed,
    )
    _notify(conn, project.id, task_id, seq, listed, {writer})
    return seq


def _set_changed(
    conn: Connection,
    project: Any,
    action: str,
    named: set[int],
    listed: set[int],
    cause: str,
    by: dict[str, Any] | str | None,
    actor: Any,
) -> int:
    from maity_hub import events

    shown = people(conn, named)
    payload = {
        "task_id": None,
        "action": action,
        "members": [shown[i] for i in sorted(named) if i in shown],
        "cause": cause,
        "by": by,
        "at": clock.rfc3339(clock.now()),
    }
    seq = events.emit(
        conn, project.id, KIND, [SET_TOKEN], payload, actor=actor, restricted_list=sorted(listed)
    )
    _notify(conn, project.id, None, seq, sorted(listed), named)
    return seq


def entered(
    conn: Connection,
    project_id: str,
    before: set[int],
    cause: str,
    by: dict[str, Any] | str | None,
    actor: Any,
) -> set[int]:
    """After a change that may let members in (§6.1 "Every way into the set"): when the set
    holds a member it did not hold `before`, one `restricted_changed` with `action: entered`
    to `restricted:set`, its list the set after the change; it wakes nobody. Returns who
    entered."""
    project = _project(conn, project_id)
    after = resolve(conn, project)
    new = after - before
    if new:
        _set_changed(conn, project, "entered", new, after, cause, by, actor)
    return new


def owner_changed(conn: Connection, agent_id: str, actor: Any) -> None:
    """An agent profile's owner changed (§6.1 "An owner change under `nobody_except`"): its id
    leaves `members` of every project whose setting is `nobody_except`, with `project_updated`
    by the hub; where it was in the set before, one `restricted_changed` with `action: left`
    and `cause: owner_changed`. Called in the owner change's own transaction, before its
    other writes read the set. No route changes an owner yet (§6.3)."""
    from maity_hub import events, namespace

    rows = conn.execute(
        select(t.membership.c.id, t.membership.c.project_id).where(
            t.membership.c.agent_id == agent_id
        )
    ).all()
    for project_id in sorted({row.project_id for row in rows}):
        project = events.lock_project(conn, project_id)
        setting = access(project)
        if setting is None or setting["mode"] != "nobody_except":
            continue
        listed = list(setting.get("members") or [])
        if agent_id not in listed:
            continue
        before = resolve(conn, project)
        was_in = {row.id for row in rows if row.project_id == project_id} & before
        stored = {"mode": "nobody_except", "members": [m for m in listed if m != agent_id]}
        conn.execute(
            t.project.update()
            .where(t.project.c.id == project_id)
            .values(settings={**(project.settings or {}), "restricted_access": stored})
        )
        events.emit(
            conn,
            project_id,
            "project_updated",
            ["all"],
            {"fields": {"settings.restricted_access": stored}},
            actor=actor,
            subject=("project", namespace.full_name(conn, project)),
        )
        if was_in:
            after = resolve(conn, _project(conn, project_id))
            _set_changed(
                conn,
                _project(conn, project_id),
                "left",
                was_in,
                after,
                "owner_changed",
                "hub",
                actor,
            )


# --- who reads (§6.4 "Who reads it is decided again at every read") ------------------------


def readable_seqs(conn: Connection, rows: Any, membership: Any) -> frozenset[int]:
    """The `restricted_changed` events among `rows` this member reads now: on the event's
    private list and in the set at this read. Never the see-all, never the actor's own."""
    seqs = [r.seq for r in rows if getattr(r, "kind", None) == KIND]
    member_id = getattr(membership, "id", None)
    project_id = getattr(membership, "project_id", None) or getattr(
        getattr(membership, "project", None), "id", None
    )
    if not seqs or member_id is None or project_id is None:
        return frozenset()
    if member_id not in resolve(conn, _project(conn, project_id)):
        return frozenset()
    return frozenset(
        conn.execute(
            select(t.restricted_event_list.c.seq).where(
                t.restricted_event_list.c.membership_id == member_id,
                t.restricted_event_list.c.seq.in_(seqs),
            )
        ).scalars()
    )


# --- the setting as served (§6.1 "Reading the setting") -------------------------------------


def reads_members(conn: Connection, project: Any, reader: Any) -> bool:
    """`members` and `cards_with_text` go to a human with `project:admin` and to a member in
    the set; every other reader gets `{mode, included}`."""
    if reader is None:
        return False
    if getattr(reader, "kind", None) == "human" and reader.may("project:admin"):
        return True
    return reader.id in resolve(conn, project)


def served(conn: Connection, project: Any, reader: Any) -> dict[str, Any] | None:
    """`settings.restricted_access` for this reader (a `Membership`, or None for nobody's)."""
    setting = access(project)
    if setting is None:
        return None
    if reads_members(conn, project, reader):
        return {
            "mode": setting["mode"],
            "members": list(setting.get("members") or []),
            "included": reader.id in resolve(conn, project),
            "cards_with_text": cards_with_text(conn, project.id),
        }
    return {
        "mode": setting["mode"],
        "included": reader is not None and reader.id in resolve(conn, project),
    }


def announced(conn: Connection, project: Any, value: Any, reader: Any, full: bool | None) -> Any:
    """`fields["settings.restricted_access"]` of a `project_updated` for this reader: the
    stored `{mode, members}` to those who read the members now, `{mode, included}` with the
    reader's own `included` to every other; `null` stays `null`."""
    if not isinstance(value, dict):
        return value
    if full:
        return {"mode": value.get("mode"), "members": list(value.get("members") or [])}
    included = reader is not None and reader.id in resolve(conn, project)
    return {"mode": value.get("mode"), "included": included}
