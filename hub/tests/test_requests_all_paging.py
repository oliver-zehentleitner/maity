"""The cross-project inbox pages in SQL (docs/api.md §1.4, §7; tsk-ybc2ma72dzvq item 4).

`routes/requests.py` `_all_page` merges, by key, each membership's listing paged as the
project's list pages it (`_listing_keys`) and the personal inbox (`_personal_keys`), and reads
only the page's rows in full. These hold it to the readable rule, `_page` over
`_sorted(_all_entries(…))`, page by page: the items and the cursor, for a human with a
different trust and role in each of three projects and personal requests of their own, every
`to`, sort, status and page size."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, delete, insert, select, update

from maity_hub import clock, cross_owner
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.db import read_transaction
from maity_hub.inbox import PRIORITIES
from maity_hub.routes import requests as requests_route
from maity_hub.routes.requests import _all_entries, _all_page, _key, _page, _render, _sorted
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_overview import Person, jour_fixe_rounds, person, seed_requests
from tests.test_requests import asked

SORTS = ("priority", "date", "agent")
STATUSES = ("open", "all")
LIMITS = (1, 7, 200)
ISO = "2026-11-19T10:00:00+00:00"


def _cursor(value: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


@dataclass
class Inbox:
    """The caller's `GET /requests` for one `to`, sort, status and asker, through both paths."""

    conn: Connection
    caller: Caller
    to: str
    sort: str
    status: str
    asked_by: str | None = None

    def __post_init__(self) -> None:
        self.read()

    def read(self) -> None:
        views = _all_entries(
            self.conn,
            self.caller,
            status=self.status,
            class_=None,
            asked_by=self.asked_by,
            to=self.to,
        )
        self.entries = _sorted(views, self.sort)

    def oracle(self, limit: int, cursor: str | None) -> dict[str, Any]:
        """`_page` as the route called it before, on a fresh copy of the sorted entries."""
        entries = [dict(e) for e in self.entries]
        return _page(entries, self.sort, limit, cursor, _render(self.conn))

    def paged(self, limit: int, cursor: str | None) -> dict[str, Any]:
        return _all_page(
            self.conn,
            self.caller,
            status=self.status,
            class_=None,
            asked_by=self.asked_by,
            to=self.to,
            sort=self.sort,
            limit=limit,
            cursor=cursor,
        )

    def walk(self, limit: int) -> list[str]:
        """Every page, the new path against the oracle with the same cursor; the ids shown."""
        cursor: str | None = None
        shown: list[str] = []
        for _ in range(len(self.entries) + 2):
            old, new = self.oracle(limit, cursor), self.paged(limit, cursor)
            where = (self.to, self.sort, self.status, self.asked_by, limit, cursor)
            assert new["next_cursor"] == old["next_cursor"], where
            assert new["items"] == old["items"], where
            shown += [item["id"] for item in new["items"]]
            cursor = new["next_cursor"]
            if cursor is None:
                return shown
        raise AssertionError(f"no last page: {where}")


@dataclass
class Seeded:
    caller: Caller
    client: flow.Human
    projects: dict[str, str]  # name: project id
    dora: str  # a human member of beta and gamma, not of alpha
    agent: str  # an agent of alpha only
    personal: list[str]

    def tos(self) -> tuple[str, ...]:
        """`to` values valid in every project, in some, and in none (each project skipped)."""
        return ("me", "all", "owner", "role:coder", "trust:admin", self.dora, self.agent)


def _copy_template(engine: Engine, template_id: str, project_id: str, request_id: str) -> str:
    with engine.begin() as conn:
        row = conn.execute(select(t.request).where(t.request.c.id == template_id)).one()
        conn.execute(
            insert(t.request).values(
                {**row._mapping, "id": request_id, "project_id": project_id, "asked_by": None}
            )
        )
    return request_id


