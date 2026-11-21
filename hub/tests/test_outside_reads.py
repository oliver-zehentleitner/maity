"""docs/api.md §2.3 "Reading a public project from outside": a signed-in human without an
active membership reads a public project's view, its members and its cards, with their history
and notes, its logo and banner, and its Why view while the repository is public, through a
closed allow-list (`access.OUTSIDE_READS`); every
other project route answers them `not_found`, a write before its body is read (§1.3)."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, func, insert, select, update

from maity_hub import access, avatars, clock, forge, images, ktw, ktw_reads, public_pages
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
from tests import test_keep_the_why as why_tests
from tests.conftest import ClientFactory
from tests.test_keep_the_why_views import lean
from tests.test_tasks import task

P = "/projects/maintainer/maity"
WHY = f"{P}/keep-the-why"
WHY_READS = (WHY, f"{WHY}/export", f"{WHY}/bodies")
API = access.API_PROJECT
NOT_FOUND = {"error": {"code": "not_found", "message": "no such resource", "details": {}}}
RESTRICTED = "RESTRICTED-SENTINEL-7f3a"  # a card's restricted text (§6.4)
REASON = "REASON-SENTINEL-91c2"  # a redaction's reason (§8.5)
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
REPOSITORY = "https://github.com/maintainer/maity"
NEVER_IN_PROJECT = {"repository", "memory", "setup", "policy", "attachments", "aliases"}
MEMBER_KEYS = set(member_routes.OUTSIDE_MEMBER_KEYS)
# Signs of presence or isolation, and what only an admin, the member or an owner reads.
NEVER_IN_MEMBER = {
    "isolation_windows", "isolated", "last_seen_at", "presence", "availability", "paused",
    "session", "instances", "covered_by", "covering", "moderation", "briefing", "owner",
    "credentials", "shared_environment", "owner_preferences", "harness", "model", "team",
}  # fmt: skip


INSTANCE_TOKEN = "instance-token"
# The operator's own namespaces, which the instance's token serves (§11.4): the world's project
# is the maintainer's, so an outsider reads its Why, as the public view shows it (§16.9).
INSTANCE: dict[str, Any] = {
    "forge_github_token": INSTANCE_TOKEN,
    "forge_instance_namespaces": frozenset({"maintainer"}),
}


@pytest.fixture
def make_client(make_client: ClientFactory) -> ClientFactory:
    """Every hub here serves public pages: while it serves none, no project is public (§16.9).
    It holds the instance's token for the maintainer's namespace (`INSTANCE`)."""
    return lambda **kw: make_client(**{"public_pages": True, **INSTANCE, **kw})


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


class WhyForge(why_tests.Fake):
    """§11.3's fake forge (tests/test_keep_the_why.py) with the sources of §11.4. The forge
    answers `/repos/acme/widget` with `private` and shows a private repository's files to a
    grant alone. Each file read records its reader's `granted` (`grants`), each visibility
    question counts (`asked`), and each `Forge.for_project` call records its project (`bound`).

    `Forge.for_project` stands for the project's own source and always answers the namespace
    owner's grant, as tests/test_keep_the_why_views.py sets it up. Only the member side reaches
    it: that is what shows a member's read through a grant never reaching an outsider. The
    outsider's path never calls it (`ktw_reads.OUTSIDE_CACHE` has `bind=False`, and the token
    is chosen by the operator's namespaces), so no outsider test depends on the stub."""

    def forget(self) -> None:
        """Drop what the recorders saw so far: a test's own reads start from here."""
        self.grants.clear()
        self.tokens.clear()
        self.bound.clear()
        self.events.clear()
        self.asked = 0

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.private = False
        self.grants: list[str | None] = []
        self.tokens: list[str | None] = []  # each file read's token
        self.asked = 0
        self.bound: list[str] = []
        self.events: list[str] = []  # "repos" for a visibility question, "file" for a file read
        # A named repository's files (`acme/other`, which the family names as a URL child), and
        # whether the forge reports it private.
        self.foreign: dict[str, Any] = {}
        self.named_private = False
        fake = self

        def file(reader: forge.Forge, repository: str, path: str, cap: int) -> bytes | None:
            fake.events.append("file")
            fake.file_reads.append(path)
            fake.grants.append(reader.granted)
            fake.tokens.append(reader.token)
            if repository.lower() != "acme/widget":
                return None if fake.named_private else fake.foreign.get(path)
            if fake.private and reader.granted is None:
                return None  # a private repository answers 404 without a grant
            found = fake.files.get(path)
            if isinstance(found, BaseException):
                raise found
            return found

        def for_project(reader: forge.Forge, project_id: str) -> forge.Forge:
            fake.bound.append(project_id)
            return forge.Forge("owner-grant", granted="owner_token", repository="acme/widget")

        def send(reader: forge.Forge, path: str, query: Any = None, **kwargs: Any) -> Any:
            if path == "/repos/acme/widget":
                fake.events.append("repos")
                fake.asked += 1
                return {"private": fake.private}
            if path == "/repos/acme/other":
                fake.events.append("repos")
                return {"private": fake.named_private}
            return None

        def require_public(reader: forge.Forge, repository: str) -> None:
            return None

        monkeypatch.setattr(forge.Forge, "file", file)
        monkeypatch.setattr(forge.Forge, "for_project", for_project)
        monkeypatch.setattr(forge.Forge, "_require_public", require_public)
        monkeypatch.setattr(forge.Forge, "_send", send)


@pytest.fixture
def why(monkeypatch: pytest.MonkeyPatch) -> WhyForge:
    """The repository's Keep the Why family through a fake forge (`WhyForge`), its root a lean
    export with a bodies file."""
    found = WhyForge(monkeypatch)
    found.family()
    lean(found, f"{why_tests.BASE}/state.json", why_tests.entry(1), why_tests.entry(2, "open"))
    return found


def _repository(engine: Engine, project_id: str, url: str | None, public: bool | None) -> None:
    """The project's repository and the hub's last look at it (§16.9), as the probe leaves them."""
    with engine.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(repository_url=url, repository_public=public)
        )


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, why: WhyForge) -> World:
    """A public project with a card, its history, a note, a redacted note and entry, a
    restricted text, an agent member, a logo and a banner, a public repository with a Keep the
    Why export (`why`), and a human who is no member."""
    owner = flow.human(make_client, migrated)
    outsider = flow.human(make_client, migrated, "reader")
    project_id = str(flow.project(owner, "maity", public_page="on")["id"])
    _repository(migrated, project_id, why_tests.REPO, True)
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


