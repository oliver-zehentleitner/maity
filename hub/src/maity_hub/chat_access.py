"""A human's allow and deny entries for their agents (docs/api.md §9.6, "The lists").

An entry says who may chat with the human's agents: an allow names a side (another human with
all, listed or none of their agents, and that human or not) or a project; a deny names a side,
one human, one agent or a project, and wins over every allow. Only the human reads and changes
the list. The entries are kept here and served by `/me/chat-access`. Nothing admits or holds
back an agent by them yet: the gate (§9.6, "Waiting") is a later part of the same card.

An entry is a row of the human: deleted with the account and in its export. The agents, humans
and projects it names are taken out of it when they go, and an entry left with no agent on the
owner's side, or naming no one, is deleted (§9.6, "Records").
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, delete, func, insert, or_, select, update

from maity_hub import clock, namespace, write_guard
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.ids import new_id
from maity_hub.views import ts

MAX_ENTRIES = 1000  # allow and deny together, per human
TEXT_MAX = 1000  # characters of `allowed` and `denied`
DURATIONS = {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(weeks=1)}
ALLOW, DENY = "allow", "deny"
OWN, THEIRS = "own", "theirs"
ALL, LIST, NONE = "all", "list", "none"
UNSET: Any = object()  # a field the body did not send


def lock_rows(engine: Any, me: str, owner_id: Any, human_id: Any = None) -> None:
    """Make the `account_lock` rows of the caller and of the other humans an entry names, in a
    transaction of their own that commits first, in the order of their ids, as
    `contacts.lock_rows` does: two humans naming each other for the first time would otherwise
    each insert their own row and wait for the other's uncommitted insert."""
    others = {v for v in (owner_id, human_id) if isinstance(v, str) and v.startswith("hum-")}
    with engine.begin() as conn:
        write_guard.exempt(conn)
        for each in sorted({me} | others):
            write_guard.ensure_row(conn, each)


# Checks of a body ----------------------------------------------------------------------------


def _agents(conn: Connection, me: str, raw: Any) -> tuple[bool, list[str]]:
    """`agents`: `"all"` or a list of the caller's own live agents, none twice (§9.6)."""
    if raw == ALL:
        return True, []
    ids = _id_list(raw, "agents")
    if not ids:
        raise invalid({"agents": "format"}, 'agents is "all" or a list of agent ids')
    a = t.agent_profile.c
    mine = set(
        conn.execute(
            select(a.id)
            .where(a.id.in_(ids), a.owner_id == me, a.deleted_at.is_(None))
            .order_by(a.id)
            .with_for_update(read=True)  # a deletion of one waits for this write, or is seen
        ).scalars()
    )
    if mine != set(ids):
        raise invalid({"agents": "not_yours"}, "an entry names only your own agents")
    return False, ids


def _their_agents(conn: Connection, owner_id: str, raw: Any) -> tuple[str, list[str]]:
    """`their_agents`: `"all"`, `"none"` or a list of live agents of `owner_id` (§9.6)."""
    if raw in (ALL, NONE):
        return str(raw), []
    ids = _id_list(raw, "their_agents")
    if not ids:
        raise invalid(
            {"their_agents": "format"}, 'their_agents is "all", "none" or a list of agent ids'
        )
    a = t.agent_profile.c
    theirs = set(
        conn.execute(
            select(a.id)
            .where(a.id.in_(ids), a.owner_id == owner_id, a.deleted_at.is_(None))
            .order_by(a.id)
            .with_for_update(read=True)
        ).scalars()
    )
    if theirs != set(ids):
        raise invalid({"their_agents": "not_theirs"}, "their_agents names only agents of owner_id")
    return LIST, ids


def _id_list(raw: Any, field: str) -> list[str]:
    if not isinstance(raw, list) or any(not isinstance(v, str) for v in raw):
        raise invalid({field: "format"}, f"{field} is a list of ids")
    if len(set(raw)) != len(raw):
        raise invalid({field: "duplicate"}, f"an id twice in {field}")
    if len(raw) > MAX_ENTRIES:
        raise invalid({field: "too_many"}, f"at most {MAX_ENTRIES} ids in {field}")
    return list(raw)