def _seed(make_client: ClientFactory, engine: Engine, count: int = 36) -> Seeded:
    """Three projects: `alpha`, the caller's own (trust owner); `beta`, bob's, where the
    caller is a member; `gamma`, bob's, where the caller is a proxy (trust admin, so a holder
    of `requests:answer` whose listing drops the bridge consent). Each seeded with
    test_overview's mix; beta's and gamma's times copied from alpha's, a third of them to the
    microsecond, so that requests of two projects tie and the id decides. Plus personal
    requests: to the caller, with and without a project, a cross-owner one the caller asked,
    and ones that are not the caller's."""
    owner = flow.human(make_client, engine)
    flow.project(owner, "alpha")
    agent = flow.agent(make_client, owner, "alpha")
    flow.agent(make_client, owner, "alpha", role="reviewer")
    flow.agent(make_client, owner, "alpha", role="proxy")
    bob = factory.human(engine, "bob")
    dora = factory.human(engine, "dora")
    with engine.connect() as conn:
        alpha = conn.execute(select(t.project.c.id).where(t.project.c.slug == "alpha")).scalar_one()
    body = {"class": "decision", "title": "Which?"}
    template = agent.post("/projects/maintainer/alpha/requests", body)
    assert template.status_code == 201, template.text
    template_id = template.json()["id"]
    projects = {"alpha": alpha}
    people = {"alpha": _members_of(engine, alpha)}
    roles = {"beta": "member", "gamma": "proxy"}
    for n, (name, role) in enumerate(roles.items(), start=1):
        project_id = factory.project(engine, name, owner_id=bob)
        projects[name] = project_id
        factory.membership(engine, project_id, "owner", human_id=bob)
        factory.membership(engine, project_id, role, human_id=owner.id)
        factory.membership(engine, project_id, "admin" if n == 2 else "member", human_id=dora)
        factory.agent(engine, project_id, bob)
        factory.agent(engine, project_id, bob, "reviewer")
        people[name] = _members_of(engine, project_id)
    for n, name in enumerate(projects):
        own = template_id if name == "alpha" else None
        if own is None:
            own = _copy_template(engine, template_id, projects[name], f"req-tpl{name}")
        seed_requests(
            engine, own, people[name], jour_fixe_rounds(engine, projects[name]), count, n * 1000
        )
    r = t.request.c
    with engine.begin() as conn:
        times = {
            int(row.id[len("req-ovw") :]): row.created_at
            for row in conn.execute(select(r.id, r.created_at).where(r.id.like("req-ovw%")))
        }
        for n in sorted(times):
            if n < 1000:
                continue
            at = times[n % 1000]
            if n % 3:
                at += timedelta(seconds=17 * (n // 1000), microseconds=n)
            same = update(t.request).where(r.id == f"req-ovw{n:08d}")
            conn.execute(same.values(created_at=at))
        personal = _personal(conn, owner.id, bob, projects, times)
    caller = Caller(kind="human", via="cookie", human_id=owner.id)
    return Seeded(caller, owner, projects, dora, agent.id, personal)


def _members_of(engine: Engine, project_id: str) -> list[Person]:
    m = t.membership.c
    with engine.connect() as conn:
        rows = conn.execute(
            select(m.id, m.agent_id, m.human_id).where(m.project_id == project_id).order_by(m.id)
        ).all()
    return [Person(row.id, row.agent_id or row.human_id) for row in rows]


def _personal(
    conn: Connection, caller: str, bob: str, projects: dict[str, str], times: dict[int, Any]
) -> list[str]:
    """Personal requests: the caller's ten (two answered, one with no project, one the
    cross-owner request the caller asked), tied in time with alpha's requests; and three that
    are not the caller's (bob's, and two the caller asked that are no cross-owner request)."""
    template = conn.execute(select(t.request).where(t.request.c.id.like("req-ovw%"))).first()
    assert template is not None
    asker = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == projects["beta"], t.membership.c.agent_id.is_not(None)
        )
    ).first()
    assert asker is not None
    base: dict[str, Any] = {
        **template._mapping,
        "personal": True,
        "to_kind": "human",
        "to_member": None,
        "to_role": None,
        "to_instance": None,
        "to_human": caller,
        "held": None,
        "cover": None,
        "jour_fixe": None,
        "proposal": None,
        "holder_member": None,
        "holder_pool": None,
        "on_behalf_of": None,
        "filed_by": "hub",
        "asked_by": asker.id,
        "asked_by_human": None,
        "project_id": projects["beta"],
        "status": "open",
    }
    rows = []
    for n in range(10):
        row = {
            **base,
            "id": f"req-prs{n:08d}",
            "priority": ("urgent", "high", "normal", "low")[n % 4],
            "created_at": times[n * 3] if n % 2 else times[n * 3] - timedelta(seconds=5),
        }
        if n in (3, 8):
            row["status"] = "answered"
        if n == 5:  # the owner's digest: no project, no asker (§5.3)
            row.update(project_id=None, asked_by=None)
        if n == 7:  # the caller asked it as an owner outside the project (§7)
            row.update(
                to_human=bob,
                asked_by=None,
                asked_by_human=caller,
                filed_by=None,
                proposal={"kind": cross_owner.KIND},
            )
        rows.append(row)
    rows.append({**base, "id": "req-prsbob00001", "to_human": bob, "created_at": times[1]})
    rows.append(
        {
            **base,
            "id": "req-prsnot00001",
            "to_human": bob,
            "asked_by": None,
            "asked_by_human": caller,
            "filed_by": None,
            "created_at": times[2],
        }
    )
    conn.execute(insert(t.request), rows)
    return [row["id"] for row in rows[:10]]


