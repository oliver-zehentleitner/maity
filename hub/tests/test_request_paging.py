"""A project's request list pages in SQL (docs/api.md §1.4, §7; tsk-ybc2ma72dzvq item 4).

`routes/requests.py` `_project_page` reads the plain requests' keys in the database
(`request_sql`), the others with the columns the Python rule needs, and only the page's rows in
full. These hold it to the readable rule, `_page` over `_sorted(_entries(_filtered(…)))`, page by
page: the items and the cursor, for every kind of caller, `to`, sort, status and page size."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.db import read_transaction
from maity_hub.routes import requests as requests_route
from maity_hub.routes.requests import (
    _entries,
    _filtered,
    _key,
    _next_cursor,
    _page,
    _project_page,
    _render,
    _sorted,
)
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import count_statements
from tests.test_overview import (
    LEFTOVER_KINDS,
    Person,
    jour_fixe_rounds,
    person,
    seed_requests,
)
from tests.test_requests import asked

PROJECT = "/projects/maintainer/maity"
SORTS = ("priority", "date", "agent")
STATUSES = ("open", "all")
LIMITS = (1, 7, 200)
SEEDED = 140


def _cursor(value: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _membership(conn: Connection, who: Person) -> Membership:
    row = conn.execute(select(t.membership).where(t.membership.c.id == who.membership)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    return Membership(project, row, "agent" if row.agent_id else "human")


@dataclass
class Listing:
    """One caller's list for one `to`, sort and status, through both paths."""

    conn: Connection
    mine: Membership
    to: str
    sort: str
    status: str
    class_: str | None = None
    asked_by: str | None = None

    def __post_init__(self) -> None:
        rows = _filtered(
            self.conn,
            self.mine,
            status=self.status,
            class_=self.class_,
            asked_by=self.asked_by,
            to=self.to,
        )
        self.entries = _sorted(_entries(self.conn, rows), self.sort)

    def oracle(self, limit: int, cursor: str | None) -> dict[str, Any]:
        """`_page` as the route called it before, on a fresh copy of the sorted entries."""
        entries = [dict(e) for e in self.entries]
        return _page(entries, self.sort, limit, cursor, _render(self.conn))

    def paged(self, limit: int, cursor: str | None) -> dict[str, Any]:
        return _project_page(
            self.conn,
            self.mine,
            status=self.status,
            class_=self.class_,
            asked_by=self.asked_by,
            to=self.to,
            sort=self.sort,
            limit=limit,
            cursor=cursor,
        )

    def walk(self, limit: int) -> Iterator[str]:
        """Every page, the new path against the oracle with the same cursor; the ids shown."""
        cursor: str | None = None
        for _ in range(len(self.entries) + 2):
            old, new = self.oracle(limit, cursor), self.paged(limit, cursor)
            where = (self.to, self.sort, self.status, self.class_, self.asked_by, limit, cursor)
            assert new["next_cursor"] == old["next_cursor"], where
            assert new["items"] == old["items"], where
            yield from (item["id"] for item in new["items"])
            cursor = new["next_cursor"]
            if cursor is None:
                return
        raise AssertionError(f"no last page: {where}")


@dataclass
class Seeded:
    callers: dict[str, Any]
    people: dict[str, Person]
    agent: flow.Agent
    project_id: str

    def tos(self) -> tuple[str, ...]:
        """Every kind of `to` a listing takes: me, all, the owner, a role, a trust token, a
        member alone and one instance of it."""
        return (
            "me",
            "all",
            "owner",
            "role:coder",
            "trust:admin",
            self.agent.id,
            f"{self.agent.id}#{self.agent.instance}",
        )