def test_an_agents_owner_outside_the_project_reads_its_briefing_view_as_on_a_private_one(
    world: World, migrated: Engine
) -> None:
    """`GET …/members/{id}/briefing` (§19.3.1) is one of the owner calls: an owner outside a
    public project reads the same projection of its agent as outside a private one."""
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == world.agent.id)
            .values(owner_id=world.outsider.id)
        )
    path = f"{P}/members/{world.agent.id}/briefing"

    def shape() -> tuple[set[str], set[str]]:
        answer = world.outsider.get(path)
        assert answer.status_code == 200, answer.text
        view = answer.json()
        return set(view), set(view["membership"])

    public = shape()
    assert public[0] == {"generated_at", "me", "membership"}
    _page(migrated, world.project_id, on=False)
    assert shape() == public


def _session_seen(engine: Engine, human_id: str, at: Any = None) -> Any:
    """The human's sessions' `last_seen_at`, set to `at` first when given."""
    s = t.human_session.c
    with engine.begin() as conn:
        if at is not None:
            conn.execute(
                update(t.human_session).where(s.human_id == human_id).values(last_seen_at=at)
            )
        return sorted(conn.execute(select(s.last_seen_at).where(s.human_id == human_id)).scalars())


@pytest.mark.parametrize(
    "extra",
    [
        {"Authorization": ""},
        {"Maity-For": ""},
        {"Maity-For": "agt-anyone"},
        {"Authorization": "", "Maity-For": "agt-anyone"},
    ],
    ids=["empty_authorization", "empty_maity_for", "maity_for", "both"],
)
def test_a_cookie_call_with_an_empty_authorization_or_a_maity_for_is_gated_as_an_outsiders(
    world: World, migrated: Engine, extra: dict[str, str]
) -> None:
    """The gate reads the caller as `caller.authenticate` does: only a non-empty
    `Authorization` header authenticates instead of the cookie, and `Maity-For` authenticates
    nothing, so these calls are the cookie's human, an outsider: `not_found` before the body
    is read, and the session is not touched (no presence write, no cookie set)."""
    stale = clock.now() - timedelta(minutes=10)
    before = _session_seen(migrated, world.outsider.id, stale)
    headers = {**_as(world.outsider), "Content-Type": "application/json", **extra}
    refused = world.outsider.client.post(f"/api/v1{P}/tasks", json={"title": 5}, headers=headers)
    assert (refused.status_code, refused.json()) == (404, NOT_FOUND), refused.text
    assert "set-cookie" not in refused.headers
    assert _session_seen(migrated, world.outsider.id) == before


def test_a_bridges_call_on_a_public_project_is_answered_as_before(
    world: World, make_client: ClientFactory, migrated: Engine
) -> None:
    """A bridge calls with its own `Authorization` and `Maity-For` (§2.3): the gate passes it,
    and its write, a bad body included, is answered as on any project."""
    from tests.test_bridge_calls import Calls, _pair

    served, bridge, _ = _pair(migrated, world.owner)
    calls = Calls(make_client(), bridge)
    made = calls.post(f"{P}/tasks", {"title": "Carried"}, served.agent_id)
    assert made.status_code == 201, made.text
    assert made.json()["created_by"] == served.agent_id
    bad = calls.post(f"{P}/tasks", {"title": 5}, served.agent_id)
    assert (bad.status_code, bad.json()["error"]["code"]) == (400, "invalid"), bad.text


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


def test_member_views_are_the_allow_list_of_their_keys(world: World, migrated: Engine) -> None:
    """An outsider's member view holds exactly the keys of `OUTSIDE_MEMBER_KEYS` the member's
    view has, at every level (`manages` its `OUTSIDE_COUNT_KEYS`), so a key the view gains
    later stays hidden; no sign of presence or isolation, no gated field."""
    items = world.outsider.get(f"{P}/members").json()["items"]
    assert world.outsider.id not in {m["id"] for m in items}  # a reader is no member
    assert {world.owner.id, world.agent.id} <= {m["id"] for m in items}
    single = [world.outsider.get(f"{P}/members/{m['id']}").json() for m in items]
    for view in items + single:
        whole = world.owner.get(f"{P}/members/{view['id']}").json()  # an admin's read
        assert set(view) <= MEMBER_KEYS, set(view) - MEMBER_KEYS
        links = {"website", "social"}  # as `links_visible` admits each reader (§16.9)
        expected = (set(whole) & MEMBER_KEYS) - links
        assert set(view) - links == expected, (set(view) - links) ^ expected
        assert not NEVER_IN_MEMBER & set(view), view
        assert set(view["manages"]) == {"direct", "total"}
        for counts in view["manages"].values():
            assert set(counts) == set(member_routes.OUTSIDE_COUNT_KEYS), counts
    # The counter-check: the owner, an admin, reads every one of them.
    agent = world.owner.get(f"{P}/members/{world.agent.id}").json()
    assert {"isolation_windows", "isolated", "last_seen_at", "presence", "owner"} <= set(agent)
    assert {"session", "instances", "availability", "paused"} <= set(agent)
    assert world.outsider.get(f"{P}/members/{world.outsider.id}").status_code == 404
    # A key the view gains later is not in the outsider's.
    agent_row = _membership_row(migrated, world)
    later = member_routes.outside_member_view(
        {**agent, "added_later": 1}, agent_row, set(), picture=None
    )
    assert "added_later" not in later


def _membership_row(engine: Engine, world: World) -> Any:
    """The world's agent's membership row, as the member routes read it."""
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == world.project_id,
                t.membership.c.agent_id == world.agent.id,
            )
        ).one()