@pytest.fixture
def seeded(make_client: ClientFactory, migrated: Engine) -> Seeded:
    return _seed(make_client, migrated)


def test_every_page_across_projects_is_the_inboxs_own(seeded: Seeded, migrated: Engine) -> None:
    seen: set[str] = set()
    ties = 0
    with migrated.connect() as conn:
        for to in seeded.tos():
            for sort in SORTS:
                for status in STATUSES:
                    inbox = Inbox(conn, seeded.caller, to, sort, status)
                    for limit in LIMITS:
                        shown = inbox.walk(limit)
                        assert shown == [e["id"] for e in inbox.entries], (to, sort, status)
                        seen.update(shown)
                    created = [(e["_created"], e["project"]) for e in inbox.entries]
                    ties += len(created) - len({at for at, _ in created})
    projects = {name: f"req-ovw{n * 1000:08d}"[:-3] for n, name in enumerate(seeded.projects)}
    for name, prefix in projects.items():
        assert any(i.startswith(prefix) for i in seen), name
    # Every personal request of the caller was listed, the cross-owner one too; none other.
    assert set(seeded.personal) <= seen
    assert not {"req-prsbob00001", "req-prsnot00001"} & seen
    assert ties  # requests of two projects at the same time: the id decided


def test_the_asker_filter_across_projects(seeded: Seeded, migrated: Engine) -> None:
    with migrated.connect() as conn:
        for asked_by in ("me", seeded.agent, seeded.dora, "agt-nobody00000"):
            for sort in SORTS:
                inbox = Inbox(conn, seeded.caller, "all", sort, "all", asked_by)
                inbox.walk(7)