def _seed(owner: flow.Human, make_client: ClientFactory, engine: Engine) -> Seeded:
    """test_overview's callers and requests, plus what the order needs: requests that tie on
    `created_at` and priority (the id decides), a deleted asker, an inviter as the asker, no
    asker at all (an empty handle), instance addresses and a personal request."""
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    admin_human = flow.human(make_client, engine, "ada")
    factory.membership(engine, project_id, role="admin", human_id=admin_human.id)
    member_human = flow.human(make_client, engine, "mia")
    factory.membership(engine, project_id, role="member", human_id=member_human.id)
    guest_human = flow.human(make_client, engine, "gus")
    factory.membership(engine, project_id, role="guest", human_id=guest_human.id)
    agent = flow.agent(make_client, owner)
    callers: dict[str, Any] = {
        "owner": owner,
        "admin": admin_human,
        "member": member_human,
        "guest": guest_human,
        "agent": agent,
        "reviewer": flow.agent(make_client, owner, role="reviewer"),
        "admin_agent": flow.agent(make_client, owner, role="admin"),
        "proxy": flow.agent(make_client, owner, role="proxy"),
        "guest_agent": flow.agent(make_client, owner, role="guest"),
    }
    people = {name: person(engine, who.id) for name, who in callers.items()}
    gone = factory.human(engine, "gone")
    gone_member = factory.membership(engine, project_id, role="member", human_id=gone)
    inviter = factory.human(engine, "ivy")
    template = agent.post(
        f"{PROJECT}/requests", {"class": "decision", "title": "Which?", "to": "owner"}
    )
    assert template.status_code == 201, template.text
    seed_requests(
        engine,
        template.json()["id"],
        list(people.values()),
        jour_fixe_rounds(engine, project_id),
        count=SEEDED,
    )
    r = t.request.c
    with engine.begin() as conn:
        rows = conn.execute(
            select(r.id, r.created_at, r.priority, r.to_kind, r.to_member).where(
                r.id.like("req-ovw%")
            )
        ).all()
        by_n = {int(row.id[len("req-ovw") :]): row for row in rows}
        to_agent = 0
        for n, row in sorted(by_n.items()):
            values: dict[str, Any] = {}
            if n % 6 in (1, 2, 3):  # three in a row tie: the id decides, in every sort
                first = by_n[n - n % 6 + 1]
                values.update(created_at=first.created_at, priority=first.priority)
            if row.to_kind == "member" and row.to_member == people["agent"].membership:
                # Counted over these rows alone: the agent's place in the 15 targets fixes n % 3.
                values["to_instance"] = (agent.instance, "zz99", None)[to_agent % 3]
                to_agent += 1
            if n % 4 == 2:  # another class, for the `class` filter
                values["class"] = "info"
            if n % 23 == 5:
                values.update(asked_by=gone_member, on_behalf_of=None)
            elif n % 23 == 9:
                values.update(asked_by=None, asked_by_human=inviter, on_behalf_of=None)
            elif n % 23 == 14:
                values.update(asked_by=None, asked_by_human=None, filed_by="hub")
            if values:
                conn.execute(update(t.request).where(r.id == row.id).values(**values))
        conn.execute(update(t.human).where(t.human.c.id == gone).values(deleted_at=clock.now()))
        template_row = conn.execute(select(t.request).where(r.id == template.json()["id"])).one()
        conn.execute(  # a personal request in the project: never in its listing (§7)
            insert(t.request).values(
                {
                    **template_row._mapping,
                    "id": "req-personal0001",
                    "personal": True,
                    "to_kind": "human",
                    "to_member": None,
                    "to_role": None,
                    "to_human": owner.id,
                    "created_at": clock.now() - timedelta(days=1),
                }
            )
        )
    return Seeded(callers, people, agent, project_id)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _kinds(conn: Connection) -> dict[str, str | None]:
    """The leftover kind of every request, as `seed_requests` names them; None for a plain one."""
    circles = dict(conn.execute(select(t.jour_fixe_round.c.id, t.jour_fixe_round.c.config)).all())
    r = t.request.c
    kinds: dict[str, str | None] = {}
    for row in conn.execute(select(r.id, r.cover, r.held, r.proposal, r.jour_fixe)):
        kind = None
        if row.cover:
            kind = "cover"
        elif row.held:
            kind = "held"
        elif row.proposal:
            kind = "proposal"
        elif row.jour_fixe:
            kind = f"jour_fixe_{circles[row.jour_fixe['round_id']]['circle']}"
        kinds[row.id] = kind
    return kinds