def _human(conn: Connection, me: str, raw: Any, field: str) -> str:
    """A live, active account other than the caller's, its `account_lock` taken shared before
    its row is read, as `contacts.target` does: a deletion of that account either waits for
    this transaction, and its cleanup then removes the entry, or has committed and is seen."""
    if not isinstance(raw, str) or not raw.startswith("hum-"):
        raise invalid({field: "format"}, f"{field} is a human id")
    if raw == me:
        raise invalid({field: "self"}, "your own side needs no entry")
    write_guard.share(conn, raw)
    h = t.human.c
    # A suspended account stays a side one may name: an entry is the owner's own word about
    # that person, and a suspension ends; deletion and an account not yet active do not.
    found = conn.execute(select(h.deleted_at, h.account_status).where(h.id == raw)).first()
    if found is None or found.deleted_at is not None or found.account_status != "active":
        raise invalid({field: "not_found"}, f"no such person for {field}")
    return raw


def _agent(conn: Connection, me: str, raw: Any) -> str:
    """A live agent of someone else: the subject of a deny of one agent."""
    if not isinstance(raw, str):
        raise invalid({"agent_id": "format"}, "agent_id is an agent id")
    a = t.agent_profile.c
    found = conn.execute(
        select(a.owner_id).where(a.id == raw, a.deleted_at.is_(None)).with_for_update(read=True)
    ).first()
    if found is None:
        raise invalid({"agent_id": "not_found"}, "no such agent")
    if found.owner_id == me:
        raise invalid({"agent_id": "self"}, "your own agents need no entry")
    return raw


def _project(conn: Connection, me: str, raw: Any) -> str:
    """`project: {owner, slug}`: a project the caller or one of their agents is a member of,
    so that an entry never tells whether a project the caller cannot see exists."""
    if (
        not isinstance(raw, dict)
        or set(raw) != {"owner", "slug"}
        or not all(isinstance(v, str) for v in raw.values())
    ):
        raise invalid({"project": "format"}, "project is {owner, slug}")
    project = namespace.resolve(conn, f"{raw['owner']}/{raw['slug']}")
    if project is None:
        raise invalid({"project": "not_found"}, "no such project")
    m, a = t.membership.c, t.agent_profile.c
    mine = conn.execute(
        select(m.id)
        .outerjoin(t.agent_profile, a.id == m.agent_id)
        .where(
            m.project_id == project.id,
            m.removed_at.is_(None),
            or_(m.human_id == me, a.owner_id == me),
        )
        .limit(1)
    ).first()
    if mine is None:
        raise invalid({"project": "not_found"}, "no such project")
    return str(project.id)