def test_isolated_and_held_members_are_not_in_an_outsiders_member_reads(
    world: World, make_client: ClientFactory, migrated: Engine
) -> None:
    """As the public page names them (§16.9, `public_project_views.members`): an isolated
    agent and one under a moderation hold on its profile are in no member list an outsider
    reads, `GET …/members/{id}` answers `not_found` for them, no edge names them and no
    count counts them; a member reads them as before."""
    owner_row = _membership_of(migrated, world.project_id, human_id=world.owner.id)
    isolated = flow.agent(make_client, world.owner)
    held = flow.agent(make_client, world.owner)
    with migrated.begin() as conn:
        m = t.membership.c
        conn.execute(
            update(t.membership)
            .where(m.project_id == world.project_id, m.agent_id == isolated.id)
            .values(isolated_since=clock.now())
        )
        conn.execute(
            update(t.membership)
            .where(m.project_id == world.project_id, m.agent_id.in_([isolated.id, held.id]))
            .values(reports_to=owner_row)
        )
        held_row = conn.execute(
            select(m.id).where(m.project_id == world.project_id, m.agent_id == held.id)
        ).scalar_one()
        conn.execute(
            update(t.membership)
            .where(m.project_id == world.project_id, m.agent_id == world.agent.id)
            .values(reports_to=held_row)
        )
        report_id = "rpt-heldprofile1"
        conn.execute(
            insert(t.abuse_report).values(
                id=report_id, reporter=world.owner.id, account_id=world.owner.id,
                target_type="profile", target_id=held.id, reason="spam", status="resolved",
                action="hide", created_at=clock.now(),
            )
        )  # fmt: skip
        conn.execute(
            insert(t.moderation_hold).values(
                report_id=report_id,
                target_type="profile",
                target_id=held.id,
                action="hide",
                at=clock.now(),
            )
        )
    hidden = {isolated.id, held.id}
    items = world.outsider.get(f"{P}/members").json()["items"]
    assert not hidden & {m["id"] for m in items}
    assert {world.owner.id, world.agent.id} <= {m["id"] for m in items}
    for agent_id in hidden:
        refused = world.outsider.get(f"{P}/members/{agent_id}")
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), agent_id
    agent = world.outsider.get(f"{P}/members/{world.agent.id}").json()
    assert agent["reports_to"] is None  # its manager is one the outsider does not read
    owner = world.outsider.get(f"{P}/members/{world.owner.id}").json()
    assert owner["manages"]["direct"]["members"] == 0
    assert not any(agent_id in str(items) for agent_id in hidden)
    inside = {m["id"] for m in world.owner.get(f"{P}/members").json()["items"]}
    assert hidden <= inside
    assert world.owner.get(f"{P}/members/{world.agent.id}").json()["reports_to"] == held.id


def test_member_views_leave_out_what_is_computed_from_presence(
    world: World, migrated: Engine
) -> None:
    """`availability` (its state is `offline` or `available` by presence) and the `online`
    and `dormant` counts of `manages` (counts of presence) leave an outsider's member views
    with `presence`; how many members and instances stand behind a member stays."""
    owner_row = _membership_of(migrated, world.project_id, human_id=world.owner.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.project_id == world.project_id)
            .where(t.membership.c.agent_id == world.agent.id)
            .values(reports_to=owner_row)
        )
    items = world.outsider.get(f"{P}/members").json()["items"]
    single = world.outsider.get(f"{P}/members/{world.owner.id}").json()
    for view in [*items, single]:
        assert "availability" not in view, view
        for part in ("direct", "total"):
            counts = view["manages"][part]
            assert not {"online", "dormant"} & set(counts), counts
            assert {"members", "instances"} <= set(counts), counts
    assert single["manages"]["direct"]["members"] == 1
    inside = world.owner.get(f"{P}/members/{world.owner.id}").json()
    assert "state" in inside["availability"]
    assert {"members", "instances", "online", "dormant"} <= set(inside["manages"]["direct"])


def test_an_outsiders_member_views_carry_the_picture_the_public_page_shows(
    world: World, migrated: Engine
) -> None:
    """`avatar_url` in an outsider's member views is the picture the public page shows
    (`public_projects.member_pictures`, §2.3, §16.9): a person's public address while their
    `public_profile` is on, `null` while it is off, an agent's always; the address answers the
    outsider. A member's views keep the member address (`avatars.url_of`), as before."""
    from tests.test_avatars import image, put_human

    uploaded = put_human(world.owner, "/me/avatar", image())
    assert uploaded.status_code == 200, uploaded.text
    member_url = uploaded.json()["avatar_url"]
    shown_both = (world.owner.id, world.agent.id)

    def profile(on: bool) -> None:
        with migrated.begin() as conn:
            conn.execute(
                update(t.human).where(t.human.c.id == world.owner.id).values(public_profile=on)
            )

    def pictures() -> dict[str, Any]:
        items = world.outsider.get(f"{P}/members").json()["items"]
        listed = {m["id"]: m["avatar_url"] for m in items}
        single = {
            i: world.outsider.get(f"{P}/members/{i}").json()["avatar_url"] for i in shown_both
        }
        assert {i: listed[i] for i in shown_both} == single
        return single

    profile(True)
    shown = pictures()
    assert shown[world.owner.id] == avatars.public_url(member_url.split("?v=", 1)[1])
    for principal in shown_both:
        url = shown[principal]
        assert url is not None and url.startswith("/api/v1/avatars/public/"), (principal, url)
        served = world.outsider.client.get(url)
        assert served.status_code == 200, (principal, served.text)
    profile(False)
    hidden = pictures()
    assert hidden[world.owner.id] is None
    assert hidden[world.agent.id] == shown[world.agent.id]
    inside = {m["id"]: m["avatar_url"] for m in world.owner.get(f"{P}/members").json()["items"]}
    assert inside[world.owner.id] == member_url
    assert inside[world.agent.id].startswith(f"/api/v1/avatars/{world.agent.id}?v=")
    assert world.owner.get(f"{P}/members/{world.owner.id}").json()["avatar_url"] == member_url