def test_every_page_is_the_listings_own_for_every_caller(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    seeded = _seed(owner, make_client, migrated)
    with migrated.connect() as conn:
        kinds = _kinds(conn)
        seen: set[str] = set()
        listed: dict[tuple[str, str, str], set[str]] = {}
        for name, who in seeded.people.items():
            mine = _membership(conn, who)
            for to in seeded.tos():
                for sort in SORTS:
                    for status in STATUSES:
                        listing = Listing(conn, mine, to, sort, status)
                        for limit in LIMITS:
                            shown = list(listing.walk(limit))
                            assert shown == [e["id"] for e in listing.entries], (name, to)
                            seen.update(shown)
                            listed[(name, to, status)] = set(shown)
    # The member alone lists what is addressed to any of its instances, the instance form only
    # its own: both seen, and they differ (`request_sql.addressed_as`' `whole_team`).
    agent = seeded.agent
    whole = listed[("owner", agent.id, "all")]
    one = listed[("owner", f"{agent.id}#{agent.instance}", "all")]
    assert one and one < whole
    # Every kind the database leaves to the Python rule reached some caller's list, and so
    # did the ties, the inviter, the deleted asker and the request with no asker.
    assert {kinds[i] for i in seen} >= set(LEFTOVER_KINDS)
    assert "req-personal0001" not in seen
    assert {f"req-ovw{n:08d}" for n in (5, 9, 14, 1, 2, 3)} <= seen


def test_the_class_and_asker_filters_page_as_the_listing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`class` and `asked_by` beside `to`: a few of each, not the whole product."""
    seeded = _seed(owner, make_client, migrated)
    agent = seeded.agent.id
    filters = [
        ("info", None),
        ("decision", None),
        (None, "me"),
        (None, agent),
        ("info", agent),
        (None, "agt-nobody00000"),  # no member: nothing listed
    ]
    with migrated.connect() as conn:
        for class_, asked_by in filters:
            found = 0
            for name in ("owner", "agent", "proxy"):
                mine = _membership(conn, seeded.people[name])
                for to in ("me", "all", agent):
                    for sort in SORTS:
                        listing = Listing(conn, mine, to, sort, "all", class_, asked_by)
                        for limit in (1, 7):
                            shown = list(listing.walk(limit))
                            assert shown == [e["id"] for e in listing.entries]
                            found += len(shown)
            assert (found > 0) == (asked_by != "agt-nobody00000"), (class_, asked_by)


# Under READ COMMITTED a request can change between statement A (the plain keys) and B (the
# others). These change one between them, on the listing's own connection, which both read.
# A plain request that gets a `cover` or a `held` is read by both: it is listed once, at B's key.
# One that loses them, or is forwarded or answered, is read by at most one of them.
DUPLICATED = ("cover_set", "held_set", "cover_and_priority")


@pytest.mark.parametrize(
    "change",
    [*DUPLICATED, "cover_cleared", "held_cleared", "forward", "answer"],
)
def test_a_request_that_changes_between_the_statements_is_listed_once(
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    made = [asked(agent, to="owner", title=f"Which {n}?")["id"] for n in range(4)]
    cover = {"for": owner.id, "by": agent.id, "since": clock.rfc3339(clock.now())}
    changes: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {  # (before A, between)
        "cover_set": ({}, {"cover": cover}),
        "held_set": ({}, {"held": [agent.id]}),
        # The key moves too (priority sort): B's place, not A's, is the one listed.
        "cover_and_priority": ({}, {"cover": cover, "priority": "urgent"}),
        "cover_cleared": ({"cover": cover}, {"cover": None}),
        "held_cleared": ({"held": [agent.id]}, {"held": None}),
        "forward": ({}, {"holder_member": person(migrated, agent.id).membership}),
        "answer": ({}, {"status": "answered"}),
    }
    before, between = changes[change]
    original = requests_route._leftover_batches
    r = t.request.c
    checked = 0
    with migrated.connect() as conn:
        mine = _membership(conn, person(migrated, owner.id))
        for sort in SORTS:
            for limit in (1, 2, 5):
                for changed in made:
                    if before:
                        conn.execute(update(t.request).where(r.id == changed).values(**before))

                    def hooked(size: int, changed: str = changed) -> Iterator[int]:
                        # Runs after A read its keys, before B's first batch.
                        conn.execute(update(t.request).where(r.id == changed).values(**between))
                        yield from original(size)

                    monkeypatch.setattr(requests_route, "_leftover_batches", hooked)
                    page = Listing(conn, mine, "all", sort, "open").paged(limit, None)
                    monkeypatch.setattr(requests_route, "_leftover_batches", original)
                    where = (change, sort, limit, changed)
                    ids = [item["id"] for item in page["items"]]
                    assert len(ids) == len(set(ids)) <= limit, where
                    if change == "answer":  # decided again on the row read in full
                        assert changed not in ids, where
                    # The last item's place as it is now; a page a row left on the full read
                    # is shorter and keeps the cursor of the keys.
                    if page["next_cursor"] is not None and len(ids) == limit:
                        last = conn.execute(select(t.request).where(r.id == ids[-1])).one()
                        key = _key(_entries(conn, [last])[0], sort)
                        assert page["next_cursor"] == _next_cursor(sort, key), where
                    if change in (*DUPLICATED, "forward"):  # the list as it is after the change
                        after = Listing(conn, mine, "all", sort, "open").oracle(limit, None)
                        assert page == after, where
                    conn.rollback()
                    checked += 1
    assert checked == len(SORTS) * 3 * len(made)


def _walk_with_change(listing: Listing, values: dict[str, Any]) -> bool:
    """Page 1, then `values` written to a request of page 2, then page 2 and on, each against
    the oracle with the same cursor, the oracle's list read again after the change. False
    when the list has no second page to change."""
    first_old, first_new = listing.oracle(7, None), listing.paged(7, None)
    assert first_new == first_old
    cursor = first_new["next_cursor"]
    if cursor is None:
        return False
    second = listing.oracle(7, cursor)["items"]
    changed = second[len(second) // 2]["id"]
    listing.conn.execute(update(t.request).where(t.request.c.id == changed).values(**values))
    listing.__post_init__()
    while cursor is not None:
        old, new = listing.oracle(7, cursor), listing.paged(7, cursor)
        assert new == old, (listing.to, listing.sort, cursor)
        cursor = new["next_cursor"]
    listing.conn.rollback()
    return True


@pytest.mark.parametrize("change", ["answer", "forward", "hold", "cover"])
def test_a_request_that_changes_between_pages(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, change: str
) -> None:
    people = _seed(owner, make_client, migrated).people
    substitute = {
        "for": people["owner"].principal,
        "by": people["agent"].principal,
        "since": clock.rfc3339(clock.now()),
    }
    changes: dict[str, dict[str, Any]] = {
        "answer": {"status": "answered"},
        "forward": {"holder_member": people["reviewer"].membership},
        "hold": {"held": [people["agent"].principal]},
        "cover": {"cover": substitute},
    }
    values = changes[change]
    walked = 0
    with migrated.connect() as conn:
        for name, to in (("owner", "all"), ("agent", "me"), ("agent", "all"), ("admin", "owner")):
            for sort in SORTS:
                listing = Listing(conn, _membership(conn, people[name]), to, sort, "open")
                walked += _walk_with_change(listing, values)
    assert walked >= 6


# The page's keys are read before its rows are read in full: on PostgreSQL every statement of
# `read_transaction` has its own snapshot (READ COMMITTED), so a row can change in between.
# The rows read in full are decided again, by `_decided` and the listing's own filters. Each
# case: (caller, to, status, the request's values before the listing, the change in between).
REDECIDED: dict[str, tuple[str, str, str, dict[str, Any], dict[str, Any]]] = {
    "forwarded_on": ("x", "all", "open", {"holder_member": "x"}, {"holder_member": "z"}),
    "cover_ended": ("x", "all", "open", {"cover": "x"}, {"cover": None}),
    "substitute_changed": ("x", "all", "open", {"cover": "x"}, {"cover": "z"}),
    "answered": ("owner", "all", "open", {}, {"status": "answered"}),
    "addressed_elsewhere": ("owner", "x", "all", {}, {"to_member": "z"}),
    "addressed_elsewhere_me": ("x", "me", "all", {}, {"to_member": "z"}),
}


@pytest.mark.parametrize("own_connection", [True, False], ids=["same_connection", "committed"])
@pytest.mark.parametrize("change", list(REDECIDED))
def test_the_rows_read_in_full_are_decided_again(
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    own_connection: bool,
) -> None:
    """`same_connection` writes on the listing's own connection, which the full read sees on
    every database. `committed` writes from another connection and commits: the full read
    sees it on PostgreSQL; SQLite reads one snapshot per read transaction, so there the page
    is the one from before the change."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agents = {name: flow.agent(make_client, owner) for name in ("x", "y", "z")}
    members = {name: person(migrated, a.id).membership for name, a in agents.items()}
    for n in range(3):  # what x lists in any case: it asked them
        asked(agents["x"], to="owner", title=f"Mine {n}?")
    changed = asked(agents["y"], to=agents["x"].id, title="Which?")["id"]
    caller, to, status, before, between = REDECIDED[change]
    to = agents[to].id if to in agents else to

    def values(names: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for column, name in names.items():
            if column == "cover" and name is not None:
                out[column] = {
                    "for": owner.id,
                    "by": agents[name].id,
                    "since": clock.rfc3339(clock.now()),
                }
            elif column in ("holder_member", "to_member") and name is not None:
                out[column] = members[name]
            else:
                out[column] = name
        return out

    r = t.request.c
    if change.startswith(("forwarded", "cover", "substitute")):  # addressed to the owner
        before = {**before, "to_kind": "owner", "to_member": None}
    with migrated.begin() as conn:
        if before:
            conn.execute(update(t.request).where(r.id == changed).values(**values(before)))
        restore = dict(
            conn.execute(select(*(r[c] for c in between)).where(r.id == changed)).one()._mapping
        )
    who = owner.id if caller == "owner" else agents[caller].id
    original = requests_route._read_in_full

    def write(conn: Connection, row_values: dict[str, Any]) -> None:
        conn.execute(update(t.request).where(r.id == changed).values(**row_values))

    for sort in SORTS:
        with migrated.connect() as conn:
            mine = _membership(conn, person(migrated, who))
            earlier = Listing(conn, mine, to, sort, status)
            assert changed in [e["id"] for e in earlier.entries], (change, sort)
            before_page = earlier.oracle(10, None)

        def hooked(conn: Connection, ids: list[str], listed: list[Any]) -> list[Any]:
            # After the keys are read (statements A and B), before the full read.
            if own_connection:
                write(conn, values(between))
            else:
                with migrated.begin() as other:
                    write(other, values(between))
            return original(conn, ids, listed)

        monkeypatch.setattr(requests_route, "_read_in_full", hooked)
        if own_connection:
            with migrated.connect() as conn:
                page = Listing(conn, mine, to, sort, status).paged(10, None)
                later = Listing(conn, mine, to, sort, status).oracle(200, None)
                conn.rollback()
        else:
            with read_transaction(migrated) as conn:
                page = Listing(conn, mine, to, sort, status).paged(10, None)
            with migrated.connect() as conn:
                later = Listing(conn, mine, to, sort, status).oracle(200, None)
            with migrated.begin() as conn:
                write(conn, restore)
        monkeypatch.setattr(requests_route, "_read_in_full", original)
        where = (change, sort, own_connection)
        if not own_connection and migrated.dialect.name == "sqlite":
            assert page == before_page, where
            continue
        # Only what the listing holds after the change, each item as it shows it now.
        listed = {item["id"]: item for item in later["items"]}
        assert changed not in listed, where
        for item in page["items"]:
            assert item == listed.get(item["id"]), where


# Handles a locale collation orders apart from their bytes: it may pass over `-` (`a-cd` after
# `abc`, `b-x` after `bb`). `handles.FORMAT` takes no upper case, so case is not among them.
BYTEWISE = ("a-1", "a-ab", "a-cd", "aab", "abc", "b-x", "bb", "zz-top")


def test_the_agent_sort_orders_handles_by_their_bytes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`_order` compares the asker's handle bytewise (`collate("C")` on PostgreSQL), as
    `_sorted` compares it in Python: every page of `sort=agent` is the listing's own."""
    agent = flow.agent(make_client, owner)
    template_id = asked(agent, to="owner")["id"]
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    members = {
        handle: factory.membership(
            migrated, project_id, role="member", human_id=factory.human(migrated, handle)
        )
        for handle in reversed(BYTEWISE)
    }
    r = t.request.c
    with migrated.begin() as conn:
        template = conn.execute(select(t.request).where(r.id == template_id)).one()
        conn.execute(
            insert(t.request),
            [
                {
                    **template._mapping,
                    "id": f"req-bytewise{n:04d}",
                    "asked_by": member,
                    "on_behalf_of": None,
                    "created_at": template.created_at - timedelta(minutes=n),
                }
                for n, member in enumerate(members.values())
            ],
        )
    by_id = {f"req-bytewise{n:04d}": handle for n, handle in enumerate(members)}
    with migrated.connect() as conn:
        mine = _membership(conn, person(migrated, owner.id))
        listing = Listing(conn, mine, "all", "agent", "all")
        for limit in (1, 2, 3, 200):
            shown = list(listing.walk(limit))
            assert [by_id[i] for i in shown if i in by_id] == list(BYTEWISE), limit


def test_a_cursor_the_hub_gave_before_still_pages(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The cursor keeps its `{"s", "k"}` and `k` as `_key` built it."""
    agent = flow.agent(make_client, owner)
    made = [asked(agent, to="owner", title=f"Which {n}?") for n in range(3)]
    with migrated.connect() as conn:
        rows = {row.id: row for row in conn.execute(select(t.request.c.id, t.request.c.created_at))}
    newest = rows[made[2]["id"]]
    old = _cursor({"s": "date", "k": [newest.created_at.isoformat(), newest.id]})
    page = owner.get(f"{PROJECT}/requests", params={"sort": "date", "cursor": old}).json()
    assert [i["id"] for i in page["items"]] == [made[1]["id"], made[0]["id"]]
    oldest = rows[made[0]["id"]]
    old = _cursor({"s": "priority", "k": [2, oldest.created_at.isoformat(), oldest.id]})
    page = owner.get(f"{PROJECT}/requests", params={"cursor": old}).json()
    assert [i["id"] for i in page["items"]] == [made[1]["id"], made[2]["id"]]


ISO = "2026-11-19T10:00:00+00:00"


@pytest.mark.parametrize(
    ("sort", "k"),
    [
        ("date", [1, "req-x"]),  # a 500 before (TypeError in `_page`'s comparison)
        ("date", [ISO, 7]),  # taken before: the first element decided
        ("priority", [ISO, 1, "req-x"]),  # a 500 before
        ("agent", [None, ISO, "req-x"]),  # a 500 before
        ("date", [ISO]),
        ("date", [ISO, "req-x", "more"]),
        ("date", {"at": ISO}),
        ("date", "req-x"),
        ("priority", [4, ISO, "req-x"]),
        ("priority", [-1, ISO, "req-x"]),
        ("priority", [True, ISO, "req-x"]),
        ("priority", [1.0, ISO, "req-x"]),
        ("date", ["2026-11-19T10:00:00", "req-x"]),  # no zone
        ("date", ["yesterday", "req-x"]),
        ("date", ["0001-01-01T00:00:00+14:00", "req-x"]),  # out of range in UTC
        ("date", [ISO + "\x00", "req-x"]),  # a NUL in the time: not bound, not parsed
        ("date", [ISO, ""]),
        ("date", [ISO, "x" * 41]),
        ("date", [ISO, "req-\x00"]),
        ("date", [ISO, "req-\ud800"]),  # a lone surrogate: JSON carries one
        ("agent", ["\ud800", ISO, "req-x"]),
        ("agent", [3, ISO, "req-x"]),
    ],
)
def test_a_cursor_key_of_the_wrong_shape_is_invalid(
    make_client: ClientFactory, migrated: Engine, sort: str, k: Any
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    asked(agent, to="owner")  # one request at least: the comparison ran only on one
    response = owner.get(
        f"{PROJECT}/requests", params={"sort": sort, "cursor": _cursor({"s": sort, "k": k})}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {"cursor": "invalid"}


@pytest.mark.parametrize(
    ("sort", "k"),
    [
        ("date", [1, "req-x"]),
        ("priority", [ISO, 1, "req-x"]),
        ("agent", [None, ISO, "req-x"]),
        ("date", [ISO, 7]),
    ],
)
def test_a_cursor_key_of_the_wrong_shape_is_invalid_across_projects(
    make_client: ClientFactory, migrated: Engine, sort: str, k: Any
) -> None:
    """`GET /requests` pages with `_page`, which reads the cursor with `_cursor_key` too."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    asked(agent, to="owner")
    response = owner.get("/requests", params={"sort": sort, "cursor": _cursor({"s": sort, "k": k})})
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid"
    assert error["details"]["fields"] == {"cursor": "invalid"}


def test_another_sorts_cursor_and_a_bad_to_are_answered_as_before(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    asked(agent, to="owner")
    malformed = _cursor({"s": "date", "k": "anything"})
    other = owner.get(f"{PROJECT}/requests", params={"cursor": malformed})
    assert other.json()["error"]["details"]["fields"] == {"cursor": "other_sort"}
    no_k = owner.get(f"{PROJECT}/requests", params={"cursor": _cursor({"s": "priority"})})
    assert no_k.json()["error"]["details"]["fields"] == {"cursor": "invalid"}
    # `to` is read before the cursor, and not at all for an asker who is no member.
    bad_to = owner.get(f"{PROJECT}/requests", params={"to": "role:nope", "cursor": malformed})
    assert bad_to.json()["error"]["details"]["fields"] == {"to": "unknown_role"}
    nobody = owner.get(
        f"{PROJECT}/requests", params={"to": "role:nope", "asked_by": "agt-nobody00000"}
    )
    assert nobody.status_code == 200 and nobody.json() == {"items": [], "next_cursor": None}
    refused = owner.get(
        f"{PROJECT}/requests",
        params={"to": "role:nope", "asked_by": "agt-nobody00000", "cursor": malformed},
    )
    assert refused.json()["error"]["details"]["fields"] == {"cursor": "other_sort"}


def test_requests_the_caller_cannot_see_past_the_page_cost_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Once the plain requests fill the page, the others are read only up to its last key:
    a pile of older requests held for the caller adds no statement."""
    agent = flow.agent(make_client, owner)
    ids = [asked(owner, to=agent.id, title=f"Which {n}?")["id"] for n in range(3)]
    path = f"{PROJECT}/requests?sort=date&limit=1"
    before = count_statements(migrated, lambda: agent.get(path), async_engines=False)
    with migrated.begin() as conn:
        template = conn.execute(select(t.request).where(t.request.c.id == ids[0])).one()
        conn.execute(
            insert(t.request),
            [
                {
                    **template._mapping,
                    "id": f"req-heldback{n:04d}",
                    "held": [agent.id],
                    "created_at": template.created_at - timedelta(days=1, minutes=n),
                }
                for n in range(60)
            ],
        )
    after = count_statements(migrated, lambda: agent.get(path), async_engines=False)
    assert after == before
    assert [i["id"] for i in agent.get(path).json()["items"]] == [ids[2]]