def _text(raw: Any, field: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > TEXT_MAX:
        raise invalid({field: "format"}, f"{field} is text of at most {TEXT_MAX} characters")
    return raw


def _duration(raw: Any) -> str | None:
    if raw is None:
        return None
    if raw not in DURATIONS:
        raise invalid({"duration": "format"}, "duration is hour, day, week or null")
    return str(raw)


def _until(duration: str | None, at: datetime) -> datetime | None:
    return None if duration is None else at + DURATIONS[duration]


def _lock(conn: Connection, me: str) -> None:
    """The caller's human row, locked before its entries are read or counted: two writes of the
    same human run one after the other, so the cap holds and a deny sees an allow written at the
    same time (SQLite's `BEGIN IMMEDIATE` already serialises them).

    On PostgreSQL the lock is `FOR NO KEY UPDATE`, which the foreign key check of another
    human's entry naming this one (`FOR KEY SHARE`) does not wait for: two humans naming each
    other at once do not deadlock. The caller's `account_lock` is no choice here, since every
    write already holds it shared (`write_guard.hold`), and taking it exclusively from there
    would deadlock two writes of the same human. MariaDB has no such mode: its foreign key check
    takes a shared lock on the other's row, and the deadlock it may then report is transient and
    run again (`db.TRANSIENT`)."""
    conn.execute(
        select(t.human.c.id).where(t.human.c.id == me).with_for_update(key_share=True)
    ).first()


def _room(conn: Connection, me: str) -> None:
    """At most `MAX_ENTRIES` entries per human (§9.6): one more is `invalid`."""
    c = t.chat_access.c
    count = conn.execute(select(func.count()).where(c.human_id == me)).scalar_one()
    if count >= MAX_ENTRIES:
        raise ApiError(
            400, "invalid", f"at most {MAX_ENTRIES} entries", {"reason": "too_many_entries"}
        )


def _names_someone(their_agents: str, their_human: bool) -> None:
    """A side's allow entry that covers none of its agents and not its human names no one:
    `invalid`, as the hub deletes such an entry when it comes to that (§9.6, "Records")."""
    if their_agents == NONE and not their_human:
        raise invalid(
            {"their_agents": "names_no_one"},
            "the entry covers none of that side's agents and not its human",
        )


def _one_subject(body: dict[str, Any], allowed: Iterable[str]) -> str:
    named = [k for k in allowed if body.get(k, UNSET) is not UNSET and body.get(k) is not None]
    if len(named) != 1:
        fields = {k: "one_subject" for k in allowed}
        raise invalid(fields, "an entry names exactly one of " + ", ".join(allowed))
    return named[0]


# Writes --------------------------------------------------------------------------------------


def create_allow(conn: Connection, me: str, body: dict[str, Any]) -> str:
    """`POST /me/chat-access/allow` (§9.6): a new allow entry of `me`, its id."""
    _lock(conn, me)
    subject = _one_subject(body, ("owner_id", "project"))
    agents_all, own = _agents(conn, me, body.get("agents"))
    now = clock.now()
    values: dict[str, Any] = {
        "id": new_id("chat_access"),
        "human_id": me,
        "kind": ALLOW,
        "agents_all": agents_all,
        "by": me,
        "since": now,
        "allowed": _text(body.get("allowed"), "allowed"),
        "denied": _text(body.get("denied"), "denied"),
    }
    duration = _duration(body.get("duration"))
    values.update(duration=duration, until=_until(duration, now))
    theirs: list[str] = []
    if subject == "owner_id":
        owner_id = _human(conn, me, body["owner_id"], "owner_id")
        mode, theirs = _their_agents(conn, owner_id, body.get("their_agents", ALL))
        human = body.get("their_human", False)
        if not isinstance(human, bool):
            raise invalid({"their_human": "format"}, "their_human is true or false")
        values.update(owner_id=owner_id, their_agents=mode, their_human=human)
        _names_someone(mode, human)
    else:
        for field in ("their_agents", "their_human"):
            if body.get(field) is not None:
                raise invalid({field: "project_entry"}, "a project entry names no side")
        values["project_id"] = _project(conn, me, body["project"])
    _room(conn, me)
    conn.execute(insert(t.chat_access).values(values))
    _write_agents(conn, values["id"], own, theirs)
    return str(values["id"])


def patch_allow(conn: Connection, me: str, entry_id: str, body: dict[str, Any]) -> None:
    """`PATCH /me/chat-access/allow/{id}` (§9.6). A `duration` sent starts the time again from
    now; one not sent keeps `until`. `their_agents` and `their_human` only on a side's entry."""
    _lock(conn, me)
    # The agents are checked, and their rows held shared, before the entry's row is locked, and
    # the entry's agent rows are replaced only after that: an agent's deletion takes the agent's
    # row, then the entries' rows, then their agent rows (`forget_agent`), so the two orders
    # agree and cannot wait on each other in a cycle.
    row = _row(conn, me, ALLOW, entry_id)
    values: dict[str, Any] = {}
    own: list[str] | None = None
    theirs: list[str] | None = None
    if "agents" in body:
        agents_all, own = _agents(conn, me, body["agents"])
        values["agents_all"] = agents_all
    if ("their_agents" in body or "their_human" in body) and row.owner_id is None:
        field = "their_agents" if "their_agents" in body else "their_human"
        raise invalid({field: "project_entry"}, "a project entry names no side")
    if "their_agents" in body:
        mode, theirs = _their_agents(conn, row.owner_id, body["their_agents"])
        values["their_agents"] = mode
    row = _row(conn, me, ALLOW, entry_id, lock=True)
    if own is not None:
        _replace_agents(conn, entry_id, OWN, own)
    if theirs is not None:
        _replace_agents(conn, entry_id, THEIRS, theirs)
    if "their_human" in body:
        if not isinstance(body["their_human"], bool):
            raise invalid({"their_human": "format"}, "their_human is true or false")
        values["their_human"] = body["their_human"]
    if row.owner_id is not None:
        _names_someone(
            values.get("their_agents", row.their_agents),
            values.get("their_human", row.their_human),
        )
    if "duration" in body:
        duration = _duration(body["duration"])
        values.update(duration=duration, until=_until(duration, clock.now()))
    for field in ("allowed", "denied"):
        if field in body:
            values[field] = _text(body[field], field)
    if values:
        conn.execute(update(t.chat_access).where(t.chat_access.c.id == entry_id).values(values))


def create_deny(conn: Connection, me: str, body: dict[str, Any]) -> str:
    """`POST /me/chat-access/deny` (§9.6): a new deny entry, its id. It removes the caller's
    allow entries for the same agents and subject: a side's or a project's. An allow for all
    agents stays when the deny names some of them, since a deny wins over it anyway."""
    _lock(conn, me)
    subject = _one_subject(body, ("owner_id", "human_id", "agent_id", "project"))
    agents_all, own = _agents(conn, me, body.get("agents"))
    values: dict[str, Any] = {
        "id": new_id("chat_access"),
        "human_id": me,
        "kind": DENY,
        "agents_all": agents_all,
        "by": me,
        "since": clock.now(),
    }
    if subject == "owner_id":
        values["owner_id"] = _human(conn, me, body["owner_id"], "owner_id")
    elif subject == "human_id":
        values["subject_human_id"] = _human(conn, me, body["human_id"], "human_id")
    elif subject == "agent_id":
        values["subject_agent_id"] = _agent(conn, me, body["agent_id"])
    else:
        values["project_id"] = _project(conn, me, body["project"])
    _room(conn, me)
    conn.execute(insert(t.chat_access).values(values))
    _write_agents(conn, values["id"], own, [])
    if subject in ("owner_id", "project"):
        column = "owner_id" if subject == "owner_id" else "project_id"
        _narrow_allows(conn, me, column, values[column], agents_all, own)
    return str(values["id"])


def _narrow_allows(
    conn: Connection, me: str, column: str, value: str, agents_all: bool, agents: list[str]
) -> None:
    c, g = t.chat_access.c, t.chat_access_agent.c
    allows = conn.execute(
        select(c.id, c.agents_all)
        .where(c.human_id == me, c.kind == ALLOW, getattr(c, column) == value)
        .order_by(c.id)
        .with_for_update()
    ).all()
    for entry in allows:
        if agents_all:
            _drop(conn, [entry.id])
            continue
        if entry.agents_all:
            continue  # the deny wins over it for the agents it names
        conn.execute(
            delete(t.chat_access_agent).where(
                g.entry_id == entry.id, g.side == OWN, g.agent_id.in_(agents)
            )
        )
    _prune(conn, [entry.id for entry in allows])


def delete_entry(conn: Connection, me: str, kind: str, entry_id: str) -> None:
    """`DELETE /me/chat-access/{allow|deny}/{id}`: also when the entry was not there."""
    _lock(conn, me)
    c = t.chat_access.c
    found = conn.execute(
        select(c.id).where(c.id == entry_id, c.human_id == me, c.kind == kind)
    ).first()
    if found is not None:
        _drop(conn, [entry_id])


def _write_agents(conn: Connection, entry_id: str, own: list[str], theirs: list[str]) -> None:
    rows = [{"entry_id": entry_id, "side": OWN, "agent_id": a} for a in own]
    rows += [{"entry_id": entry_id, "side": THEIRS, "agent_id": a} for a in theirs]
    if rows:
        conn.execute(insert(t.chat_access_agent), rows)


def _replace_agents(conn: Connection, entry_id: str, side: str, agents: list[str]) -> None:
    g = t.chat_access_agent.c
    conn.execute(delete(t.chat_access_agent).where(g.entry_id == entry_id, g.side == side))
    if agents:
        conn.execute(
            insert(t.chat_access_agent),
            [{"entry_id": entry_id, "side": side, "agent_id": a} for a in agents],
        )


def _drop(conn: Connection, entry_ids: list[str]) -> None:
    """Delete entries with their agent rows. The entries' rows are locked first, in the order
    `PATCH` locks them, so a change of one waits for this or this for it, never both."""
    if not entry_ids:
        return
    c = t.chat_access.c
    conn.execute(select(c.id).where(c.id.in_(entry_ids)).order_by(c.id).with_for_update()).all()
    conn.execute(delete(t.chat_access_agent).where(t.chat_access_agent.c.entry_id.in_(entry_ids)))
    conn.execute(delete(t.chat_access).where(t.chat_access.c.id.in_(entry_ids)))


def _prune(conn: Connection, entry_ids: list[str]) -> None:
    """Of `entry_ids`, the entries a removal just touched and no others: delete those left with
    no agent on the owner's side, and turn a side's listed agents that are all gone into `none`;
    such an entry that no longer names the side's human either names no one and goes too
    (§9.6, "Records")."""
    if not entry_ids:
        return
    c, g = t.chat_access.c, t.chat_access_agent.c
    touched = c.id.in_(entry_ids)
    own = select(g.entry_id).where(g.entry_id == c.id, g.side == OWN).exists()
    theirs = select(g.entry_id).where(g.entry_id == c.id, g.side == THEIRS).exists()
    empty = conn.execute(select(c.id).where(touched, c.agents_all.is_(False), ~own)).scalars()
    _drop(conn, list(empty))
    conn.execute(
        update(t.chat_access)
        .where(touched, c.their_agents == LIST, ~theirs)
        .values(their_agents=NONE)
        .execution_options(synchronize_session=False)
    )
    nobody = conn.execute(
        select(c.id).where(
            touched,
            c.kind == ALLOW,
            c.owner_id.is_not(None),
            c.their_agents == NONE,
            c.their_human.is_(False),
        )
    ).scalars()
    _drop(conn, list(nobody))


# Cleanup when what an entry names goes ------------------------------------------------------


def forget_human(conn: Connection, human_id: str) -> None:
    """A deleted account (§2.9): its own entries, and every entry naming it as a side or as the
    human of a deny, go. Its agents are taken out of every entry by `forget_agent`, which the
    deletion of each of its profiles calls (`delete_profile`)."""
    c = t.chat_access.c
    gone = conn.execute(
        select(c.id).where(
            or_(c.human_id == human_id, c.owner_id == human_id, c.subject_human_id == human_id)
        )
    ).scalars()
    _drop(conn, list(gone))


def forget_agent(conn: Connection, agent_id: str) -> None:
    """A deleted agent profile (§6.3): taken out of every entry; a deny of it goes.

    The caller holds the agent's row. The entries that name the agent are locked next, in the
    order of their ids, and only then are their agent rows deleted: the order `PATCH`, `DELETE`
    and a deny take (entry, then its agent rows), so neither waits on the other in a cycle. No
    entry can come to name the agent meanwhile, since a write naming it holds its row shared."""
    c, g = t.chat_access.c, t.chat_access_agent.c
    named = set(conn.execute(select(g.entry_id).where(g.agent_id == agent_id)).scalars())
    subject = set(conn.execute(select(c.id).where(c.subject_agent_id == agent_id)).scalars())
    if named | subject:
        conn.execute(
            select(c.id).where(c.id.in_(named | subject)).order_by(c.id).with_for_update()
        ).all()
    conn.execute(delete(t.chat_access_agent).where(g.agent_id == agent_id))
    _drop(conn, sorted(subject))
    _prune(conn, sorted(named - subject))


# Reads ---------------------------------------------------------------------------------------


def _row(conn: Connection, me: str, kind: str, entry_id: str, *, lock: bool = False) -> Any:
    c = t.chat_access.c
    query = select(t.chat_access).where(c.id == entry_id, c.human_id == me, c.kind == kind)
    if lock:
        query = query.with_for_update()
    found = conn.execute(query).first()
    if found is None:
        raise not_found()
    return found


def listing(conn: Connection, me: str, agent: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """`GET /me/chat-access`: `{allow, deny}`, newest first; with `agent` only the entries
    that cover that agent (its own `agents`, or all of them)."""
    c, g = t.chat_access.c, t.chat_access_agent.c
    query = select(t.chat_access).where(c.human_id == me)
    if agent is not None:
        listed = (
            select(g.entry_id)
            .where(g.entry_id == c.id, g.side == OWN, g.agent_id == agent)
            .exists()
        )
        query = query.where(or_(c.agents_all.is_(True), listed))
    rows = conn.execute(query.order_by(c.since.desc(), c.id.desc())).all()
    views = render(conn, rows)
    return {
        ALLOW: [v for r, v in zip(rows, views, strict=True) if r.kind == ALLOW],
        DENY: [v for r, v in zip(rows, views, strict=True) if r.kind == DENY],
    }


def one(conn: Connection, me: str, kind: str, entry_id: str) -> dict[str, Any]:
    return render(conn, [_row(conn, me, kind, entry_id)])[0]


def replayed(conn: Connection, entry_id: str) -> dict[str, Any]:
    """An entry as it is now, for the replay of an `Idempotency-Key` (§1.5): the key is the
    caller's own, so the entry is read by its id alone. An entry deleted since (by `DELETE`, a
    deny or an agent's deletion) answers `not_found`, not the first call's status."""
    found = conn.execute(select(t.chat_access).where(t.chat_access.c.id == entry_id)).first()
    if found is None:
        raise not_found()
    return render(conn, [found])[0]


def render(conn: Connection, rows: Sequence[Any]) -> list[dict[str, Any]]:
    """The entries as §9.6 shows them."""
    ids = [r.id for r in rows]
    g = t.chat_access_agent.c
    agents: dict[tuple[str, str], list[str]] = {}
    if ids:
        for a in conn.execute(
            select(g.entry_id, g.side, g.agent_id)
            .where(g.entry_id.in_(ids))
            .order_by(g.entry_id, g.side, g.agent_id)
        ):
            agents.setdefault((a.entry_id, a.side), []).append(a.agent_id)
    humans = {r.owner_id for r in rows} | {r.subject_human_id for r in rows}
    handles = _handles(conn, {h for h in humans if h is not None})
    projects = {r.project_id for r in rows if r.project_id is not None}
    names = namespace.full_names(conn, projects) if projects else {}
    out = []
    for r in rows:
        view: dict[str, Any] = {
            "id": r.id,
            "agents": ALL if r.agents_all else agents.get((r.id, OWN), []),
        }
        if r.project_id is not None:
            owner, slug = names[r.project_id].split("/", 1)
            project: Any = {"owner": owner, "slug": slug}
        else:
            project = None
        if r.kind == ALLOW:
            view.update(
                owner_id=r.owner_id,
                handle=handles.get(r.owner_id) if r.owner_id else None,
                their_agents=(
                    agents.get((r.id, THEIRS), []) if r.their_agents == LIST else r.their_agents
                ),
                their_human=r.their_human,
                project=project,
                duration=r.duration,
                until=ts(r.until) if r.until is not None else None,
                allowed=r.allowed,
                denied=r.denied,
            )
        elif r.owner_id is not None:
            view.update(owner_id=r.owner_id, handle=handles.get(r.owner_id))
        elif r.subject_human_id is not None:
            view.update(human_id=r.subject_human_id, handle=handles.get(r.subject_human_id))
        elif r.subject_agent_id is not None:
            view["agent_id"] = r.subject_agent_id
        else:
            view["project"] = project
        view.update(by=r.by, since=ts(r.since))
        out.append(view)
    return out


def _handles(conn: Connection, human_ids: set[str]) -> dict[str, str]:
    if not human_ids:
        return {}
    h = t.human.c
    return {
        row.id: row.handle
        for row in conn.execute(select(h.id, h.handle).where(h.id.in_(human_ids)))
    }


def exported(conn: Connection, human_id: str) -> dict[str, list[dict[str, Any]]]:
    """The owner's entries for the export (§2.9, §9.6 "Records"): `{allow, deny}`, oldest
    first."""
    listed = listing(conn, human_id)
    return {kind: list(reversed(items)) for kind, items in listed.items()}
