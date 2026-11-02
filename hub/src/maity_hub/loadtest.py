"""The load test's accounts (hub/context/replicas.md cac80c88): `maity-hub loadtest seed` and
`maity-hub loadtest purge`, run where the hub runs, against the hub's own database.

Every account is named `lt-<n>` and has `NO_PASSWORD` for a password hash. The name alone does not
tell the seed's accounts: `lt-<n>` is not reserved, and a real account may be called `lt-7`, but its
hash is always a scrypt one, so `purge` asks for both. Each is a human with its own project
`lt-<n>/load` and two agents in it, signed in: the output holds a session cookie per human and a
signing key per agent, which is what `loadtest/run.js` reads.
A human has no mail address, so nothing the run does can send a mail.

Directly in the database, not through the API: the API's limits on logins and on agents per human
are what the run measures, and seeding through it would have to lift them. The rows are the ones
the routes write, through the same helpers where there are any.

A hub is seeded only when the operator names it: `LOADTEST_CONFIRMED_TEST_SYSTEM` names the host of
`MAITY_PUBLIC_URL`; for a host under `maity.team`, which may be production, only
`LOADTEST_CONFIRMED_PRODUCTION` does.

`purge` deletes every row of those accounts, in every table, in one transaction: the humans, their
projects and agents, and every row that refers to them by a foreign key, followed until nothing new
turns up, plus the few tables that name an account without one (`BY_VALUE`). It is refused when an
account is not the seed's alone, so that nothing of anyone else's goes with it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Column, Connection, Engine, Table, and_, delete, insert, select, update

from maity_hub import clock, handle_register, handles, namespace, policy, rules, setup_cards
from maity_hub import tables as t
from maity_hub.auth import credentials, sessions
from maity_hub.db import metadata
from maity_hub.ids import new_id

PREFIX = "lt-"
SLUG = "load"
AGENTS_PER_HUMAN = 2
PRODUCTION = "maity.team"
# Not a scrypt hash: `passwords.verify_password` answers False for it, so no one signs in with it,
# and no real account has it, so it marks the seed's accounts for `purge`.
NO_PASSWORD = "loadtest"


def refusal(public_url: str, test_system: str | None, production: str | None) -> str | None:
    """Why this hub is not seeded, or None. The host is the one of the hub's own public URL, so
    the name the operator gives is checked against where the command runs."""
    host = (urlsplit(public_url).hostname or "").lower()
    if not host:
        return "MAITY_PUBLIC_URL names no host"
    if host == PRODUCTION or host.endswith(f".{PRODUCTION}"):
        if production != host:
            return f"{host} may be production: LOADTEST_CONFIRMED_PRODUCTION does not name it"
        return None
    if test_system != host:
        return f"LOADTEST_CONFIRMED_TEST_SYSTEM does not name {host}"
    return None


def first_free(engine: Engine) -> int:
    """The next number after every `lt-<n>` handle, so a second seed adds accounts."""
    with engine.connect() as conn:
        taken = conn.execute(select(t.human.c.handle).where(t.human.c.handle.like(f"{PREFIX}%")))
        numbers = (h.removeprefix(PREFIX) for (h,) in taken)
        return 1 + max((int(n) for n in numbers if n.isdigit()), default=-1)


def seed_one(engine: Engine, n: int) -> dict[str, Any]:
    """One human `lt-<n>` with its project and agents, in one transaction; what `run.js` needs."""
    handle = f"{PREFIX}{n}"
    now = clock.now()
    with engine.begin() as conn:
        human_id = new_id("human")
        handles.lock(conn, handles.HUMANS, handle)
        conn.execute(
            insert(t.human).values(
                id=human_id,
                handle=handle,
                display_name=f"Load test {n}",
                password_hash=NO_PASSWORD,
                created_at=now,
            )
        )
        if not handle_register.claim(conn, handle, handle_register.HUMAN, human_id):
            raise RuntimeError(f"the handle {handle} is taken")
        project_id = new_id("project")
        conn.execute(
            insert(t.project).values(
                id=project_id,
                **namespace.owner_values(human_id),
                slug=SLUG,
                name="Load test",
                state="build",
                state_changed_at=now,
                keep_the_why=False,
                setup=setup_cards.stored(setup_cards.parse(None, False)),
                public_page="off",
                **policy.columns(policy.filled("hierarchical", human_id)),
                settings={"release_checklist": []},
                rules_version=1,
                rules_text_digest=rules.text_digest(),
                created_at=now,
            )
        )
        conn.execute(
            insert(t.membership).values(
                project_id=project_id,
                human_id=human_id,
                trust="owner",
                role="coder",
                role_base="coder",
                areas=["/"],
                capabilities=[],
                joined_at=now,
            )
        )
        agents = []
        for k in range(AGENTS_PER_HUMAN):
            agent_id = new_id("agent")
            conn.execute(
                insert(t.agent_profile).values(
                    id=agent_id,
                    owner_id=human_id,
                    handle=f"agent-{k}",
                    display_name=f"Load test {n} agent {k}",
                    created_at=now,
                )
            )
            result = conn.execute(
                insert(t.membership).values(
                    project_id=project_id,
                    agent_id=agent_id,
                    trust="member",
                    role="coder",
                    role_base="coder",
                    areas=["/"],
                    capabilities=[],
                    joined_at=now,
                )
            )
            key = result.inserted_primary_key
            assert key is not None
            membership_id = int(key[0])
            credential_id = new_id("credential")
            _, verifier = credentials.issue(credential_id)
            conn.execute(
                insert(t.credential).values(
                    id=credential_id,
                    membership_id=membership_id,
                    instance=f"lt{k}a",
                    verifier=verifier,
                    created_at=now,
                )
            )
            conn.execute(
                insert(t.agent_session).values(
                    id=new_id("session"),
                    credential_id=credential_id,
                    membership_id=membership_id,
                    harness="k6",
                    started_at=now,
                    last_seen_at=now,
                    acknowledged_seq=0,
                    live=True,
                )
            )
            agents.append(
                {"agent_id": agent_id, "credential_id": credential_id, "verifier": verifier}
            )
        cookie, _, _ = sessions.create(
            conn, human_id, method="password", address="192.0.2.1", user_agent="k6"
        )
    return {"handle": handle, "owner": handle, "slug": SLUG, "session": cookie, "agents": agents}


def seed(engine: Engine, humans: int, out: Path) -> int:
    """Seed `humans` accounts and write them to `out`, a new file only its owner reads. What an
    interrupted seed made is written too: still usable, and still found by the prefix."""
    start = first_free(engine)
    descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    made: list[dict[str, Any]] = []
    try:
        for n in range(humans):
            made.append(seed_one(engine, start + n))
    finally:
        with os.fdopen(descriptor, "w") as file:
            json.dump(made, file)
    return len(made)


# ----- purge -----------------------------------------------------------------------------------

HANDLE = re.compile(rf"{re.escape(PREFIX)}[0-9]+")
CHUNK = 500
# What the seed's accounts are; every row that refers to one of these goes with them.
ANCHORS = ("human", "project", "agent_profile", "membership")
# Tables that name an account without a foreign key: the column, and whose ids it holds.
BY_VALUE = (
    ("handle_register", "owner_id", ("human", "agent_profile")),
    ("handle_change", "subject_id", ("human", "agent_profile")),
    ("avatar_image", "owner_id", ("human", "agent_profile")),
    ("public_page", "target_id", ("human", "project", "agent_profile")),
    ("idempotency_key", "caller", ("human", "agent_profile", "credential")),
    ("request_nonce", "credential_id", ("credential",)),
)


@dataclass
class Doomed:
    """The rows `purge` deletes, by table: each row as its primary key."""

    rows: dict[str, set[tuple[Any, ...]]] = field(default_factory=dict)

    def ids(self, table: str) -> set[Any]:
        """The single-column primary keys of a table's rows."""
        return {key[0] for key in self.rows.get(table, set())}

    def count(self) -> dict[str, int]:
        return {name: len(keys) for name, keys in sorted(self.rows.items()) if keys}