def test_a_removed_member_reads_as_an_outsider(world: World, migrated: Engine) -> None:
    """`access.reader`: a membership that is no longer active reads the public project as any
    outsider does (§2.3): the allow-listed reads, the project's and the member's allow-lists,
    and `not_found` on any other route, a write before its body is read."""
    factory.membership(migrated, world.project_id, "member", human_id=world.outsider.id)
    joined = _membership_of(migrated, world.project_id, human_id=world.outsider.id)
    inside = world.outsider.get(f"{P}/members").json()["items"]
    assert world.outsider.id in {m["id"] for m in inside}  # a member, while active
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == joined)
            .values(active=None, removed_at=clock.now())
        )
    view = world.outsider.get(P)
    assert view.status_code == 200, view.text
    assert set(view.json()) == set(project_routes.OUTSIDE_PROJECT_KEYS)
    items = world.outsider.get(f"{P}/members").json()["items"]
    assert world.outsider.id not in {m["id"] for m in items}
    for item in items:
        assert set(item) <= MEMBER_KEYS, set(item) - MEMBER_KEYS
    assert world.outsider.get(f"{P}/members/{world.outsider.id}").status_code == 404
    for path in _reads(world):
        assert world.outsider.client.get(path).status_code == 200, path
    headers = {**_as(world.outsider), "Content-Type": "application/json"}
    for body in ({"title": "A card"}, {"title": 5}):
        refused = world.outsider.client.post(f"/api/v1{P}/tasks", json=body, headers=headers)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (body, refused.text)


def test_a_link_into_a_private_repository_is_null_in_an_outsiders_project_view(
    world: World, migrated: Engine
) -> None:
    """`links` as the public page shows them (§2.3, §16.9, `project_links.public`): a link into
    the repository's own path is `null` while the hub's last look did not find the repository
    public, any other link as set; a member reads every link as set."""
    into = "https://github.com/maintainer/maity/issues"
    elsewhere = "https://example.org/docs"
    linked = world.owner.patch(P, {"links": {"issues": into, "docs": elsewhere}})
    assert linked.status_code == 200, linked.text

    def repository(public: bool) -> None:
        with migrated.begin() as conn:
            conn.execute(
                update(t.project)
                .where(t.project.c.id == world.project_id)
                .values(repository_url=REPOSITORY, repository_public=public)
            )

    repository(False)
    links = world.outsider.get(P).json()["links"]
    assert (links["issues"], links["docs"]) == (None, elsewhere)
    inside = world.owner.get(P).json()["links"]
    assert (inside["issues"], inside["docs"]) == (into, elsewhere)
    repository(True)
    assert world.outsider.get(P).json()["links"]["issues"] == into