def _walk_with_change(inbox: Inbox, values: dict[str, Any], personal: bool) -> bool:
    """Page 1, then `values` written to a request of page 2 (a personal one with
    `personal`), then page 2 and on, each against the oracle with the same cursor, the
    oracle's list read again after the change. False when page 2 has none to change."""
    first_old, first_new = inbox.oracle(7, None), inbox.paged(7, None)
    assert first_new == first_old
    cursor = first_new["next_cursor"]
    if cursor is None:
        return False
    second = [i for i in inbox.oracle(7, cursor)["items"] if i["personal"] is personal]
    if not second:
        return False
    changed = second[len(second) // 2]["id"]
    if values:
        inbox.conn.execute(update(t.request).where(t.request.c.id == changed).values(**values))
    else:  # gone altogether
        inbox.conn.execute(delete(t.request).where(t.request.c.id == changed))
    inbox.read()
    while cursor is not None:
        old, new = inbox.oracle(7, cursor), inbox.paged(7, cursor)
        assert new == old, (inbox.to, inbox.sort, cursor)
        cursor = new["next_cursor"]
    inbox.conn.rollback()
    return True


@pytest.mark.parametrize("change", ["answer", "hold", "cover", "gone", "personal_answer"])
def test_a_request_that_changes_between_pages_across_projects(
    seeded: Seeded, migrated: Engine, change: str
) -> None:
    substitute = {"for": seeded.dora, "by": seeded.agent, "since": clock.rfc3339(clock.now())}
    changes: dict[str, dict[str, Any]] = {
        "answer": {"status": "answered"},
        "hold": {"held": [seeded.agent]},
        "cover": {"cover": substitute},
        "gone": {},
        "personal_answer": {"status": "answered"},
    }
    walked = 0
    with migrated.connect() as conn:
        for to in ("me", "all"):
            for sort in SORTS:
                inbox = Inbox(conn, seeded.caller, to, sort, "open")
                walked += _walk_with_change(inbox, changes[change], change == "personal_answer")
    assert walked >= 3


# As on the project's list (test_request_paging.py `REDECIDED`): the page's keys are read
# before its rows are read in full, and on PostgreSQL each statement of `read_transaction` has
# its own snapshot, so the rows read in full are decided again: a project's by its listing, a
# personal one by the inbox's rule. Each case: (the request changed, `to`, status, its values
# before the listing, the change in between).
REDECIDED_ALL: dict[str, tuple[str, str, str, dict[str, Any], dict[str, Any]]] = {
    "forwarded_on": ("project", "me", "open", {"to_kind": "owner"}, {"holder_member": "z"}),
    "answered": ("project", "me", "open", {"to_kind": "owner"}, {"status": "answered"}),
    "addressed_elsewhere": ("project", "x", "all", {}, {"to_member": "z"}),
    "addressed_elsewhere_me": (
        "project",
        "me",
        "all",
        {"to_kind": "owner"},
        {"to_kind": "member", "to_member": "z"},
    ),
    "personal_answered": ("personal", "me", "open", {}, {"status": "answered"}),
    "personal_readdressed": ("personal", "all", "all", {}, {"to_human": "bob"}),
}


@pytest.mark.parametrize("own_connection", [True, False], ids=["same_connection", "committed"])
@pytest.mark.parametrize("change", list(REDECIDED_ALL))
def test_the_rows_read_in_full_are_decided_again_across_projects(
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    own_connection: bool,
) -> None:
    """`same_connection` writes on the listing's own connection, which the full read sees on
    every database. `committed` writes from another connection and commits: the full read
    sees it on PostgreSQL; SQLite reads one snapshot per read transaction, so there the page
    is the one from before the change. A second project's request is on every page, so the
    full read covers more than one listing."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agents = {name: flow.agent(make_client, owner) for name in ("x", "y", "z")}
    members = {name: person(migrated, a.id).membership for name, a in agents.items()}
    bob = factory.human(migrated, "bob")
    for n in range(3):  # what the owner lists in any case: addressed to them
        asked(agents["x"], to="owner", title=f"Mine {n}?")
    project_row = asked(agents["y"], to=agents["x"].id, title="Which?")["id"]
    r = t.request.c
    beta = factory.project(migrated, "beta", owner_id=bob)
    factory.membership(migrated, beta, "owner", human_id=bob)
    in_beta = factory.membership(migrated, beta, "member", human_id=owner.id)
    personal_row = "req-prsdecide001"
    with migrated.begin() as conn:
        template = conn.execute(select(t.request).where(r.id == project_row)).one()._mapping
        to_caller = {"to_kind": "member", "to_member": in_beta, "asked_by": None}
        conn.execute(
            insert(t.request),
            [
                {**template, **to_caller, "id": "req-betadecide01", "project_id": beta},
                {
                    **template,
                    "id": personal_row,
                    "personal": True,
                    "to_kind": "human",
                    "to_member": None,
                    "to_human": owner.id,
                    "filed_by": "hub",
                },
            ],
        )
    kind, to, status, before, between = REDECIDED_ALL[change]
    changed = personal_row if kind == "personal" else project_row
    to = agents[to].id if to in agents else to
    names: dict[str, Any] = {**members, "bob": bob}

    def values(given: dict[str, Any]) -> dict[str, Any]:
        out = {c: names.get(v, v) if isinstance(v, str) else v for c, v in given.items()}
        if out.get("to_kind") == "owner":
            out["to_member"] = None
        return out

    with migrated.begin() as conn:
        if before:
            conn.execute(update(t.request).where(r.id == changed).values(**values(before)))
        restore = dict(
            conn.execute(select(*(r[c] for c in between)).where(r.id == changed)).one()._mapping
        )
    caller = Caller(kind="human", via="cookie", human_id=owner.id)
    original = requests_route._read_in_full

    def write(conn: Connection, row_values: dict[str, Any]) -> None:
        conn.execute(update(t.request).where(r.id == changed).values(**row_values))

    fired: list[bool] = []
    for sort in SORTS:
        with migrated.connect() as conn:
            earlier = Inbox(conn, caller, to, sort, status)
            shown = [e["id"] for e in earlier.entries]
            assert changed in shown, (change, sort)
            if to in ("me", "all"):
                assert "req-betadecide01" in shown, (change, sort)
            before_page = earlier.oracle(10, None)
        fired.clear()

        def hooked(conn: Connection, ids: list[str], listed: Any) -> list[Any]:
            # After the keys are read (every listing's and the personal inbox's), before the
            # full read.
            fired.append(True)
            if own_connection:
                write(conn, values(between))
            else:
                with migrated.begin() as other:
                    write(other, values(between))
            return original(conn, ids, listed)

        monkeypatch.setattr(requests_route, "_read_in_full", hooked)
        if own_connection:
            with migrated.connect() as conn:
                page = Inbox(conn, caller, to, sort, status).paged(10, None)
                later = Inbox(conn, caller, to, sort, status).oracle(200, None)
                conn.rollback()
        else:
            with read_transaction(migrated) as conn:
                page = Inbox(conn, caller, to, sort, status).paged(10, None)
            with migrated.connect() as conn:
                later = Inbox(conn, caller, to, sort, status).oracle(200, None)
            with migrated.begin() as conn:
                write(conn, restore)
        monkeypatch.setattr(requests_route, "_read_in_full", original)
        where = (change, sort, own_connection)
        assert fired == [True], where  # one full read for the whole page
        if not own_connection and migrated.dialect.name == "sqlite":
            assert page == before_page, where
            continue
        # Only what the inbox holds after the change, each item as it shows it now.
        listed = {item["id"]: item for item in later["items"]}
        assert changed not in listed, where
        assert page["items"] or to not in ("me", "all"), where  # the rest still listed
        for item in page["items"]:
            assert item == listed.get(item["id"]), where


def test_a_cursor_the_hub_gave_before_still_pages_across_projects(
    seeded: Seeded, migrated: Engine
) -> None:
    """A cursor in `_key`'s shape at any entry, a personal one too, and at a request since
    gone from the list, pages as the old path did."""
    with migrated.connect() as conn:
        for sort in SORTS:
            inbox = Inbox(conn, seeded.caller, "all", sort, "all")
            picks = inbox.entries[:: max(1, len(inbox.entries) // 6)]
            picks += [e for e in inbox.entries if e["id"] in seeded.personal][:2]
            for entry in picks:
                cursor = _cursor({"s": sort, "k": _key(entry, sort)})
                assert inbox.paged(7, cursor) == inbox.oracle(7, cursor), (sort, entry["id"])
            gone = picks[1]
            conn.execute(delete(t.request).where(t.request.c.id == gone["id"]))
            inbox.read()
            cursor = _cursor({"s": sort, "k": _key(gone, sort)})
            assert inbox.paged(7, cursor) == inbox.oracle(7, cursor), sort
            conn.rollback()


def _ten_listed(make_client: ClientFactory, migrated: Engine) -> Caller:
    """Six open requests to the owner in their project from two agents and four personal ones
    to the owner, across the priorities and between the project's in time: the owner's
    `GET /requests?to=all` lists all ten, the kinds mixed in every sort."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    askers = [flow.agent(make_client, owner) for _ in range(2)]
    members = [person(migrated, a.id).membership for a in askers]
    made = [asked(askers[n % 2], to="owner", title=f"Which {n}?")["id"] for n in range(6)]
    r = t.request.c
    with migrated.begin() as conn:
        for n, request_id in enumerate(made):
            priority = PRIORITIES[n % len(PRIORITIES)]
            conn.execute(update(t.request).where(r.id == request_id).values(priority=priority))
        rows = {row.id: row for row in conn.execute(select(t.request).where(r.id.in_(made)))}
        template = rows[made[0]]._mapping
        personal = [
            {
                **template,
                "id": f"req-prskeep{n:05d}",
                "personal": True,
                "to_kind": "human",
                "to_member": None,
                "to_human": owner.id,
                "filed_by": "hub",
                "asked_by": members[(n + 1) % 2],
                "priority": PRIORITIES[(n + 1) % len(PRIORITIES)],
                "created_at": rows[made[n + 1]].created_at + timedelta(microseconds=n + 1),
            }
            for n in range(4)
        ]
        conn.execute(insert(t.request), personal)
    return Caller(kind="human", via="cookie", human_id=owner.id)


def _set_status(conn: Connection, ids: Iterable[str], status: str) -> None:
    conn.execute(update(t.request).where(t.request.c.id.in_(list(ids))).values(status=status))


def _hide_on_full_read(
    monkeypatch: pytest.MonkeyPatch,
    migrated: Engine,
    own_connection: bool,
    choose: Callable[[list[str]], list[str]],
) -> set[str]:
    """Between the key reads and the full read, the requests `choose` picks of the page's ids
    leave the inbox (answered), on the inbox's connection or committed from another one. The
    set of every id hidden so far."""
    hidden: set[str] = set()
    original = requests_route._read_in_full

    def hooked(conn: Connection, ids: list[str], listed: Any) -> list[Any]:
        chosen = [i for i in choose(ids) if i not in hidden]
        hidden.update(chosen)
        if chosen and own_connection:
            _set_status(conn, chosen, "answered")
        elif chosen:
            with migrated.begin() as other:
                _set_status(other, chosen, "answered")
        return original(conn, ids, listed)

    monkeypatch.setattr(requests_route, "_read_in_full", hooked)
    return hidden


def _cursor_names(cursor: str | None, hidden: set[str]) -> set[str]:
    """The hidden ids a cursor's `k` holds."""
    if cursor is None:
        return set()
    raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    return {value for value in raw["k"] if value in hidden}


def _paged_once(
    migrated: Engine, caller: Caller, sort: str, limit: int, cursor: str | None, own: bool
) -> dict[str, Any]:
    """The owner's `to=all` page: on a connection rolled back after, or in a read transaction
    while another connection commits (`_hide_on_full_read`)."""
    if own:
        with migrated.connect() as conn:
            page = Inbox(conn, caller, "all", sort, "open").paged(limit, cursor)
            conn.rollback()
            return page
    with read_transaction(migrated) as conn:
        return Inbox(conn, caller, "all", sort, "open").paged(limit, cursor)


def _oracle_from(listed: Inbox, limit: int, cursor: str | None) -> list[str]:
    """The ids the old path shows from `cursor` on."""
    shown: list[str] = []
    for _ in range(len(listed.entries) + 2):
        page = listed.oracle(limit, cursor)
        shown += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return shown
    raise AssertionError("no last page")


def _rest(listed: Inbox, limit: int, cursor: str | None, hidden: set[str]) -> list[str]:
    """The ids of every page from `cursor` on; no cursor names a hidden request."""
    shown: list[str] = []
    for _ in range(len(listed.entries) + 5):
        if cursor is None:
            return shown
        page = listed.paged(limit, cursor)
        assert not _cursor_names(page["next_cursor"], hidden), cursor
        shown += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
    raise AssertionError("no last page")


def _ending_with(listed: Inbox, limit: int, personal: bool) -> tuple[str | None, str]:
    """A cursor whose page ends on a personal request (`personal`) or a project's, and that
    request: the first such one with a full page before it."""
    entries = listed.entries
    for at in range(limit - 1, len(entries)):
        entry = entries[at]
        if entry["id"].startswith("req-prskeep") is personal:  # `_ten_listed`'s personal ids
            if at < limit:
                cursor = None
            else:
                cursor = _cursor({"s": listed.sort, "k": _key(entries[at - limit], listed.sort)})
            page = listed.oracle(limit, cursor)
            assert page["items"][-1]["id"] == entry["id"], (listed.sort, limit)
            return cursor, entry["id"]
    raise AssertionError(("no request of that kind", listed.sort, limit, personal))


@pytest.mark.parametrize("own_connection", [True, False], ids=["same_connection", "committed"])
def test_a_pages_cursor_is_built_from_the_rows_it_keeps(
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    own_connection: bool,
) -> None:
    """The page's last row, a project's request or a personal one, leaves the inbox between
    the key reads and the full read: the cursor names a row the page keeps, and the walk from
    it lists every request the inbox holds after the change once. `committed` on SQLite reads
    one snapshot: the page is the one from before the change."""
    caller = _ten_listed(make_client, migrated)
    sqlite_snapshot = not own_connection and migrated.dialect.name == "sqlite"
    for personal in (False, True):
        for sort in SORTS:
            for limit in (1, 2):
                with migrated.connect() as conn:
                    before = Inbox(conn, caller, "all", sort, "open")
                    start, boundary = _ending_with(before, limit, personal)
                    before_ids = _oracle_from(before, limit, start)

                def choose(ids: list[str], boundary: str = boundary) -> list[str]:
                    return [boundary] if boundary in ids else []

                hidden = _hide_on_full_read(monkeypatch, migrated, own_connection, choose)
                where = (personal, sort, limit, own_connection)
                page = _paged_once(migrated, caller, sort, limit, start, own_connection)
                assert hidden == {boundary}, where
                if not sqlite_snapshot:
                    assert not _cursor_names(page["next_cursor"], hidden), where
                with migrated.connect() as conn:
                    if own_connection:
                        _set_status(conn, hidden, "answered")
                    after = Inbox(conn, caller, "all", sort, "open")
                    shown = [i["id"] for i in page["items"]]
                    shown += _rest(after, limit, page["next_cursor"], hidden)
                    if sqlite_snapshot:
                        assert shown == before_ids, where
                    else:
                        assert shown == _oracle_from(after, limit, start), where
                        assert boundary not in shown, where
                    conn.rollback()
                monkeypatch.undo()
                if not own_connection:
                    with migrated.begin() as conn:
                        _set_status(conn, hidden, "open")


@pytest.mark.parametrize("own_connection", [True, False], ids=["same_connection", "committed"])
def test_a_page_whose_rows_all_drop_reads_on(
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    own_connection: bool,
) -> None:
    """Every row of a page (the first, then the second, each ending on a project's request or
    a personal one) leaves the inbox between the key reads and the full read: the page reads
    on to the requests after them and is the page the inbox gives after the change; the walk
    lists each request it holds once."""
    caller = _ten_listed(make_client, migrated)
    sqlite_snapshot = not own_connection and migrated.dialect.name == "sqlite"
    limit = 2
    for personal in (False, True):
        for sort in SORTS:
            for at_page in (0, 1):
                with migrated.connect() as conn:
                    before = Inbox(conn, caller, "all", sort, "open")
                    cursor, _last = _ending_with(before, limit, personal)
                    if at_page:
                        cursor = before.oracle(limit, cursor)["next_cursor"]
                    before_page = before.oracle(limit, cursor)
                calls: list[list[str]] = []

                def choose(ids: list[str], calls: list[list[str]] = calls) -> list[str]:
                    calls.append(ids)
                    return ids if len(calls) == 1 else []  # the target page's first full read

                hidden = _hide_on_full_read(monkeypatch, migrated, own_connection, choose)
                where = (personal, sort, at_page, own_connection)
                page = _paged_once(migrated, caller, sort, limit, cursor, own_connection)
                assert hidden == {i["id"] for i in before_page["items"]}, where
                with migrated.connect() as conn:
                    if own_connection:
                        _set_status(conn, hidden, "answered")
                    after = Inbox(conn, caller, "all", sort, "open")
                    if sqlite_snapshot:
                        assert page == before_page, where
                    else:
                        assert page == after.oracle(limit, cursor), where
                        assert not _cursor_names(page["next_cursor"], hidden), where
                        shown = [i["id"] for i in page["items"]]
                        shown += _rest(after, limit, page["next_cursor"], hidden)
                        assert shown == _oracle_from(after, limit, cursor), where
                        assert not hidden & set(shown), where
                    conn.rollback()
                monkeypatch.undo()
                if not own_connection:
                    with migrated.begin() as conn:
                        _set_status(conn, hidden, "open")


@pytest.mark.parametrize("own_connection", [True, False], ids=["same_connection", "committed"])
def test_a_walk_whose_rows_keep_dropping_ends(
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    own_connection: bool,
) -> None:
    """Every row read in full leaves the inbox just before, project requests and personal
    ones alike: each call reads on `READ_ON_ROUNDS` times, then answers an empty page with the
    cursor it was called with (a place before every request on the first page), and the walk
    ends once nothing is left. `committed` on SQLite reads one snapshot per call: the full read
    still holds the rows, and the page is the one from before the change."""
    caller = _ten_listed(make_client, migrated)
    sqlite_snapshot = not own_connection and migrated.dialect.name == "sqlite"
    rounds = requests_route.READ_ON_ROUNDS
    for sort in SORTS:
        for limit, start_after_first in ((1, False), (2, False), (1, True)):
            where = (sort, limit, start_after_first, own_connection)
            with migrated.connect() as conn:
                before = Inbox(conn, caller, "all", sort, "open")
                cursor = before.oracle(1, None)["next_cursor"] if start_after_first else None
                before_page = before.oracle(limit, cursor)
            hidden = _hide_on_full_read(monkeypatch, migrated, own_connection, lambda ids: ids)
            with migrated.connect() as conn:
                calls = 0
                while True:
                    calls += 1
                    assert calls <= 6, where
                    if own_connection:
                        page = Inbox(conn, caller, "all", sort, "open").paged(limit, cursor)
                    else:
                        page = _paged_once(migrated, caller, sort, limit, cursor, False)
                    if sqlite_snapshot:
                        assert page == before_page, where
                        break
                    assert page["items"] == [], where
                    assert not _cursor_names(page["next_cursor"], hidden), where
                    if page["next_cursor"] is None:
                        break
                    # The bound was reached: the cursor the call was given, or the start.
                    start = requests_route._next_cursor(sort, requests_route._start_key(sort))
                    assert page["next_cursor"] == (cursor or start), where
                    assert len(hidden) % (rounds * limit) == 0, where
                    cursor = page["next_cursor"]
                if not sqlite_snapshot:
                    assert len(hidden) == 10 - int(start_after_first), where
                conn.rollback()
            monkeypatch.undo()
            if not own_connection:
                with migrated.begin() as conn:
                    _set_status(conn, hidden, "open")


@pytest.mark.parametrize(
    ("sort", "k"),
    [
        # A regression test: 400 since `_page` reads the cursor with `_cursor_key`. Before
        # that (4f279610) the first three were a 500 and the last was taken.
        ("date", [1, "req-x"]),
        ("priority", [ISO, 1, "req-x"]),
        ("agent", [None, ISO, "req-x"]),
        ("date", [ISO, 7]),
    ],
)
def test_a_cursor_key_of_the_wrong_shape_is_invalid_across_projects(
    make_client: ClientFactory, migrated: Engine, sort: str, k: Any
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    asked(agent, to="owner")
    cursor = _cursor({"s": sort, "k": k})
    response = owner.get("/requests", params={"sort": sort, "cursor": cursor})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {"cursor": "invalid"}


def test_a_bad_cursor_is_refused_after_every_project_is_skipped(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """A `to` that is no address anywhere skips every project, as before; the cursor is still
    read, and a caller with no membership gets the same answer."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    malformed = _cursor({"s": "date", "k": "anything"})
    for who in (owner, flow.human(make_client, migrated, "nobody")):
        empty = who.get("/requests", params={"to": "role:nope"})
        assert empty.json() == {"items": [], "next_cursor": None}
        refused = who.get("/requests", params={"to": "role:nope", "cursor": malformed})
        assert refused.json()["error"]["details"]["fields"] == {"cursor": "other_sort"}