class Refused(Exception):
    """`purge` would touch something the seed did not make."""


def _chunks(values: set[Any]) -> list[list[Any]]:
    items = sorted(values, key=str)
    return [items[i : i + CHUNK] for i in range(0, len(items), CHUNK)]


def _key(table: Table, row: Any) -> tuple[Any, ...]:
    return tuple(row._mapping[c.name] for c in table.primary_key.columns)


def _select_in(conn: Connection, table: Table, column: Column[Any], values: set[Any]) -> list[Any]:
    found: list[Any] = []
    for chunk in _chunks(values):
        found.extend(conn.execute(select(table).where(column.in_(chunk))).all())
    return found


def find(conn: Connection) -> Doomed:
    """Every row that belongs to the `lt-<n>` accounts: the humans the seed made (the handle and
    `NO_PASSWORD`, since anyone may sign up as `lt-7` and a real account always has a hash), their
    projects and agents,
    the memberships in those projects, and, following every foreign key, each row that refers to
    one of them, until nothing new turns up. Refused when an account is not the seed's alone: a
    membership across the line in either direction, an organisation, or a row that refers to an
    account and also to someone else's."""
    humans = {
        str(id_)
        for id_, handle in conn.execute(
            select(t.human.c.id, t.human.c.handle).where(
                t.human.c.handle.like(f"{PREFIX}%"), t.human.c.password_hash == NO_PASSWORD
            )
        )
        if HANDLE.fullmatch(handle)
    }
    projects = set(
        conn.execute(select(t.project.c.id).where(t.project.c.owner_id.in_(humans))).scalars()
        if humans
        else []
    )
    agents = set(
        conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id.in_(humans))
        ).scalars()
        if humans
        else []
    )
    memberships: set[int] = set()
    for row in _select_in(conn, t.membership, t.membership.c.project_id, projects):
        if not (row.human_id in humans or row.agent_id in agents):
            raise Refused(f"project {row.project_id} has a member that is not a load test account")
        memberships.add(int(row.id))
    for column, mine in ((t.membership.c.human_id, humans), (t.membership.c.agent_id, agents)):
        for row in _select_in(conn, t.membership, column, mine):
            if row.project_id not in projects:
                raise Refused(f"a load test account is a member of project {row.project_id}")
    if _select_in(conn, t.org_member, t.org_member.c.human_id, humans):
        raise Refused("a load test account is a member of an organisation")
    doomed = Doomed(
        {
            "human": {(h,) for h in humans},
            "project": {(p,) for p in projects},
            "agent_profile": {(a,) for a in agents},
            "membership": {(m,) for m in memberships},
        }
    )
    tables = list(metadata.tables.values())
    grew = True
    while grew:
        grew = False
        for table in tables:
            for fk in table.foreign_keys:
                target = fk.column.table
                referenced = {key[0] for key in doomed.rows.get(target.name, set())}
                if not referenced or len(target.primary_key.columns) != 1:
                    continue
                if fk.column is not list(target.primary_key.columns)[0]:
                    continue
                keys = doomed.rows.setdefault(table.name, set())
                for row in _select_in(conn, table, fk.parent, referenced):
                    key = _key(table, row)
                    if key not in keys:
                        _only_ours(table, row, doomed)
                        keys.add(key)
                        grew = True
    for name, column_name, kinds in BY_VALUE:
        named = metadata.tables[name]
        values = set().union(*(doomed.ids(kind) for kind in kinds))
        rows = _select_in(conn, named, named.c[column_name], values)
        doomed.rows.setdefault(name, set()).update(_key(named, row) for row in rows)
    names = {row.handle for row in _select_in(conn, t.human, t.human.c.id, doomed.ids("human"))}
    locks = _select_in(conn, t.handle_lock, t.handle_lock.c.handle, names)
    doomed.rows.setdefault("handle_lock", set()).update(
        _key(t.handle_lock, row) for row in locks if row.scope == handles.HUMANS
    )
    return doomed