def test_the_logo_and_banner_reach_an_outsider_without_the_forge_read_through(
    world: World, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An outsider's read leaves no trace (§2.3), so `GET …/logo` and `GET …/banner` give it
    what is stored and never `images.read_through`: the upload, else `not_found`. A member's
    read with nothing stored reads through the forge, as before (§11.2)."""
    read_through: list[str] = []

    def recorded(*args: Any) -> bool:
        read_through.append(args[-1])
        return False  # the forge did not answer

    monkeypatch.setattr(images, "read_through", recorded)
    with migrated.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == world.project_id)
            .values(repository_url=REPOSITORY)
        )
    for kind in images.KINDS:
        stored = world.outsider.client.get(f"/api/v1{P}/{kind}")
        assert stored.status_code == 200, (kind, stored.text)
        assert stored.content.startswith(b"\x89PNG"), kind
        removed = world.owner.delete(f"{P}/{kind}")
        assert removed.status_code == 200, (kind, removed.text)
        nothing = world.outsider.client.get(f"/api/v1{P}/{kind}")
        assert (nothing.status_code, nothing.json()) == (404, NOT_FOUND), kind
    assert read_through == []
    for kind in images.KINDS:  # the counter-check: a member's read reads through
        member = world.owner.client.get(f"/api/v1{P}/{kind}")
        assert member.status_code == 503, (kind, member.text)
    assert read_through == list(images.KINDS)


# --- the Why view: only while the repository is public (option A, req-vsfjgx3fch8k) -------------


def test_an_outsider_reads_the_why_while_the_repository_is_public(
    world: World, why: WhyForge
) -> None:
    """`GET …/keep-the-why` (§11.3), `…/export` and `…/bodies` (§11.5) are among the outsider's
    reads (§2.3) and answer it as a member while the hub last found the repository public."""
    templates = {("GET", API + path.removeprefix(P)) for path in WHY_READS}
    assert templates <= access.OUTSIDE_READS
    for path in WHY_READS:
        outside = world.outsider.get(path)
        assert outside.status_code == 200, (path, outside.text)
        assert world.owner.get(path).status_code == 200, path
    root = f"{why_tests.BASE}/state.json"
    assert world.outsider.get(f"{WHY}/export").json()["state"] == why.states[root]
    summary = world.outsider.get(WHY).json()
    assert [m["path"] for m in summary["members"]] == [
        m["path"] for m in world.owner.get(WHY).json()["members"]
    ]


@pytest.mark.parametrize(
    ("url", "public"),
    [(why_tests.REPO, False), (why_tests.REPO, None), (None, None)],
    ids=["private", "unknown", "no_repository"],
)
def test_the_why_is_not_found_to_an_outsider_while_the_repository_is_not_public(
    world: World, migrated: Engine, url: str | None, public: bool | None
) -> None:
    """Only while the hub last found the repository public (`repository_public is True`), as
    the public view's **Why** (§16.9): otherwise each read answers an outsider the `not_found`
    of a route closed to it, an `If-None-Match` too (never `304`); a member reads as before."""
    etags = {
        kind: world.owner.get(f"{WHY}/{kind}").headers["ETag"] for kind in ("export", "bodies")
    }
    _repository(migrated, world.project_id, url, public)
    for path in WHY_READS:
        refused = world.outsider.get(path)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
        member = world.owner.get(path)
        assert member.status_code == (200 if url else 409), (path, member.text)
    for kind, etag in etags.items():
        revalidated = world.outsider.get(f"{WHY}/{kind}", headers={"If-None-Match": etag})
        assert (revalidated.status_code, revalidated.json()) == (404, NOT_FOUND), kind


def test_the_why_is_not_found_to_an_outsider_with_public_pages_off(
    world: World, settings: Settings
) -> None:
    """With public pages off no project is public (§16.9): `access.reader` refuses the outsider
    before the repository is looked at; a member reads as before."""
    public_pages.configure(replace(settings, public_pages=False))
    try:
        for path in WHY_READS:
            refused = world.outsider.get(path)
            assert (refused.status_code, refused.json()) == (404, NOT_FOUND), path
            assert world.owner.get(path).status_code == 200, path
    finally:
        public_pages.configure(replace(settings, public_pages=True))


def test_max_age_zero_holds_an_outsider_to_one_read_per_interval(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`max_age=0` forces at most one read per `ktw.FORCE_INTERVAL` per project for the
    outsiders' cache (`ktw_reads.OUTSIDE_CACHE`), as for the members' (§2.3, §11.3): within
    it an outsider's call is answered from that cache, no file and no visibility read again."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    forced = {"max_age": 0}
    first = world.outsider.get(WHY, params=forced)
    assert first.status_code == 200 and first.json()["fresh"] is True, first.text
    reads = (len(why.file_reads), len(why.state_reads), why.asked)
    held = world.outsider.get(WHY, params=forced)
    assert held.status_code == 200 and held.json()["fresh"] is False, held.text
    assert world.outsider.get(f"{WHY}/export", params=forced).status_code == 200
    assert (len(why.file_reads), len(why.state_reads), why.asked) == reads, "within the interval"
    now[0] += ktw.FORCE_INTERVAL + 1
    again = world.outsider.get(WHY, params=forced)
    assert again.status_code == 200 and again.json()["fresh"] is True, again.text
    assert len(why.file_reads) > reads[0] and why.asked > reads[2]


def test_max_age_zero_on_the_bodies_is_held_to_the_shared_window(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GET …/keep-the-why/bodies?max_age=0` holds an outsider to the window it shares with the
    members (§2.3, §11.5): within `ktw.FORCE_INTERVAL` of a member's forced read the outsider's
    makes no family read and no file read; after it, a forced read happens again."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    bodies, forced = f"{WHY}/bodies", {"max_age": 0}
    assert world.outsider.get(bodies, params=forced).status_code == 200  # its own entry first
    now[0] += ktw.FORCE_INTERVAL + 1
    assert world.owner.get(bodies, params=forced).status_code == 200  # the member's forced read
    reads = (len(why.file_reads), len(why.state_reads))
    held = world.outsider.get(bodies, params=forced)
    assert held.status_code == 200, held.text
    assert (len(why.file_reads), len(why.state_reads)) == reads, "within the member's interval"
    now[0] += ktw.FORCE_INTERVAL + 1
    assert world.outsider.get(bodies, params=forced).status_code == 200
    assert len(why.file_reads) > reads[0]


def test_an_outsiders_why_reads_never_ask_the_projects_source(
    world: World, why: WhyForge, migrated: Engine
) -> None:
    """An outsider's read leaves no trace (§2.3): the token is chosen by the operator's
    namespaces, as the public page chooses it, so `Forge.for_project`, which may write the
    project's `probe_via` and the grants' state, is never called on the outsider's path, and
    the project's row is the same after all three reads (A1830 P1)."""

    def project_row() -> Any:
        with migrated.connect() as conn:
            return conn.execute(select(t.project).where(t.project.c.id == world.project_id)).one()

    before = project_row()
    why.forget()  # the world's own setup reads (a member's view, the page) are not the outsider's
    for path in WHY_READS:
        for query in ({}, {"max_age": 0}):
            assert world.outsider.get(path, params=query).status_code == 200, (path, query)
    assert why.bound == []
    assert why.grants and None in why.grants and "owner_token" not in why.grants
    assert project_row() == before
    assert world.owner.get(WHY).status_code == 200  # the counter-check: a member's read asks
    assert why.bound


def test_the_forced_read_is_shared_by_members_and_outsiders_each_served_their_own(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ktw.CACHE` and `ktw_reads.OUTSIDE_CACHE` are each other's `peer`: a forced read in one
    within `ktw.FORCE_INTERVAL` of a read in the other makes no family read and serves the
    cache's own older entry, never the other's (§2.3: "the same one forge read per 30 seconds
    per project as for a member"); after the interval a forced read happens again."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    forced = {"max_age": 0}
    root = f"{why_tests.BASE}/state.json"

    def entries(who: flow.Human) -> tuple[int, bool]:
        """The summary's entry count and `fresh`, for a forced read by `who`."""
        answer = who.get(WHY, params=forced)
        assert answer.status_code == 200, answer.text
        body = answer.json()
        return int(body["summary"]["entries"]), bool(body["fresh"])

    seeded = entries(world.outsider)  # each cache's first read happens: nothing of its own yet
    assert seeded[1] is True
    assert entries(world.owner)[1] is True
    lean(why, root, why_tests.entry(1), why_tests.entry(2, "open"), why_tests.entry(3, "open"))
    now[0] += ktw.FORCE_INTERVAL + 1
    member = entries(world.owner)  # the member's forced read, the outsider's 31 s old
    assert member == (seeded[0] + 1, True)
    reads = len(why.file_reads)
    assert entries(world.outsider) == (seeded[0], False)  # its own older entry, not the member's
    assert len(why.file_reads) == reads, "a family read within the member's interval"
    now[0] += ktw.FORCE_INTERVAL + 1
    assert entries(world.outsider) == (seeded[0] + 1, True)  # the outsider's forced read
    reads = len(why.file_reads)
    assert entries(world.owner) == (seeded[0] + 1, False)
    assert len(why.file_reads) == reads, "a family read within the outsider's interval"
    now[0] += ktw.FORCE_INTERVAL + 1
    assert entries(world.owner)[1] is True
    assert len(why.file_reads) > reads


def test_a_refresh_for_an_outsider_asks_the_forge_once_before_its_file_reads(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every content fetch for an outsider follows a live visibility answer in the same request
    (the lead's rule, seq 186723): a forced refresh past the shared window asks `/repos/…`
    exactly once, before its first file read, and the endpoint reuses the gate's answer."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    assert world.outsider.get(WHY).status_code == 200
    now[0] += ktw.FORCE_INTERVAL + 1
    why.forget()
    again = world.outsider.get(WHY, params={"max_age": 0})
    assert again.status_code == 200 and again.json()["fresh"] is True, again.text
    first_file = why.events.index("file")
    assert why.events[:first_file] == ["repos"], why.events
    assert why.events.count("repos") == 1, why.events


def test_a_repository_private_inside_the_window_gets_no_file_read_for_an_outsider(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repository turns private inside the window, the kept answers still fresh; the
    outsider then forces a refresh past the shared 30 s window: no content file is fetched and
    all three reads answer `not_found` (the lead's rule, seq 186723, A1863 point 1)."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    for path in WHY_READS:
        assert world.outsider.get(path).status_code == 200, path
    why.private = True
    now[0] += ktw.FORCE_INTERVAL + 1
    reads = len(why.file_reads)
    for path in WHY_READS:
        refused = world.outsider.get(path, params={"max_age": 0})
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
    assert len(why.file_reads) == reads


def test_a_kept_public_answer_does_not_stand_in_for_a_new_read(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kept positive answer only lets the outsiders' cache serve what it holds: a read the
    cache has to make (here a cold one, its entry dropped) asks the forge live first, even
    while the kept answer is fresh, and fetches nothing when the forge says private."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    assert world.outsider.get(WHY).status_code == 200  # the kept answer: public, at 1000
    ktw_reads.OUTSIDE_CACHE.forget(world.project_id)
    why.private = True
    now[0] += 5  # inside every window: the gate and the endpoint use the kept answer
    why.forget()
    reads = len(why.file_reads)
    for path in WHY_READS:
        refused = world.outsider.get(path)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
    assert len(why.file_reads) == reads
    assert why.asked >= 1  # asked live before the read the cache would have made


@pytest.mark.parametrize(
    ("query", "paths"),
    [
        ({"max_age": "-1"}, WHY_READS),
        ({"canonical": "x" * 2049}, WHY_READS[1:]),  # the summary takes no `canonical`
    ],
    ids=["max_age", "canonical"],
)
def test_a_bad_query_answers_an_outsider_not_found_while_the_forge_says_private(
    world: World, why: WhyForge, query: dict[str, str], paths: tuple[str, ...]
) -> None:
    """The live visibility decision comes before the query is read (`access.gate`, A1863
    point 2): the forge says private while the stored `repository_public` is still true, so an
    outsider with a bad query gets `not_found`, never `400`; a member gets `400`."""
    why.private = True
    for path in paths:
        refused = world.outsider.get(path, params=query)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
        member = world.owner.get(path, params=query)
        assert (member.status_code, member.json()["error"]["code"]) == (400, "invalid"), path


class _CountingCache(ktw.Cache):
    """A cache whose family read is counted, stores an empty answer, and may wait for `go`."""

    def __init__(self, reads: list[bool], go: threading.Event | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.reads, self.go = reads, go

    def _read(
        self, reader: forge.Forge, project_id: str, repository_url: str | None, last: Any
    ) -> Any:
        self.reads.append(self.bind)
        if self.go is not None:
            assert self.go.wait(5)
        return ktw._Entry(None, ktw.now(), repository_url)


def test_overlapping_cold_requests_make_one_read() -> None:
    """Under the shared per-project lock an overlapping request waits for the read under way
    and serves what it stored (`ktw.Cache.get`)."""
    reads: list[bool] = []
    go = threading.Event()
    cache = _CountingCache(reads, go)
    answers: list[bool] = []

    def call() -> None:
        answers.append(cache.get(forge.Forge(None), "prj-overlap", why_tests.REPO, 0)[1])

    first = threading.Thread(target=call)
    first.start()
    for _ in range(500):
        if reads:
            break
        time.sleep(0.01)
    second = threading.Thread(target=call)
    second.start()
    time.sleep(0.05)
    go.set()
    first.join(5)
    second.join(5)
    assert reads == [True]
    assert sorted(answers) == [False, True]


def test_a_warm_caller_gets_its_own_entry_at_once_while_a_read_is_under_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller with its own entry for the repository does not wait for the lock another
    request holds for its read: it gets that entry at once, `fresh: false` (`ktw.Cache.get`,
    the lead, seq 187206)."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    reads: list[bool] = []
    cache = _CountingCache(reads)
    reader, project = forge.Forge(None), "prj-warm"
    kept = cache.get(reader, project, why_tests.REPO, 0)[0]  # its own entry, at 1000
    go = threading.Event()
    cache.go = go
    now[0] += ktw.FORCE_INTERVAL + 1
    holder = threading.Thread(target=lambda: cache.get(reader, project, why_tests.REPO, 0))
    holder.start()
    for _ in range(500):
        if len(reads) == 2:
            break
        time.sleep(0.01)
    assert len(reads) == 2  # the holder's read is under way, holding the lock
    began = time.monotonic()
    entry, fresh = cache.get(reader, project, why_tests.REPO, 0)
    waited = time.monotonic() - began
    go.set()
    holder.join(5)
    assert (entry, fresh) == (kept, False)
    assert waited < ktw.LOCK_WAIT
    assert len(reads) == 2


def test_an_outsiders_file_fetch_asks_the_forge_first(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The export and bodies fetch a published file themselves when the store misses, while the
    family is still kept: for an outsider that fetch, too, follows the forge's answer in the
    same request (the lead, seq 187206, ukxh A1875). The repository turns private with the kept
    public answer still within its window: no file is fetched and the answer is `not_found`."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    for path in WHY_READS:
        assert world.outsider.get(path).status_code == 200, path  # the family kept, at 1000
    ktw.RAW.clear()  # the files dropped from the store; the family stays in OUTSIDE_CACHE
    why.private = True
    # Past the files' 30 s hold, inside the kept answer's and the family's 600 s: the gate and
    # the endpoint use the kept answer, and only the file fetch would reach the forge.
    now[0] += ktw.FORCE_INTERVAL + 1
    states = len(why.state_reads)
    for path in WHY_READS[1:]:
        refused = world.outsider.get(path)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
    assert len(why.state_reads) == states, "a published file fetched for an outsider"
    assert why.asked >= 1


def test_an_outsiders_fetch_of_a_named_repositorys_file_asks_about_that_repository(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A named repository (`?canonical=`): its family kept in `ktw_reads.FOREIGN` and its state
    file in the store, its bodies file never fetched. The named repository turns private: the
    outsider's bodies read asks the forge about that repository, not the project's own, in the
    same request, fetches nothing and answers `not_found` (the lead, seq 187245, zxjn A1830)."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    other, other_base = "https://github.com/acme/other", "https://other.example/ktw"
    why.foreign[".keep-the-why"] = why_tests.kfile(f"{other_base}/state.json", "acme---other")
    lean(why, f"{other_base}/state.json", why_tests.entry(10))
    assert world.outsider.get(WHY).status_code == 200  # the project's family kept
    named = world.outsider.get(f"{WHY}/export", params={"canonical": other})
    assert named.status_code == 200, named.text  # the named family kept, its state file stored
    why.named_private = True
    now[0] += 5  # inside every window: the kept answers and entries all stand
    reads = (len(why.file_reads), len(why.state_reads))
    why.forget()
    refused = world.outsider.get(f"{WHY}/bodies", params={"canonical": other})
    assert (refused.status_code, refused.json()) == (404, NOT_FOUND), refused.text
    assert (len(why.file_reads), len(why.state_reads)) == reads, "a file fetched for an outsider"
    assert "repos" in why.events  # the named repository was asked about


@pytest.mark.parametrize(
    "raw", ["0", "00", "000", "0.0", "+0", " 0", "5", "600", "86400", "86401", "-1", "0.5", "x"]
)
def test_the_gate_parses_max_age_as_the_route_does(world: World, why: WhyForge, raw: str) -> None:
    """One parser (`ktw.max_age_of`, the route's own pydantic type): a spelling the route
    accepts is a value in the gate too, one it refuses is `None` (the default window)."""
    answer = world.owner.get(WHY, params={"max_age": raw})
    accepted = answer.status_code != 400
    assert (ktw.max_age_of(raw) is not None) == accepted, (raw, answer.status_code)


def test_a_zero_padded_max_age_takes_the_forced_window_in_the_gate(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`max_age=00` is 0 to the gate as to the route (ukxh, A1875): past the 30 s window the
    gate asks the forge live, finds the repository private and answers `not_found` before a
    bad `canonical` is read; with the default window it would have let the `400` through."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    assert world.outsider.get(f"{WHY}/export").status_code == 200  # the kept answer: public
    why.private = True
    now[0] += ktw.FORCE_INTERVAL + 1
    query = {"max_age": "00", "canonical": "x" * 2049}
    refused = world.outsider.get(f"{WHY}/export", params=query)
    assert (refused.status_code, refused.json()) == (404, NOT_FOUND), refused.text


@pytest.mark.parametrize("starving", ["members", "outsiders"])
@pytest.mark.parametrize("asked", [0, ktw.DEFAULT_MAX_AGE], ids=["forced", "normal"])
def test_a_cache_is_not_starved_by_its_linked_peer(
    monkeypatch: pytest.MonkeyPatch, starving: str, asked: int
) -> None:
    """The lead's ruling, seq 187034 (zxjn, A1830): the peer forces a read every 30.1 s; the
    other cache's forced read on its own entry younger than DEFAULT_MAX_AGE still gets that
    entry as it is, but once the entry is past DEFAULT_MAX_AGE the next read refreshes it,
    a normal one (`max_age` the default) and a forced one (`max_age=0`) alike, either way round."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    reads: list[bool] = []
    members, outsiders = _CountingCache(reads), _CountingCache(reads, bind=False)
    members.link(outsiders)
    starver, victim = (members, outsiders) if starving == "members" else (outsiders, members)
    reader, project, url = forge.Forge(None), "prj-starve", why_tests.REPO
    assert victim.get(reader, project, url, 0)[1] is True  # its own entry, at 1000
    start = now[0]
    while True:
        now[0] += 30.1
        assert starver.get(reader, project, url, 0)[1] is True  # the peer's forced read
        if now[0] - start >= ktw.DEFAULT_MAX_AGE:
            break
        assert victim.get(reader, project, url, asked)[1] is False, now[0] - start
    assert victim.get(reader, project, url, asked)[1] is True  # past DEFAULT_MAX_AGE: refreshed


def test_one_forced_read_per_project_across_linked_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lead's ruling, seq 186740: a cold first read is always made (a linked cache's
    answer is never served); a forced read (`max_age=0`) within FORCE_INTERVAL of the last
    read in either cache serves the cache's own entry; after it, a forced read happens."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    reads: list[bool] = []
    members, outsiders = _CountingCache(reads), _CountingCache(reads, bind=False)
    members.link(outsiders)
    reader, project = forge.Forge(None), "prj-linked"
    assert members.get(reader, project, why_tests.REPO, 0)[1] is True
    now[0] += 5
    assert outsiders.get(reader, project, why_tests.REPO, 0)[1] is True  # cold: allowed
    assert outsiders.get(reader, project, why_tests.REPO, 0)[1] is False
    assert reads == [True, False]
    now[0] += ktw.FORCE_INTERVAL - 4  # 31 s after the members' read, 26 s after the outsiders'
    assert members.get(reader, project, why_tests.REPO, 0)[1] is False  # within the window
    now[0] += 5
    assert members.get(reader, project, why_tests.REPO, 0)[1] is True
    assert outsiders.get(reader, project, why_tests.REPO, 0)[1] is False
    assert reads == [True, False, True]


def test_an_outsider_reads_the_why_without_a_grant(world: World, why: WhyForge) -> None:
    """The outsider's reads go through the instance's token, holding no grant and bound to no
    project (`ktw_reads.outside_reader`), never the project's own source, which here is the
    namespace owner's grant; a member's read still uses that grant."""
    why.forget()  # the world's own setup reads (a member's view, the page) are not the outsider's
    for path in WHY_READS:
        assert world.outsider.get(path).status_code == 200, path
    assert why.grants and all(granted is None for granted in why.grants), why.grants
    assert why.tokens and set(why.tokens) == {INSTANCE_TOKEN}, why.tokens
    assert why.asked > 0  # the forge was asked whether the repository is public
    assert world.owner.get(WHY, params={"max_age": 0}).status_code == 200
    assert "owner_token" in why.grants


@pytest.mark.parametrize(
    "overrides",
    [{"forge_instance_namespaces": frozenset({"elsewhere"})}, {"forge_github_token": None}],
    ids=["another_namespace", "no_instance_token"],
)
def test_the_why_is_not_found_to_an_outsider_where_the_instance_token_does_not_serve(
    world: World,
    why: WhyForge,
    make_client: ClientFactory,
    migrated: Engine,
    overrides: dict[str, Any],
) -> None:
    """An outsider reads the Why only where the instance's token serves the project's namespace,
    as the public view shows it (§2.3, §16.9; the lead, seq 186180): elsewhere, or on a hub
    without a token, all three reads answer `not_found`, a bad query too (`access.gate`, before
    it is read), and nothing is asked of the forge, so no anonymous budget is spent. The
    project itself stays public to them, and a member reads the Why as before."""
    client = make_client(**overrides)
    assert factory.login(client, world.outsider.id, engine=migrated).status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    outsider = flow.Human(client, csrf, world.outsider.id, "reader")
    asked, reads = why.asked, len(why.file_reads)
    for path in WHY_READS:
        for query in ({}, {"max_age": "-1"}, {"max_age": 0}):
            refused = outsider.get(path, params=query)
            assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, query)
    assert (why.asked, len(why.file_reads)) == (asked, reads)
    assert outsider.get(P).status_code == 200
    for path in WHY_READS:
        assert world.owner.get(path).status_code == 200, path


def test_after_the_repository_turns_private_an_outsider_gets_nothing_a_grant_read(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member's reads fill the members' cache through the namespace owner's grant; the
    repository then turns private at the forge while the stored `repository_public` is still
    true (the probe has not looked again). The outsider is answered `not_found` on all three
    reads, never the members' cached family or export (F1 of A1829); the member reads on."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    for path in WHY_READS:
        assert world.owner.get(path).status_code == 200, path
    assert "owner_token" in why.grants
    why.private = True
    for path in WHY_READS:
        refused = world.outsider.get(path)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
        assert world.owner.get(path).status_code == 200, path
    assert None not in why.grants  # every file read was the member's, through the grant


def test_an_outsiders_own_cache_ends_at_the_forges_next_visibility_answer(
    world: World, why: WhyForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the outsider read while the repository was public is served from their own cache
    only until the forge is asked again: after `ktw.FORCE_INTERVAL` with `max_age=0`, and at
    the latest after `ktw_reads.VISIBILITY_SECONDS`, a private repository is `not_found`."""
    now = [1000.0]
    monkeypatch.setattr(ktw, "now", lambda: now[0])
    for path in WHY_READS:
        assert world.outsider.get(path).status_code == 200, path
    why.private = True
    now[0] += ktw.FORCE_INTERVAL + 1
    for path in WHY_READS:
        refused = world.outsider.get(path, params={"max_age": 0})
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
    why.private = False
    now[0] += ktw_reads.VISIBILITY_SECONDS + 1
    assert world.outsider.get(WHY).status_code == 200
    why.private = True
    now[0] += ktw_reads.VISIBILITY_SECONDS + 1
    for path in WHY_READS:
        refused = world.outsider.get(path)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)


@pytest.mark.parametrize(
    ("query", "paths"),
    [
        ({"max_age": "-1"}, WHY_READS),
        ({"canonical": "x" * 2049}, WHY_READS[1:]),  # the summary takes no `canonical`
    ],
    ids=["max_age", "canonical"],
)
def test_a_bad_query_answers_an_outsider_not_found_before_validation_while_not_public(
    world: World, migrated: Engine, query: dict[str, str], paths: tuple[str, ...]
) -> None:
    """`ProjectRoute` passes the Why reads through `access.gate` (`PUBLIC_REPOSITORY_READS`):
    while the stored `repository_public` is not true an outsider is answered `not_found`
    before the query is read, so no `400` reaches them (F2 of A1829); with it true the route
    is open to them and the same query is the route's `invalid`, as a member's always is."""
    _repository(migrated, world.project_id, why_tests.REPO, False)
    for path in paths:
        refused = world.outsider.get(path, params=query)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), (path, refused.text)
        member = world.owner.get(path, params=query)
        assert (member.status_code, member.json()["error"]["code"]) == (400, "invalid"), path
    _repository(migrated, world.project_id, why_tests.REPO, True)
    for path in paths:
        opened = world.outsider.get(path, params=query)
        assert (opened.status_code, opened.json()["error"]["code"]) == (400, "invalid"), path


def test_a_release_names_no_hidden_card_to_an_outsider(world: World, migrated: Engine) -> None:
    """`public_cards._release_without` from the outsider's read: a pull request only a hidden
    card reported leaves, a group keeps its visible cards and goes below two, a `task_open`
    blocker for a hidden card, a `group_incomplete` blocker left with fewer than two cards and
    the blocker on a pull request left out go; `readiness.ready` stays as computed."""
    writer = _membership_of(migrated, world.project_id, human_id=world.owner.id)
    secret = factory.card(migrated, world.project_id, writer, title="Hole", label="security")
    plain = factory.card(migrated, world.project_id, writer, title="Plain")
    other = factory.card(migrated, world.project_id, writer, title="Other")
    frozen = {
        "pull_requests": [
            {"number": 1, "task_id": secret, "title": "Fix the hole"},
            {"number": 2, "task_id": plain, "title": "Plain work"},
        ],
        "groups": [[secret, plain], [plain, other, secret]],
        "readiness": {
            "ready": False,
            "blocking": [
                {"reason": "task_open", "task": secret},
                {"reason": "group_incomplete", "tasks": [secret, plain]},
                {"reason": "pr_open", "pr": 1},
                {"reason": "task_open", "task": plain},
            ],
        },
    }
    release = factory.card(
        migrated,
        world.project_id,
        writer,
        kind="release",
        title="Release 1.0.0",
        release_data={"version": "1.0.0", "frozen": frozen},
    )
    card = world.outsider.get(f"{P}/tasks/{release}").json()
    for view in (card, _listed(world.outsider, "")[release]):
        shown = view["release"]
        assert [pr["number"] for pr in shown["pull_requests"]] == [2]
        assert shown["groups"] == [[plain, other]]
        assert shown["readiness"]["blocking"] == [{"reason": "task_open", "task": plain}]
        assert shown["readiness"]["ready"] is False
        assert secret not in str(view)
    inside = world.owner.get(f"{P}/tasks/{release}").json()["release"]
    assert inside["pull_requests"] == frozen["pull_requests"]
    assert inside["groups"] == frozen["groups"]
    assert inside["readiness"] == frozen["readiness"]


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
