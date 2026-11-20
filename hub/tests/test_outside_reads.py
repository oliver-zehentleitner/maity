"""docs/api.md §2.3 "Reading a public project from outside": a signed-in human without an
active membership reads a public project's view, its members and its cards, with their history
and notes, and its logo and banner, through a closed allow-list (`access.OUTSIDE_READS`); every
other project route answers them `not_found`, a write before its body is read (§1.3)."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, func, insert, select, update

from maity_hub import access, clock, public_pages
from maity_hub import routes as route_package
from maity_hub import tables as t
from maity_hub import views as card_views
from maity_hub.config import Settings
from maity_hub.ids import new_id
from maity_hub.routes import board as board_routes
from maity_hub.routes import members as member_routes
from maity_hub.routes import projects as project_routes
from maity_hub.routes import tasks as task_routes
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

P = "/projects/maintainer/maity"
API = access.API_PROJECT
NOT_FOUND = {"error": {"code": "not_found", "message": "no such resource", "details": {}}}
RESTRICTED = "RESTRICTED-SENTINEL-7f3a"  # a card's restricted text (§6.4)
REASON = "REASON-SENTINEL-91c2"  # a redaction's reason (§8.5)
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
NEVER_IN_PROJECT = {"repository", "memory", "setup", "policy", "attachments", "aliases"}
NEVER_IN_MEMBER = set(member_routes.OUTSIDE_HIDDEN_MEMBER)


@pytest.fixture
def make_client(make_client: ClientFactory) -> ClientFactory:
    """Every hub here serves public pages: while it serves none, no project is public (§16.9)."""
    return lambda **kw: make_client(**{"public_pages": True, **kw})


@dataclass
class World:
    owner: flow.Human
    outsider: flow.Human
    agent: flow.Agent
    project_id: str
    card_id: str
    history_id: str
    note_id: str
    redacted_note_id: str

    @property
    def params(self) -> dict[str, str]:
        """Every path parameter of a project route by name: an unknown one fails the walk, so a
        new route needs a deliberate entry here. The ids of things that exist where the
        allow-list reads them; any value elsewhere, since the gate answers first."""
        return {
            "card_id": self.card_id,
            "task_id": self.card_id,
            "member_id": self.owner.id,
            "history_id": self.history_id,
            "note_id": self.note_id,
            "link_id": "lnk-none",
            "attachment_id": "att-none",
            "bridge_id": "brg-none",
            "conversation_id": "cnv-none",
            "seq": "1",
            "invitation_id": "inv-none",
            "join_id": "jn-none",
            "series_id": "jfs-none",
            "round_id": "jfr-none",
            "entry_id": "mem-none",
            "placement_id": "plc-none",
            "request_id": "req-none",
            "runner_id": "run-none",
            "takeover_id": "tko-none",
            "item_id": "chk-none",
            "credential_id": "crd-none",
        }


def _membership_of(engine: Engine, project_id: str, **principal: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id,
                *(getattr(t.membership.c, k) == v for k, v in principal.items()),
            )
        ).scalar_one()
        return found


def _put_image(human: flow.Human, kind: str) -> None:
    done = human.client.put(
        f"/api/v1{P}/{kind}",
        content=PNG,
        headers={"Content-Type": "image/png", "X-CSRF-Token": human.csrf},
    )
    assert done.status_code == 200, done.text


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine) -> World:
    """A public project with a card, its history, a note, a redacted note and entry, a
    restricted text, an agent member, a logo and a banner, and a human who is no member."""
    owner = flow.human(make_client, migrated)
    outsider = flow.human(make_client, migrated, "reader")
    project_id = str(flow.project(owner, "maity", public_page="on")["id"])
    agent = flow.agent(make_client, owner)
    card = task(owner, body="what the card asks")
    renamed = owner.patch(f"{P}/tasks/{card['id']}", {"title": "Renamed"})
    assert renamed.status_code == 200, renamed.text
    history = owner.get(f"{P}/tasks/{card['id']}/history").json()["items"]
    entry = next(e for e in history if e["field"] == "title")
    redacted = owner.post(
        f"{P}/tasks/{card['id']}/history/{entry['id']}/redact", {"reason": REASON}
    )
    assert redacted.status_code == 200, redacted.text
    kept = owner.post(f"{P}/tasks/{card['id']}/notes", {"body": "a finding"})
    assert kept.status_code == 201, kept.text
    gone = owner.post(f"{P}/tasks/{card['id']}/notes", {"body": "a leaked token"})
    assert gone.status_code == 201, gone.text
    hidden = owner.post(
        f"{P}/tasks/{card['id']}/notes/{gone.json()['id']}/redact",
        {"reason": REASON, "base_version": gone.json()["version"]},
    )
    assert hidden.status_code == 200, hidden.text
    writer = _membership_of(migrated, project_id, human_id=owner.id)
    with migrated.begin() as conn:  # no read of a card carries it (§6.4)
        conn.execute(
            insert(t.task_restricted).values(
                task_id=card["id"],
                project_id=project_id,
                text=RESTRICTED,
                version=1,
                updated_by=writer,
                updated_at=clock.now(),
            )
        )
    for kind in ("logo", "banner"):
        _put_image(owner, kind)
    return World(
        owner,
        outsider,
        agent,
        project_id,
        card["id"],
        entry["id"],
        kept.json()["id"],
        gone.json()["id"],
    )


def _app_routes(app: Any) -> set[tuple[str, str]]:
    """(method, path template) of every route the app serves, its included routers walked
    with their prefixes: FastAPI keeps an included router behind its own object, so
    `app.routes` lists no route of it (hub/context/namespace.md)."""
    return {
        (method, route.path_format)
        for route in iter_route_contexts(list(app.routes))
        if route.path_format is not None
        for method in route.methods or ()
    }


def _project_routes(app: Any) -> list[tuple[str, str]]:
    """(method, path template) of every route under `/api/v1/projects/{owner}/{slug}`."""
    return sorted(
        (method, path)
        for method, path in _app_routes(app)
        if path == API or path.startswith(API + "/")
    )


def _api_endpoints() -> dict[tuple[str, str], APIRoute]:
    """Each API route the routers of `maity_hub.routes` declare, by (method, template as the
    app serves it): a router's own routes are `APIRoute`s with the path below `access.API`,
    whichever way FastAPI keeps them once included."""
    found: dict[tuple[str, str], APIRoute] = {}
    for info in pkgutil.iter_modules(route_package.__path__):
        module = importlib.import_module(f"{route_package.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            continue
        for route in router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods or ():
                    found[(method, access.API + route.path)] = route
    return found


def _fill(template: str, params: dict[str, str], project: str = "maity") -> str:
    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "owner":
            return "maintainer"
        if name == "slug":
            return project
        if name not in params:
            pytest.fail(f"no value for the path parameter {name!r} of {template}")
        return params[name]

    return re.sub(r"{(\w+)(?::[^}]*)?}", value, template)


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]) -> Any:
    body: dict[str, Any] | None = None if method == "GET" else {}
    return client.request(method, path, json=body, headers=headers)


def _as(human: flow.Human) -> dict[str, str]:
    return {"X-CSRF-Token": human.csrf}


def _reads(world: World) -> list[str]:
    """The allow-listed paths, filled; the images last."""
    return sorted((_fill(path, world.params) for _, path in access.OUTSIDE_READS), key=len)


def _page(engine: Engine, project_id: str, on: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(public_page="on" if on else "off")
        )


# --- the allow-list, closed by construction ----------------------------------------------------


def test_the_allow_list_the_marker_and_the_reader_agree(make_client: ClientFactory) -> None:
    """Every endpoint that reads through `access.reader` carries `@outside_read` and is in
    `OUTSIDE_READS`, and the other way round; every entry is a GET the app routes."""
    served = _project_routes(make_client().app)
    endpoints = _api_endpoints()
    # Every project route the app serves is one the routers declare, so none escapes below.
    assert served, "the walk found no project route"
    assert set(endpoints) >= set(served), sorted(set(served) - set(endpoints))
    routes = {key: endpoints[key] for key in served}
    for method, path in access.OUTSIDE_READS:
        assert method == "GET", path
        assert (method, path) in routes, (method, path)
    # The owner calls of §1.3 are routes the app has, and none is an outsider's read.
    assert set(routes) >= access.OWNER_CALLS
    assert not access.OWNER_CALLS & access.OUTSIDE_READS
    for (method, path), route in endpoints.items():  # every API route, a project's or not
        source = inspect.getsource(route.endpoint)
        reads = "access.reader(" in source
        marked = getattr(route.endpoint, access.OUTSIDE_READ_MARK, False) is True
        listed = (method, path) in access.OUTSIDE_READS
        assert reads == marked == listed, (method, path, reads, marked, listed)
    # `reader` only ever as `access.reader`, so the check above sees every call of it.
    for module in Path(inspect.getfile(project_routes)).parent.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert not re.search(r"from maity_hub\.access import[^\n]*\breader\b", text), module
        assert not re.search(r"from maity_hub\.access import \([^)]*\breader\b", text), module


# --- the route walk -----------------------------------------------------------------------------


def test_an_outsider_reads_the_allow_list_and_every_other_route_is_not_found(
    world: World,
) -> None:
    """Every project route the app has: an allow-listed GET answers the outsider 200; every
    other GET, and every other method before its body is read, the `not_found` an unknown
    project answers (§1.3, §2.3)."""
    routes = _project_routes(world.outsider.client.app)
    assert set(access.OUTSIDE_READS) <= set(routes)
    unknown = world.outsider.client.get(_fill(API, world.params, "nothere"))
    assert (unknown.status_code, unknown.json()) == (404, NOT_FOUND)
    for method, template in routes:
        path = _fill(template, world.params)
        answer = _call(world.outsider.client, method, path, _as(world.outsider))
        where = (method, template, answer.text)
        if (method, template) in access.OUTSIDE_READS:
            assert answer.status_code == 200, where
        else:
            assert (answer.status_code, answer.json()) == (404, NOT_FOUND), where


def test_the_allow_list_answers_as_an_unknown_project_off_private_unsigned_or_to_an_agent(
    world: World, make_client: ClientFactory, migrated: Engine, settings: Settings
) -> None:
    """The same calls answer exactly what the same caller gets for a project that does not
    exist: without a session (`unauthenticated`, as before), with public pages off, for a
    private project, and for an agent credential of another project (§2.2, §2.3)."""
    flow.project(world.owner, "other")
    elsewhere = flow.agent(make_client, world.owner, slug="other")
    nobody = make_client()

    def same_as_unknown(client: TestClient, headers: dict[str, str], why: str) -> None:
        for _, template in sorted(access.OUTSIDE_READS):
            answer = client.get(_fill(template, world.params), headers=headers)
            unknown = client.get(_fill(template, world.params, "nothere"), headers=headers)
            got = (answer.status_code, answer.json())
            expected = (unknown.status_code, unknown.json())
            assert answer.status_code != 200, (why, template)
            assert got == expected, (why, template)

    same_as_unknown(nobody, {}, "no session")
    same_as_unknown(elsewhere.client, elsewhere.auth, "an agent of another project")
    public_pages.configure(replace(settings, public_pages=False))
    try:
        same_as_unknown(world.outsider.client, {}, "public pages off")
    finally:
        public_pages.configure(replace(settings, public_pages=True))
    _page(migrated, world.project_id, on=False)
    same_as_unknown(world.outsider.client, {}, "a private project")
    _page(migrated, world.project_id, on=True)
    assert world.outsider.get(P).status_code == 200  # public again, read again


# --- the gate before the body (R6) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/tasks", {"title": 5}),
        ("POST", "/tasks", b"{not json"),
        ("PATCH", "", {"name": 7}),
        ("PATCH", "/tasks/{card_id}", {"title": []}),
        ("POST", "/tasks/{card_id}/notes", {}),
        ("POST", "/tasks/{card_id}/history/{history_id}/redact", {}),
    ],
)
def test_an_outsiders_write_with_a_bad_body_is_not_found_before_validation(
    world: World, method: str, path: str, body: Any
) -> None:
    """`ProjectRoute`'s gate answers `not_found` before FastAPI reads the body: the outsider
    never learns a route's body from a validation answer. A member's call with the same body
    is refused for the body, as before; so is a call on an unknown project, which the gate
    leaves as it was."""
    url = "/api/v1" + P + path.format(**world.params)
    elsewhere = url.replace("/maintainer/maity", "/maintainer/nothere")

    def send(human: flow.Human, target: str) -> Any:
        headers = {**_as(human), "Content-Type": "application/json"}
        if isinstance(body, bytes):
            return human.client.request(method, target, content=body, headers=headers)
        return human.client.request(method, target, json=body, headers=headers)

    refused = send(world.outsider, url)
    assert (refused.status_code, refused.json()) == (404, NOT_FOUND), refused.text
    as_member = send(world.owner, url)
    assert as_member.status_code == 400, as_member.text
    assert as_member.json()["error"]["code"] == "invalid"
    unknown = send(world.outsider, elsewhere)
    assert unknown.status_code == 400, unknown.text  # unchanged: the gate passes it


def test_an_agents_owner_outside_the_project_passes_the_gate_on_the_owner_calls_alone(
    world: World, make_client: ClientFactory, migrated: Engine
) -> None:
    """An owner whose agent is a member keeps the calls §1.3 lists for them
    (`access.OWNER_CALLS`): the gate passes them there, and the route answers as it always
    did (their agent's briefings, §6.2; a malformed body on their agent's membership is the
    route's `invalid`). Every other route of the project answers them `not_found` before its
    body is read, as it answers any outsider, a write with a bad body included."""
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == world.agent.id)
            .values(owner_id=world.outsider.id)
        )
    path = f"{P}/members/{world.agent.id}/briefings"
    assert world.outsider.get(path).status_code == 200
    stranger = flow.human(make_client, migrated, "stranger")
    assert (stranger.get(path).status_code, stranger.get(path).json()) == (404, NOT_FOUND)
    headers = {**_as(world.outsider), "Content-Type": "application/json"}
    passed = world.outsider.client.patch(
        f"/api/v1{P}/members/{world.agent.id}", content=b"{not json", headers=headers
    )
    assert (passed.status_code, passed.json()["error"]["code"]) == (400, "invalid"), passed.text
    tasks = f"/api/v1{P}/tasks"
    for body in ({"title": "A card"}, {"title": 5}):
        refused = world.outsider.client.post(tasks, json=body, headers=headers)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (body, refused.text)
    refused = world.outsider.client.post(tasks, content=b"{not json", headers=headers)
    assert (refused.status_code, refused.json()) == (404, NOT_FOUND), refused.text
    open_to_them = access.OUTSIDE_READS | access.OWNER_CALLS
    for method, template in _project_routes(world.outsider.client.app):
        if (method, template) in open_to_them:
            continue
        answer = _call(world.outsider.client, method, _fill(template, world.params), headers)
        assert (answer.status_code, answer.json()) == (404, NOT_FOUND), (method, template)


# --- not-done security cards, as on the Board ---------------------------------------------------


def test_a_not_done_security_card_is_hidden_from_an_outsider_as_on_the_public_board(
    world: World, migrated: Engine
) -> None:
    """`public_cards.shown`, the public Board's and card page's rule (§16.9): a card labelled
    `security` (any case) is left out of every list an outsider reads, and its card, history
    and notes answer `not_found`, until it is `done`; a member reads it as before."""
    writer = _membership_of(migrated, world.project_id, human_id=world.owner.id)
    secret = factory.card(migrated, world.project_id, writer, title="Secret hole", label="Security")
    fixed = factory.card(
        migrated,
        world.project_id,
        writer,
        title="Fixed hole",
        label="security",
        status="done",
        closed_at=clock.now(),
    )

    def listed(who: flow.Human, query: str) -> set[str]:
        answer = who.get(f"{P}/tasks{query}")
        assert answer.status_code == 200, (query, answer.text)
        return {item["id"] for item in answer.json()["items"]}

    for query in ("", "?order=updated", "?status=open", "?status=done", "?label=Security"):
        assert secret not in listed(world.outsider, query), query
    for query in ("", "?order=updated", "?status=done"):
        assert fixed in listed(world.outsider, query), query
    assert {secret, fixed} <= listed(world.owner, "")
    for card_id, hidden in ((secret, True), (fixed, False)):
        for tail in ("", "/history", "/notes"):
            path = f"{P}/tasks/{card_id}{tail}"
            outside = world.outsider.get(path)
            if hidden:
                assert (outside.status_code, outside.json()) == (404, NOT_FOUND), path
            else:
                assert outside.status_code == 200, (path, outside.text)
            assert world.owner.get(path).status_code == 200, path


def _hold(engine: Engine, reporter: str, card_id: str, action: str = "hide") -> None:
    """A moderation hold on the card, as `moderation.apply` leaves one (§16.8)."""
    with engine.begin() as conn:
        _hold_on(conn, reporter, card_id, action)


def _hold_on(conn: Connection, reporter: str, card_id: str, action: str = "hide") -> None:
    """`_hold`, written on `conn`."""
    report_id = f"rpt-{card_id[-12:]}"
    conn.execute(
        insert(t.abuse_report).values(
            id=report_id, reporter=reporter, account_id=reporter, target_type="card",
            target_id=card_id, reason="spam", status="resolved", action=action,
            created_at=clock.now(),
        )
    )  # fmt: skip
    conn.execute(
        insert(t.moderation_hold).values(
            report_id=report_id,
            target_type="card",
            target_id=card_id,
            action=action,
            at=clock.now(),
        )
    )


def _listed(who: flow.Human, query: str) -> dict[str, Any]:
    answer = who.get(f"{P}/tasks{query}")
    assert answer.status_code == 200, (query, answer.text)
    return {item["id"]: item for item in answer.json()["items"]}


def test_a_card_under_a_hold_is_hidden_from_an_outsider_as_on_the_public_board(
    world: World, migrated: Engine
) -> None:
    """`moderation.hold`, the public Board's and card page's rule (§16.8, §16.9): a card under
    a hold, whatever its status, is in no list an outsider reads, and its card, history and
    notes answer `not_found`; a member reads it as before, with its `moderation`."""
    writer = _membership_of(migrated, world.project_id, human_id=world.owner.id)
    held = factory.card(migrated, world.project_id, writer, title="Free tokens")
    closed = factory.card(
        migrated, world.project_id, writer, title="Old spam", status="done", closed_at=clock.now()
    )
    for card_id in (held, closed):
        _hold(migrated, world.owner.id, card_id)
    for query in ("", "?order=updated", "?status=open", "?status=done", "?q=tokens"):
        assert not {held, closed} & set(_listed(world.outsider, query)), query
    assert world.card_id in _listed(world.outsider, "")
    assert {held, closed} <= set(_listed(world.owner, ""))
    for card_id in (held, closed):
        for tail in ("", "/history", "/notes"):
            path = f"{P}/tasks/{card_id}{tail}"
            outside = world.outsider.get(path)
            assert (outside.status_code, outside.json()) == (404, NOT_FOUND), path
            inside = world.owner.get(path)
            assert inside.status_code == 200, path
        assert world.owner.get(f"{P}/tasks/{card_id}").json()["moderation"]["action"] == "hide"


def test_no_hidden_cards_id_is_in_any_card_an_outsider_reads(
    world: World, migrated: Engine
) -> None:
    """A visible card that depends on, ships with, relates to or is the child of a not-done
    `security` card or a card under a hold names none of them to an outsider, in the list or
    the card, and its subtask counts leave out such children; a member reads every id and
    count as before."""
    writer = _membership_of(migrated, world.project_id, human_id=world.owner.id)
    secret = factory.card(migrated, world.project_id, writer, title="Hole", label="security")
    held = factory.card(migrated, world.project_id, writer, title="Spam")
    _hold(migrated, world.owner.id, held)
    plain = factory.card(migrated, world.project_id, writer, title="Plain")
    card = factory.card(migrated, world.project_id, writer, title="Visible", parent=secret)
    factory.card(migrated, world.project_id, writer, title="Hole 2", parent=card, label="security")
    held_child = factory.card(migrated, world.project_id, writer, title="Held", parent=card)
    _hold(migrated, world.owner.id, held_child)
    shown_child = factory.card(migrated, world.project_id, writer, title="Child", parent=card)
    edges = [
        (card, other, kind)
        for other in (secret, held, plain)
        for kind in ("depends_on", "ships_with", "related")
    ]
    edges += [(other, card, "related") for other in (secret, held, plain)]  # symmetric
    with migrated.begin() as conn:
        conn.execute(
            insert(t.card_edge),
            [{"from_card": a, "to_card": b, "kind": kind} for a, b, kind in edges],
        )
    hidden = {secret, held, held_child}
    path = f"{P}/tasks/{card}"
    outside = [world.outsider.get(path).json(), _listed(world.outsider, "")[card]]
    outside.append(_listed(world.outsider, "?order=updated")[card])
    for view in outside:
        for field in ("depends_on", "ships_with", "related"):
            assert view[field] == [plain], (field, view[field])
        assert view["parent"] is None
        assert view["children"] == {"open": 1, "total": 1}
        assert not any(card_id in str(view) for card_id in hidden), view
    assert set(_listed(world.outsider, f"?parent={secret}")) == set()
    assert set(_listed(world.outsider, f"?parent={card}")) == {shown_child}
    inside = world.owner.get(path).json()
    for field in ("depends_on", "ships_with", "related"):
        assert inside[field] == sorted([secret, held, plain]), field
    assert inside["parent"] == secret
    assert inside["children"] == {"open": 3, "total": 3}
    assert card in set(_listed(world.owner, f"?parent={secret}"))


# --- a card hidden between two statements of one read (READ COMMITTED, as #2005) ----------------


@contextmanager
def _writable(engine: Engine) -> Iterator[Connection]:
    """A route's read transaction a test may write in, rolled back at its end: a write on it
    between two of the route's statements is seen by the later ones on every database, as a
    write committed meanwhile is on PostgreSQL (READ COMMITTED)."""
    with engine.connect() as conn:
        conn.begin()
        try:
            yield conn
        finally:
            conn.rollback()


def _hide(conn: Connection, change: str, card_id: str, reporter: str) -> None:
    if change == "security":
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(label="security"))
    else:
        _hold_on(conn, reporter, card_id)


# A read, and the function around which the card is hidden: before the list's full rows are
# read after its keys (`_views`, `before`), or after the statement that read the card (the
# list's full rows or `_project_card`, and the views' edges and counts after them) and before
# the statements that read what the outsider gets (`outside_views`, the entries).
BETWEEN = {
    "board_keys": ("", task_routes, "_views", True),
    "updated_keys": ("?order=updated", task_routes, "_views", True),
    "board": ("", card_views, "_task_views", False),
    "updated": ("?order=updated", card_views, "_task_views", False),
    "card": ("/{card}", card_views, "_task_views", False),
    "history": ("/{card}/history", board_routes, "_project_card", False),
    "notes": ("/{card}/notes", board_routes, "_project_card", False),
}


@pytest.mark.parametrize("own_connection", [True, False], ids=["same_connection", "committed"])
@pytest.mark.parametrize("change", ["security", "held"])
@pytest.mark.parametrize("read", list(BETWEEN))
def test_a_card_hidden_between_the_statements_of_a_read_does_not_reach_an_outsider(
    world: World,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    read: str,
    change: str,
    own_connection: bool,
) -> None:
    """The outsider's card rule is decided on the rows a read returns, not only on a statement
    before them: a card that becomes a not-done `security` card or gets a hold after the
    statement that read it is not in the list, its card answers `not_found`, and its history
    and notes read nothing. `same_connection` writes on the route's own transaction, which
    every later statement sees on every database; `committed` writes from another connection
    and commits: PostgreSQL's next statement sees it, while SQLite reads one snapshot per read
    transaction, so there the read answers as before the change."""
    card = task(world.owner, body="a card that turns secret")["id"]
    renamed = world.owner.patch(f"{P}/tasks/{card}", {"title": "Turns secret"})
    assert renamed.status_code == 200, renamed.text
    noted = world.owner.post(f"{P}/tasks/{card}/notes", {"body": "NOTE-SENTINEL-4b1e"})
    assert noted.status_code == 201, noted.text
    tail, module, name, before = BETWEEN[read]
    if own_connection:
        monkeypatch.setattr(task_routes, "read_transaction", _writable)
        monkeypatch.setattr(board_routes, "read_transaction", _writable)
    original = getattr(module, name)
    fired: list[bool] = []

    def hide(conn: Connection) -> None:
        if fired:
            return
        fired.append(True)
        if own_connection:
            _hide(conn, change, card, world.owner.id)
        else:
            with migrated.begin() as other:
                _hide(other, change, card, world.owner.id)

    def hooked(conn: Connection, *args: Any) -> Any:
        if before:
            hide(conn)
        result = original(conn, *args)
        hide(conn)
        return result

    monkeypatch.setattr(module, name, hooked)
    answer = world.outsider.get(f"{P}/tasks" + tail.format(card=card))
    monkeypatch.setattr(module, name, original)
    assert fired, read
    hidden = own_connection or migrated.dialect.name != "sqlite"
    if read == "card":
        if hidden:
            assert (answer.status_code, answer.json()) == (404, NOT_FOUND), answer.text
        else:
            assert answer.status_code == 200, answer.text
        return
    assert answer.status_code == 200, answer.text
    items = answer.json()["items"]
    if read in ("board", "updated", "board_keys", "updated_keys"):
        assert (card not in {item["id"] for item in items}) is hidden, items
        if hidden:
            assert "moderation" not in answer.text
        return
    assert (items == []) is hidden, items
    if hidden:
        assert "NOTE-SENTINEL-4b1e" not in answer.text


def test_a_hidden_child_added_between_the_statements_is_not_counted_off(
    world: World, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `children` counts an outsider reads are counted from the children the deciding
    statement reads, not by subtracting from an earlier count: a not-done `security` child
    added between the two statements neither shows nor makes a count negative."""
    writer = _membership_of(migrated, world.project_id, human_id=world.owner.id)
    parent = factory.card(migrated, world.project_id, writer, title="No children yet")
    monkeypatch.setattr(task_routes, "read_transaction", _writable)
    original = card_views._task_views

    def hooked(conn: Connection, *args: Any) -> Any:
        result = original(conn, *args)
        conn.execute(
            insert(t.card).values(
                id=new_id("task"), project_id=world.project_id, kind="task",
                title="Secret child", status="open", label="security", parent=parent,
                created_by=writer, created_at=clock.now(), updated_at=clock.now(),
            )
        )  # fmt: skip
        return result

    monkeypatch.setattr(card_views, "_task_views", hooked)
    answer = world.outsider.get(f"{P}/tasks/{parent}")
    monkeypatch.setattr(card_views, "_task_views", original)
    assert answer.status_code == 200, answer.text
    assert answer.json()["children"] == {"open": 0, "total": 0}


# --- a stranger's bad body: a private project answers as an unknown one -------------------------


@pytest.mark.parametrize("body", [{"title": 5}, b"{not json"])
def test_a_bad_body_answers_a_stranger_to_a_private_project_as_to_an_unknown_one(
    world: World, make_client: ClientFactory, migrated: Engine, body: Any
) -> None:
    """The gate leaves strangers to a private project alone because nothing tells the project
    from an unknown one: the body is validated before the route reads the membership, for
    both alike, so a human gets the same `invalid` and an agent of another project the same
    answer (§1.3). A member's bad body is `invalid` too."""
    flow.project(world.owner, "other")
    elsewhere = flow.agent(make_client, world.owner, slug="other")
    _page(migrated, world.project_id, on=False)
    url = f"/api/v1{P}/tasks"
    unknown_url = url.replace("/maintainer/maity", "/maintainer/nothere")

    def send(client: TestClient, headers: dict[str, str], target: str) -> Any:
        headers = {**headers, "Content-Type": "application/json"}
        if isinstance(body, bytes):
            return client.request("POST", target, content=body, headers=headers)
        return client.request("POST", target, json=body, headers=headers)

    callers = (
        (world.outsider.client, _as(world.outsider), "a human"),
        (elsewhere.client, elsewhere.auth | elsewhere.key(), "an agent of another project"),
    )
    for client, headers, who in callers:
        private = send(client, headers, url)
        unknown = send(client, headers, unknown_url)
        assert (private.status_code, private.json()) == (unknown.status_code, unknown.json()), who
        assert private.status_code in (400, 404), (who, private.text)
    human = send(world.outsider.client, _as(world.outsider), url)
    assert (human.status_code, human.json()["error"]["code"]) == (400, "invalid"), human.text
    member = send(world.owner.client, _as(world.owner), url)
    assert (member.status_code, member.json()["error"]["code"]) == (400, "invalid"), member.text


# --- what the reads show ----------------------------------------------------------------------


def test_no_allow_listed_read_carries_a_restricted_text_or_a_redactions_reason(
    world: World,
) -> None:
    for path in _reads(world):
        if path.endswith(("/logo", "/banner")):
            continue
        for query in ("", "?state=all"):
            answer = world.outsider.client.get(path + query)
            assert answer.status_code == 200, (path, answer.text)
            assert RESTRICTED not in answer.text, path
            assert REASON not in answer.text, path
    # The counter-check: the owner reads the reason the outsider never gets (§8.5).
    history = world.owner.get(f"{P}/tasks/{world.card_id}/history").text
    assert REASON in history


def test_the_project_view_is_the_allow_list_of_its_keys(world: World) -> None:
    linked = world.owner.patch(P, {"links": {"issues": "https://example.org/issues"}})
    assert linked.status_code == 200, linked.text
    view = world.outsider.get(P).json()
    assert set(view) == set(project_routes.OUTSIDE_PROJECT_KEYS)
    assert not NEVER_IN_PROJECT & set(view)
    assert view["settings"] == {"language": "en"}
    assert view["links"]["issues"] == "https://example.org/issues"
    named = (view["id"], view["full_name"], view["public_page"])
    assert named == (world.project_id, "maintainer/maity", "on")
    assert view["logo"]["available"] is True
    member = world.owner.get(P).json()  # a member's view is as it was
    assert {"repository", "memory", "setup", "policy"} <= set(member)
    assert set(view) < set(member)


def test_member_views_leave_out_windows_isolation_presence_and_the_gated_fields(
    world: World,
) -> None:
    items = world.outsider.get(f"{P}/members").json()["items"]
    assert world.outsider.id not in {m["id"] for m in items}  # a reader is no member
    assert {world.owner.id, world.agent.id} <= {m["id"] for m in items}
    single = [world.outsider.get(f"{P}/members/{m['id']}").json() for m in items]
    for view in items + single:
        assert not NEVER_IN_MEMBER & set(view), view
        for instance in view.get("instances") or []:
            assert not {"presence", "last_seen_at"} & set(instance), instance
            assert "listening" not in (instance.get("session") or {}), instance
        assert "listening" not in (view.get("session") or {}), view
    # The counter-check: the owner, an admin, reads every one of them.
    agent = world.owner.get(f"{P}/members/{world.agent.id}").json()
    assert {"isolation_windows", "isolated", "last_seen_at", "presence", "owner"} <= set(agent)
    assert world.outsider.get(f"{P}/members/{world.outsider.id}").status_code == 404


def test_notes_and_history_follow_redaction_and_the_readers_own_windows(
    world: World, migrated: Engine
) -> None:
    """A redacted note's and entry's tombstone without its reason; the outsider has no hidden
    window of its own (§6.2), so it reads what a member without one reads, while a member's
    window still hides the notes from that member alone."""
    notes = f"{P}/tasks/{world.card_id}/notes?state=all"
    outside = world.outsider.get(notes).json()["items"]
    inside = world.owner.get(notes).json()["items"]
    assert [n["id"] for n in outside] == [n["id"] for n in inside]
    tomb = next(n for n in outside if n["id"] == world.redacted_note_id)
    assert tomb["redacted"] is True and tomb["body"]["reason"] is None
    assert next(n for n in inside if n["id"] == world.redacted_note_id)["body"]["reason"] == REASON
    entries = world.outsider.get(f"{P}/tasks/{world.card_id}/history").json()["items"]
    entry = next(e for e in entries if e["id"] == world.history_id)
    assert entry["redacted"] is True and entry["before"]["reason"] is None
    agent_row = _membership_of(migrated, world.project_id, agent_id=world.agent.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == agent_row)
            .values(isolation_windows=[{"from_seq": 0, "to_seq": 10**9}])
        )
    assert world.agent.get(notes).json()["items"] == []  # its window hides them from it
    again = world.outsider.get(notes).json()["items"]
    assert [n["id"] for n in again] == [n["id"] for n in inside]
    members = world.outsider.get(f"{P}/members").json()["items"]
    assert all("isolation_windows" not in m for m in members)


