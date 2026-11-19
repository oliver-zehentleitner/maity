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
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, delete, insert, select, update

from maity_hub import clock, cross_owner
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.routes.requests import _all_entries, _all_page, _key, _page, _render, _sorted
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_overview import Person, jour_fixe_rounds, seed_requests
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
