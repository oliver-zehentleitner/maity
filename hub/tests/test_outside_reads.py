"""docs/api.md §2.3 "Reading a public project from outside": a signed-in human without an
active membership reads a public project's view, its members and its cards, with their history
and notes, and its logo and banner, through a closed allow-list (`access.OUTSIDE_READS`); every
other project route answers them `not_found`, a write before its body is read (§1.3)."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, insert, select, update

from maity_hub import access, clock, public_pages
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.routes import members as member_routes
from maity_hub.routes import projects as project_routes
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


def _project_routes(app: Any) -> list[tuple[str, str]]:
    """(method, path template) of every route under `/api/v1/projects/{owner}/{slug}`."""
    found: list[tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == API or route.path.startswith(API + "/"):
            found += [(method, route.path) for method in sorted(route.methods)]
    return sorted(found)


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
    app = make_client().app
    routes = {
        (method, route.path): route
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    for method, path in access.OUTSIDE_READS:
        assert method == "GET", path
        assert (method, path) in routes, (method, path)
    for (method, path), route in routes.items():
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


def test_an_agents_owner_outside_the_project_passes_the_gate_as_before(
    world: World, make_client: ClientFactory, migrated: Engine
) -> None:
    """An owner whose agent is a member keeps the calls §1.3 lists for them: the gate passes
    them, and the route answers as it always did (their agent's briefings, §6.2)."""
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