def test_a_public_read_never_makes_the_outsider_a_colleague_of_a_member(
    world: World, migrated: Engine
) -> None:
    """`links_visible: colleagues` admits the humans who share an active membership with the
    person (`person_links.Reader`); reading a public project is none (§16.9, §2.3)."""
    links = {"website": "https://example.org", "links_visible": "colleagues"}
    shown = world.owner.patch("/me", links)
    assert shown.status_code == 200, shown.text

    def website() -> Any:
        items = world.outsider.get(f"{P}/members").json()["items"]
        single = world.outsider.get(f"{P}/members/{world.owner.id}").json()
        listed = next(m for m in items if m["id"] == world.owner.id)
        assert listed.get("website") == single.get("website")
        return listed.get("website")

    assert website() is None
    # A colleague by a shared project, as `person_links` has it: that, not the read, admits.
    other = str(flow.project(world.owner, "other")["id"])
    factory.membership(migrated, other, "member", human_id=world.outsider.id)
    assert website() == "https://example.org"


def test_an_outsiders_reads_leave_no_trace_in_the_project(world: World, migrated: Engine) -> None:
    """No event, no `last_seen_at` of a membership in the project (§2.3, §2.4)."""

    def state() -> tuple[int, dict[int, Any]]:
        with migrated.connect() as conn:
            events = conn.execute(
                select(func.count())
                .select_from(t.event)
                .where(t.event.c.project_id == world.project_id)
            ).scalar_one()
            rows = conn.execute(
                select(t.membership.c.id, t.membership.c.last_seen_at).where(
                    t.membership.c.project_id == world.project_id
                )
            )
            seen = {row.id: row.last_seen_at for row in rows}
        return int(events), seen

    before = state()
    for path in _reads(world):
        for query in ("", "?state=all"):
            assert world.outsider.client.get(path + query).status_code == 200, path
    assert state() == before


def test_bootstrap_stays_with_members(world: World) -> None:
    """`GET /bootstrap` reads its project parts through the membership alone (§5.4)."""
    parts = world.outsider.client.get("/api/v1/bootstrap?project=maintainer/maity").json()
    assert parts["project"]["status"] == 404 and parts["members"]["status"] == 404
    mine = world.owner.client.get("/api/v1/bootstrap?project=maintainer/maity").json()
    assert mine["project"]["status"] == 200 and "repository" in mine["project"]["body"]