def _only_ours(table: Table, row: Any, doomed: Doomed) -> None:
    """A row that refers to an account must not refer to anyone else's: deleting it would take
    something of theirs with it."""
    if table.name in ANCHORS:
        raise Refused(f"{table.name} {_key(table, row)} refers to a load test account")
    for fk in table.foreign_keys:
        target = fk.column.table.name
        value = row._mapping[fk.parent.name]
        if target in ANCHORS and value is not None and value not in doomed.ids(target):
            raise Refused(f"a row of {table.name} refers to a load test account and to {value}")


def delete_all(conn: Connection, doomed: Doomed) -> None:
    """Delete what `find` found, children before parents. A foreign key on a cycle of the tables
    (credential, join link and placement refer to each other) is nullable; on the rows that go it
    is set to null first, which breaks the cycle."""
    tables = {name: metadata.tables[name] for name, keys in doomed.rows.items() if keys}
    refers = {  # table → the tables it refers to, among those that lose rows
        name: {fk.column.table.name for fk in table.foreign_keys} & set(tables)
        for name, table in tables.items()
    }

    def reaches(start: str, goal: str) -> bool:
        seen, todo = set(), [start]
        while todo:
            here = todo.pop()
            if here == goal:
                return True
            if here not in seen:
                seen.add(here)
                todo.extend(refers[here])
        return False

    cut: set[tuple[str, str]] = set()  # (table, column) set to null first
    for name, table in tables.items():
        for fk in table.foreign_keys:
            target = fk.column.table.name
            if target in tables and reaches(target, name):
                if not fk.parent.nullable:
                    raise Refused(f"{name}.{fk.parent.name} is on a cycle and cannot be null")
                cut.add((name, fk.parent.name))
    for name, column in sorted(cut):
        table = tables[name]
        _each(conn, table, doomed.rows[name], _nulling(table, column))
    after = {  # a table goes after every other table that still refers to it
        name: {
            other
            for other, table_ in tables.items()
            for fk in table_.foreign_keys
            if fk.column.table.name == name and other != name and (other, fk.parent.name) not in cut
        }
        for name in tables
    }
    gone: set[str] = set()
    while len(gone) < len(tables):
        ready = sorted(name for name in tables if name not in gone and after[name] <= gone)
        if not ready:
            raise Refused(f"no order to delete {sorted(set(tables) - gone)}")
        for name in ready:
            _each(conn, tables[name], doomed.rows[name], _deleting(tables[name]))
            gone.add(name)


def _nulling(table: Table, column: str) -> Any:
    return lambda where: update(table).where(where).values({table.c[column]: None})


def _deleting(table: Table) -> Any:
    return lambda where: delete(table).where(where)


def _each(conn: Connection, table: Table, keys: set[tuple[Any, ...]], statement: Any) -> None:
    """Run `statement(where)` over `keys` in chunks."""
    pk = list(table.primary_key.columns)
    if len(pk) == 1:
        for chunk in _chunks({k[0] for k in keys}):
            conn.execute(statement(pk[0].in_(chunk)))
    else:
        for key in keys:
            conn.execute(statement(_match(table, key)))


def _match(table: Table, key: tuple[Any, ...]) -> Any:
    return and_(*(c == v for c, v in zip(table.primary_key.columns, key, strict=True)))


def purge(engine: Engine, *, change: bool) -> dict[str, int]:
    """Find, and with `change` delete, every row of the `lt-<n>` accounts in one transaction;
    the count per table either way."""
    with engine.begin() as conn:
        doomed = find(conn)
        if change:
            delete_all(conn, doomed)
    return doomed.count()
