"""docs/api.md §2.2, §2.4, §6.2 and §6.17: an agent instance attached to several projects is
authenticated once for all of them and acts, on each call, in the projects the call is for
(hub PR B).

- Authentication decides only what holds everywhere: `signing: required` in any project the
  instance is attached to refuses its Bearer calls on every route, an isolated attachment
  included (the lead, Q7); only a detached one no longer counts.
- A call outside any project writes presence and renews leases in every live attachment that
  is not isolated (the lead, Q10).
- A call on a project's routes acts in the live attachment there alone: none is `not_found`,
  an isolated one `isolated`, both before any side effect, in that order; otherwise presence
  and leases are written in that membership only.
- A read refused as `isolated` is not counted against the read limit (§1.7); a read of a
  project the instance is not attached to is, before its `not_found`.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, update
from starlette.requests import Request

from maity_hub import attached, clock, events, idempotency, instances, namespace, read_limits
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError
from maity_hub.ids import new_id
from tests import factory
from tests.conftest import ClientFactory
from tests.test_auth_agent import bearer, signed

API = "/api/v1"
A = "/projects/maintainer/alpha"
B = "/projects/maintainer/beta"
NOTICE = {"kind": "message", "type": "notice", "to": "all", "body": "hello"}


@dataclass
class World:
    """Projects A and B of one owner, and one agent instance attached to both, with a live
    session and a claimed card in each, its lease at `start`."""

    engine: Engine
    client: TestClient
    agent: factory.Agent
    alpha: str
    beta: str
    in_a: int
    in_b: int
    card_a: str
    card_b: str
    start: datetime

    def call(
        self,
        method: str,
        path: str,
        *,
        sign: bool = True,
        body: Any = None,
        key: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> Any:
        """The agent's call to `path` below /api/v1, signed or as Bearer; a write under `key`,
        else a fresh Idempotency-Key; `extra` headers beside them (Bearer only: a signature
        does not cover them here)."""
        full = f"{API}{path}"
        raw = json.dumps(body).encode() if body is not None else b""
        route, _, query = full.partition("?")
        headers = (
            (signed(self.agent, method, route, query, raw) if sign else bearer(self.agent))
            | {"Content-Type": "application/json"}
            | (extra or {})
        )
        if method != "GET":
            headers["Idempotency-Key"] = key or f"key-{secrets.token_hex(12)}"
        return self.client.request(method, full, headers=headers, content=raw or None)

    def later(self, hours: int = 1) -> None:
        """Move the clock past `SEEN_EVERY` and past the cards' leases."""
        moment = self.start + timedelta(hours=hours)
        clock.set_source(lambda: moment)

    def seen(self, membership_id: int) -> datetime | None:
        with self.engine.connect() as conn:
            found: datetime | None = conn.execute(
                select(t.membership.c.last_seen_at).where(t.membership.c.id == membership_id)
            ).scalar_one()
        return found

    def lease(self, card_id: str) -> datetime:
        with self.engine.connect() as conn:
            found: datetime = conn.execute(
                select(t.card.c.lease_until).where(t.card.c.id == card_id)
            ).scalar_one()
        return found

    def event_count(self, project_id: str) -> int:
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(t.event)
                    .where(t.event.c.project_id == project_id)
                ).scalar_one()
            )

    def traces(self, membership_id: int, card_id: str, project_id: str) -> tuple[Any, ...]:
        """What a call writes in one project: presence, the lease, the events."""
        return self.seen(membership_id), self.lease(card_id), self.event_count(project_id)

    def isolate(self, membership_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == membership_id)
                .values(isolated_since=clock.now(), isolated_reason="a rewrite", isolated_by="hub")
            )

    def detach(self, membership_id: int) -> None:
        """End an attachment by hand: nothing writes `detached_at` yet (hub PR D)."""
        with self.engine.begin() as conn:
            conn.execute(
                update(t.instance_attachment)
                .where(instances.attachment_of(self.agent.credential_id, membership_id))
                .values(detached_at=clock.now(), detached_reason="detached")
            )

    def require_signing(self, project_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(t.project).where(t.project.c.id == project_id).values(signing="required")
            )


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine) -> World:
    alpha = factory.project(migrated, "alpha")
    beta = factory.project(migrated, "beta")
    owner = factory.human(migrated, "maintainer")
    for project_id in (alpha, beta):
        factory.membership(migrated, project_id, human_id=owner)
    agent = factory.agent(migrated, alpha, owner)
    in_b = factory.attach(migrated, agent, beta)
    start = clock.now()
    card_a, card_b = (
        factory.card(
            migrated,
            project_id,
            membership_id,
            status="in_progress",
            claim_holder=membership_id,
            claim_instance=agent.instance,
            claim_since=start,
            lease_until=start,
        )
        for project_id, membership_id in ((alpha, agent.membership_id), (beta, in_b))
    )
    return World(
        migrated,
        make_client(),
        agent,
        alpha,
        beta,
        agent.membership_id,
        in_b,
        card_a,
        card_b,
        start,
    )


def _refused(response: Any, code: str) -> None:
    assert response.status_code == 403, response.text
    assert response.headers["Maity-Error"] == code


# --- signing binds the credential in every project (§2.2, Q7) -------------------------------


def test_signing_required_in_a_refuses_bearer_everywhere(world: World) -> None:
    """A requires signing, B does not: a Bearer call is `signature_required` on B's routes
    and on `GET /me`, before any side effect; a signed call goes through."""
    w = world
    w.require_signing(w.alpha)
    w.later()
    before = w.traces(w.in_b, w.card_b, w.beta)
    _refused(w.call("GET", f"{B}/tasks", sign=False), "signature_required")
    _refused(w.call("GET", "/me", sign=False), "signature_required")
    _refused(w.call("GET", "/me/cross-chats", sign=False), "signature_required")
    assert w.traces(w.in_b, w.card_b, w.beta) == before
    assert w.call("GET", "/me/cross-chats").status_code == 200
    for project in (A, B):
        found = w.call("GET", f"{project}/tasks")
        assert found.status_code == 200, found.text


def test_an_isolated_attachment_still_binds_and_a_detached_one_does_not(world: World) -> None:
    """Q7: A isolates the instance and still requires signing: Bearer is refused in B too. Once
    the instance is detached from A, A's policy no longer binds it."""
    w = world
    w.require_signing(w.alpha)
    w.isolate(w.in_a)
    _refused(w.call("GET", "/me/cross-chats", sign=False), "signature_required")
    _refused(w.call("GET", f"{B}/tasks", sign=False), "signature_required")
    assert w.call("GET", f"{B}/tasks").status_code == 200
    w.detach(w.in_a)
    assert w.call("GET", f"{B}/tasks", sign=False).status_code == 200
    assert w.call("GET", "/me/cross-chats", sign=False).status_code == 200
    assert w.call("GET", "/me", sign=False).status_code == 200  # B alone: its one membership


def test_signing_required_in_the_newer_attachment_binds_until_it_is_detached(
    world: World,
) -> None:
    """B, the attachment made second, requires signing, A does not: a Bearer call is refused on
    A's routes and on `GET /me` too, since the credential is one secret in both (before hub PR
    B only the oldest attachment's policy was read, so this went through). Once B is
    detached, A's policy alone binds it and Bearer works again."""
    w = world
    w.require_signing(w.beta)
    _refused(w.call("GET", f"{A}/tasks", sign=False), "signature_required")
    _refused(w.call("GET", "/me", sign=False), "signature_required")
    _refused(w.call("GET", f"{B}/tasks", sign=False), "signature_required")
    assert w.call("GET", f"{A}/tasks").status_code == 200  # signed, it goes through
    w.detach(w.in_b)
    assert w.call("GET", f"{A}/tasks", sign=False).status_code == 200
    me = w.call("GET", "/me", sign=False)
    assert me.status_code == 200, me.text
    assert [p["id"] for p in me.json()["projects"]] == [w.alpha]


# --- a project's routes act in that project's attachment only (§2.2, §2.4, §6.2) -----------


def test_a_project_the_instance_is_not_attached_to_is_not_found(world: World) -> None:
    """Attached to A only (B detached, its membership still there): B's routes answer
    `not_found`, a read and a write alike, and nothing is written in B: no presence, no lease,
    no event."""
    w = world
    w.detach(w.in_b)
    w.later()
    before = w.traces(w.in_b, w.card_b, w.beta)
    for response in (w.call("GET", f"{B}/tasks"), w.call("POST", f"{B}/events", body=NOTICE)):
        assert response.status_code == 404, response.text
        assert response.headers["Maity-Error"] == "not_found"
    assert w.traces(w.in_b, w.card_b, w.beta) == before
    assert w.call("GET", f"{A}/tasks").status_code == 200  # its own project answers


def test_a_project_without_a_membership_is_not_found(world: World) -> None:
    w = world
    factory.project(w.engine, "gamma")
    found = w.call("GET", "/projects/maintainer/gamma/tasks")
    assert found.status_code == 404, found.text


def test_isolated_in_a_refuses_a_before_any_side_effect_and_b_works_on(world: World) -> None:
    """Isolated in A, attached to both: A's routes answer `isolated` and leave A as it was
    (presence, lease, events); B's routes answer and renew presence and the lease in B
    alone."""
    w = world
    w.isolate(w.in_a)
    w.later()
    before = w.traces(w.in_a, w.card_a, w.alpha)
    for response in (w.call("GET", f"{A}/tasks"), w.call("POST", f"{A}/events", body=NOTICE)):
        assert response.status_code == 403, response.text
        assert response.json()["error"]["details"]["reason"] == "isolated"
    assert w.traces(w.in_a, w.card_a, w.alpha) == before
    assert w.call("GET", f"{B}/tasks").status_code == 200
    said = w.call("POST", f"{B}/events", body=NOTICE)
    assert said.status_code == 201, said.text
    moment = clock.now()
    assert w.seen(w.in_b) == moment
    assert w.lease(w.card_b) == moment + timedelta(hours=2)
    assert w.traces(w.in_a, w.card_a, w.alpha) == before


def test_not_found_comes_before_isolated(world: World) -> None:
    """Isolated in A and detached from it: A's routes answer `not_found`, so an isolation is
    told to no one outside the project."""
    w = world
    w.isolate(w.in_a)
    w.detach(w.in_a)
    found = w.call("GET", f"{A}/tasks")
    assert found.status_code == 404, found.text


def test_a_project_route_renews_only_its_own_membership(world: World) -> None:
    w = world
    w.later()
    assert w.call("GET", f"{B}/tasks").status_code == 200
    moment = clock.now()
    assert (w.seen(w.in_a), w.seen(w.in_b)) == (None, moment)
    assert (w.lease(w.card_a), w.lease(w.card_b)) == (w.start, moment + timedelta(hours=2))


# --- presence and leases outside a project (§2.4, Q10) --------------------------------------


def test_a_call_outside_any_project_renews_every_attachment(world: World) -> None:
    w = world
    w.later()
    assert w.call("GET", "/me/cross-chats").status_code == 200
    moment = clock.now()
    assert (w.seen(w.in_a), w.seen(w.in_b)) == (moment, moment)
    assert (w.lease(w.card_a), w.lease(w.card_b)) == (moment + timedelta(hours=2),) * 2


def test_a_call_outside_any_project_skips_an_isolated_attachment(world: World) -> None:
    w = world
    w.isolate(w.in_a)
    w.later()
    assert w.call("GET", "/me/cross-chats").status_code == 200
    moment = clock.now()
    assert (w.seen(w.in_a), w.seen(w.in_b)) == (None, moment)
    assert (w.lease(w.card_a), w.lease(w.card_b)) == (w.start, moment + timedelta(hours=2))


def test_isolated_everywhere_a_call_outside_a_project_is_refused_without_a_trace(
    world: World,
) -> None:
    """Every attachment isolated: a call outside a project is `isolated` and writes presence and
    a lease nowhere."""
    w = world
    w.isolate(w.in_a)
    w.isolate(w.in_b)
    w.later()
    refused = w.call("GET", "/me/cross-chats")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "isolated"
    assert (w.seen(w.in_a), w.seen(w.in_b)) == (None, None)
    assert (w.lease(w.card_a), w.lease(w.card_b)) == (w.start, w.start)


def test_the_long_poll_outside_renews_no_lease(world: World) -> None:
    """The long-poll is presence, not work, as before (§2.4): checked through the settle of a
    call outside a project with `renew_leases` off."""
    from maity_hub.auth.caller import RequestFacts, authenticate, settle_project_less
    from maity_hub.net import Origin

    w = world
    w.later()
    facts = RequestFacts(
        method="GET",
        raw_path=b"/api/v1/me/cross-chats",
        path="/api/v1/me/cross-chats",
        raw_query=b"",
        headers={"authorization": f"Bearer {w.agent.value}"},
        cookies={},
        body=b"",
        origin=Origin("203.0.113.7", "https"),
        allow_plain_http=False,
    )
    with w.engine.begin() as conn:
        caller = settle_project_less(conn, authenticate(conn, facts), facts, renew_leases=False)
    assert (caller.membership_id, caller.project_id) == (None, None)  # several: none chosen
    moment = clock.now()
    assert (w.seen(w.in_a), w.seen(w.in_b)) == (moment, moment)
    assert (w.lease(w.card_a), w.lease(w.card_b)) == (w.start, w.start)


def test_a_single_attachment_acts_in_its_one_membership(world: World) -> None:
    """The instance in one project only, as every instance was before: a call outside a
    project acts in that membership, as `GET /me` shows."""
    w = world
    w.detach(w.in_b)
    me = w.call("GET", "/me")
    assert me.status_code == 200, me.text
    assert [p["id"] for p in me.json()["projects"]] == [w.alpha]


# --- the read limit (§1.7): an isolated call leaves no count, a probe still counts ---------


def _reads(w: World) -> int:
    """The reads counted against the instance's credential in this process (`read_limits`)."""
    found = read_limits.COUNTER._counts.get(w.agent.credential_id)
    return 0 if found is None else found.current


def test_an_isolated_read_in_a_is_not_counted(world: World) -> None:
    """Isolated in A: a read of A's routes is `isolated` and leaves no count, as an isolated
    read always did (§6.2 "Those two calls leave no trace")."""
    w = world
    w.isolate(w.in_a)
    refused = w.call("GET", f"{A}/tasks")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "isolated"
    assert _reads(w) == 0


def test_isolated_everywhere_a_read_outside_a_project_is_not_counted(world: World) -> None:
    """Every attachment isolated: a read outside a project is `isolated` with no count; the
    calls it may still make (`GET /me`) count, as before."""
    w = world
    w.isolate(w.in_a)
    w.isolate(w.in_b)
    refused = w.call("GET", "/me/cross-chats")
    assert refused.status_code == 403, refused.text
    assert _reads(w) == 0
    me = w.call("GET", "/me")
    assert me.status_code == 200, me.text
    assert _reads(w) == 1


def test_a_read_of_a_project_the_instance_is_not_attached_to_counts(world: World) -> None:
    """B detached, and a project with no membership at all: each read is `not_found` and is
    counted, so probing other projects stays limited."""
    w = world
    w.detach(w.in_b)
    factory.project(w.engine, "gamma")
    for path in (f"{B}/tasks", "/projects/maintainer/gamma/tasks", "/projects/nobody/x/tasks"):
        found = w.call("GET", path)
        assert found.status_code == 404, found.text
    assert _reads(w) == 3


def test_a_read_counts_once(world: World) -> None:
    w = world
    assert w.call("GET", f"{A}/tasks").status_code == 200
    assert _reads(w) == 1
    assert w.call("GET", "/me/cross-chats").status_code == 200
    assert _reads(w) == 2


# --- routes outside a project name their project (§5.1, §5.3, §6.12, §6.23, §6.17) ---------


def _invalid(response: Any, field: str, reason: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"][field] == reason


def _attachment(w: World, membership_id: int) -> Any:
    a = t.instance_attachment
    with w.engine.connect() as conn:
        return conn.execute(
            select(a).where(instances.attachment_of(w.agent.credential_id, membership_id))
        ).one()


def _limit(w: World, membership_id: int) -> datetime | None:
    with w.engine.connect() as conn:
        found: datetime | None = conn.execute(
            select(t.membership.c.limit_until).where(t.membership.c.id == membership_id)
        ).scalar_one()
    return found


def test_get_me_lists_every_attachment_with_its_flags(world: World) -> None:
    """Each live attachment one entry, in the order attached, with that membership's
    `trust`, `role`, `isolated`, and the instance's `paused` and `dormant` there; no
    single-project `membership` beside them."""
    w = world
    w.isolate(w.in_b)
    with w.engine.begin() as conn:
        conn.execute(
            update(t.instance_attachment)
            .where(instances.attachment_of(w.agent.credential_id, w.in_a))
            .values(dormant_since=clock.now(), dormant_by=w.agent.agent_id)
        )
    me = w.call("GET", "/me")
    assert me.status_code == 200, me.text
    body = me.json()
    a, b = body["projects"]
    assert (a["id"], b["id"]) == (w.alpha, w.beta)
    assert (a["full_name"], b["full_name"]) == ("maintainer/alpha", "maintainer/beta")
    assert {a["trust"], b["trust"]} <= {"member", "admin", "owner", "guest"}
    assert a["isolated"] is None and b["isolated"]["reason"] == "a rewrite"
    assert a["dormant"]["by"] == w.agent.agent_id and b["dormant"] is None
    assert a["paused"] is None and b["paused"] is None
    assert body["membership"] is None
    assert body["member"]["owner_id"] == w.agent.owner_id
    assert body["member"]["instance"] == w.agent.instance


def test_get_me_of_a_single_attachment_reads_as_before(world: World) -> None:
    """One live attachment: the entry keeps every field it had, and `membership.isolated` stays
    beside it, so an older client reads it as before."""
    w = world
    w.detach(w.in_b)
    body = w.call("GET", "/me").json()
    [entry] = body["projects"]
    assert {"id", "slug", "full_name", "name", "state", "trust", "role", "logo"} <= set(entry)
    assert entry["id"] == w.alpha and entry["full_name"] == "maintainer/alpha"
    assert body["membership"] == {"isolated": None}


def test_patch_me_paused_applies_per_project(world: World) -> None:
    """Without `project` every attachment that is not isolated, answered with `projects`;
    with it that one, answered with its member view; an isolated project named is `isolated`,
    one the instance is not attached to `invalid` (`not_a_member`)."""
    w = world
    paused = w.call(
        "PATCH", "/me", body={"paused": {"reason": "a break"}, "project": "maintainer/beta"}
    )
    assert paused.status_code == 200, paused.text
    assert "projects" not in paused.json()
    assert _attachment(w, w.in_b).paused_since is not None
    assert _attachment(w, w.in_a).paused_since is None
    everywhere = w.call("PATCH", "/me", body={"paused": None})
    assert everywhere.status_code == 200, everywhere.text
    assert len(everywhere.json()["projects"]) == 2
    assert _attachment(w, w.in_b).paused_since is None
    w.isolate(w.in_a)
    again = w.call("PATCH", "/me", body={"paused": {"reason": "again"}})
    assert again.status_code == 200, again.text
    assert len(again.json()["projects"]) == 1  # A is skipped
    assert _attachment(w, w.in_a).paused_since is None
    assert _attachment(w, w.in_b).paused_since is not None
    named = w.call("PATCH", "/me", body={"paused": None, "project": "maintainer/alpha"})
    _refused(named, "forbidden")
    assert named.json()["error"]["details"]["reason"] == "isolated"
    factory.project(w.engine, "gamma")
    for project in ("maintainer/gamma", "nobody/nothing", "prj-000000000000", w.beta):
        _invalid(
            w.call("PATCH", "/me", body={"paused": None, "project": project}),
            "project",
            "not_a_member",
        )


def test_post_me_limit_applies_per_project(world: World) -> None:
    w = world
    until = clock.rfc3339(clock.now() + timedelta(hours=1))
    one = w.call("POST", "/me/limit", body={"until": until, "project": "maintainer/alpha"})
    assert one.status_code == 200, one.text
    assert _limit(w, w.in_a) is not None and _limit(w, w.in_b) is None
    both = w.call("POST", "/me/limit", body={"until": until})
    assert both.status_code == 200, both.text
    assert len(both.json()["projects"]) == 2
    assert _limit(w, w.in_b) is not None
    w.isolate(w.in_b)
    named = w.call("POST", "/me/limit", body={"until": None, "project": "maintainer/beta"})
    assert named.json()["error"]["details"]["reason"] == "isolated"
    _invalid(
        w.call("POST", "/me/limit", body={"until": None, "project": "nobody/nothing"}),
        "project",
        "not_a_member",
    )


@pytest.mark.parametrize("change", ["isolate", "detach"])
@pytest.mark.parametrize(
    "path, body",
    [
        ("/me", {"paused": {"reason": "a break"}, "project": "maintainer/alpha"}),
        ("/me/limit", {"until": None, "project": "maintainer/alpha"}),
    ],
)
def test_a_replayed_single_project_write_rechecks_its_attachment(
    world: World, change: str, path: str, body: dict[str, Any]
) -> None:
    """The one-project answer of `PATCH /me` or `POST /me/limit` replays (§1.5) only while
    the attachment in that project is live and not isolated: B keeps the credential
    authenticated, but A's member view and briefing are not read through it."""
    w = world
    method = "PATCH" if path == "/me" else "POST"
    key = f"key-{secrets.token_hex(12)}"
    first = w.call(method, path, body=body, key=key)
    assert first.status_code == 200, first.text
    again = w.call(method, path, body=body, key=key)
    assert again.status_code == 200, again.text
    assert again.headers["Idempotent-Replayed"] == "true"
    getattr(w, change)(w.in_a)
    replayed = w.call(method, path, body=body, key=key)
    assert replayed.status_code == 404, replayed.text
    assert "briefing" not in replayed.text
    assert w.call("GET", "/me").status_code == 200  # B still authenticates


@pytest.mark.parametrize("change", ["isolate", "detach"])
@pytest.mark.parametrize(
    "path, body",
    [("/me", {"paused": {"reason": "a break"}}), ("/me/limit", {"until": None})],
)
def test_a_replayed_write_in_every_project_reads_only_the_attachments_left(
    world: World, change: str, path: str, body: dict[str, Any]
) -> None:
    """The `projects` answer of `PATCH /me` or `POST /me/limit` without `project` replays
    (§1.5) by the credential, as its attachments are then: a project detached or isolated
    since is left out, the other kept; the stored id answers no other caller."""
    w = world
    with w.engine.begin() as conn:
        for membership_id, area in ((w.in_a, "alpha-area"), (w.in_b, "beta-area")):
            conn.execute(
                update(t.membership).where(t.membership.c.id == membership_id).values(areas=[area])
            )
    method = "PATCH" if path == "/me" else "POST"
    key = f"key-{secrets.token_hex(12)}"
    first = w.call(method, path, body=body, key=key)
    assert first.status_code == 200, first.text
    assert [p["areas"] for p in first.json()["projects"]] == [["alpha-area"], ["beta-area"]]
    getattr(w, change)(w.in_a)
    replayed = w.call(method, path, body=body, key=key)
    assert replayed.status_code == 200, replayed.text
    assert replayed.headers["Idempotent-Replayed"] == "true"
    assert [p["areas"] for p in replayed.json()["projects"]] == [["beta-area"]]
    assert "alpha-area" not in replayed.text
    check = idempotency.LOADERS["member_set"].may_see
    owner = Caller(kind="human", via="cookie", human_id=w.agent.owner_id)
    other = factory.agent(w.engine, w.beta, w.agent.owner_id, instance="oth2")
    stranger = Caller(
        kind="agent",
        via="bearer",
        agent_id=other.agent_id,
        owner_id=other.owner_id,
        credential_id=other.credential_id,
    )
    with w.engine.connect() as conn:
        assert not check(conn, w.agent.credential_id, owner)
        assert not check(conn, w.agent.credential_id, stranger)


@pytest.mark.parametrize("change", ["isolate", "detach"])
@pytest.mark.parametrize(
    "path, body",
    [("/me", {"paused": {"reason": "a break"}}), ("/me/limit", {"until": None})],
)
def test_a_replayed_write_in_every_project_refuses_as_the_request_once_none_is_left(
    world: World, change: str, path: str, body: dict[str, Any]
) -> None:
    """With no live attachment that is not isolated left, the replay answers as the request
    it stands for would without the key (§1.5): the same status, error and details, never
    `projects: []`. B is isolated in both cases; A goes the way `change` names.

    Over HTTP authentication refuses such a credential before the replay is read; the
    loader refuses too, for a change that lands between authentication and the replay's
    own transaction."""
    w = world
    method = "PATCH" if path == "/me" else "POST"
    key = f"key-{secrets.token_hex(12)}"
    first = w.call(method, path, body=body, key=key)
    assert first.status_code == 200, first.text
    w.isolate(w.in_b)
    getattr(w, change)(w.in_a)
    fresh = w.call(method, path, body=body)
    replayed = w.call(method, path, body=body, key=key)
    assert fresh.status_code >= 400, fresh.text
    assert (replayed.status_code, replayed.json()) == (fresh.status_code, fresh.json())
    assert "Idempotent-Replayed" not in replayed.headers
    load = idempotency.LOADERS["member_set"].load
    with w.engine.connect() as conn, pytest.raises(ApiError) as refused:
        load(conn, w.agent.credential_id, _REQUEST)
    error = fresh.json()["error"]
    assert refused.value.status == fresh.status_code
    assert refused.value.code == error["code"]
    assert refused.value.details == error.get("details", {})


# A replay's loader is called here without a route: the `member_*` loaders read nothing
# from the request, so an empty one stands in.
_REQUEST = Request({"type": "http", "headers": []})


def _agent_caller(w: World) -> Caller:
    return Caller(
        kind="agent",
        via="bearer",
        agent_id=w.agent.agent_id,
        owner_id=w.agent.owner_id,
        credential_id=w.agent.credential_id,
    )


def test_a_replayed_self_write_refuses_a_credential_revoked_since_it_authenticated(
    world: World,
) -> None:
    """A revocation that lands between authentication and the replay's own transaction
    keeps the attachment rows, so the replay asks the credential itself: `unauthenticated`,
    as the write's `attached.recheck` answers, for the answer in one project (`member_self`,
    not the `not_found` of a lost attachment) and in every project (`member_set`). Over HTTP
    authentication refuses a revoked credential first, so the replay's read is called here."""
    w = world
    single = w.call("PATCH", "/me", body={"paused": None, "project": "maintainer/alpha"})
    assert single.status_code == 200, single.text
    caller = _agent_caller(w)
    member_self = idempotency.LOADERS["member_self"]
    member_set = idempotency.LOADERS["member_set"]
    with w.engine.connect() as conn:  # live: both replay as before
        assert member_self.may_see(conn, str(w.in_a), caller)
        assert member_set.may_see(conn, w.agent.credential_id, caller)
        member_set.load(conn, w.agent.credential_id, _REQUEST)
    with w.engine.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == w.agent.credential_id)
            .values(revoked_at=clock.now())
        )
    with w.engine.connect() as conn:
        with pytest.raises(ApiError) as one:
            member_self.may_see(conn, str(w.in_a), caller)
        with pytest.raises(ApiError) as every:
            member_set.load(conn, w.agent.credential_id, _REQUEST)
    for refused in (one.value, every.value):
        assert (refused.status, refused.code) == (401, "unauthenticated")


def test_a_replayed_write_in_every_project_with_no_live_attachment_is_unauthenticated(
    world: World,
) -> None:
    """Detached from every project since authentication, the `member_set` replay refuses
    `unauthenticated`, as `attached.every` does for the request, never `projects: []`."""
    w = world
    w.detach(w.in_a)
    w.detach(w.in_b)
    with w.engine.connect() as conn, pytest.raises(ApiError) as refused:
        idempotency.LOADERS["member_set"].load(conn, w.agent.credential_id, _REQUEST)
    assert (refused.value.status, refused.value.code) == (401, "unauthenticated")


def test_a_replayed_self_write_locks_its_projects_before_it_asks_the_credential(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revocation locks the projects it writes in, in the order of their ids, before it
    writes the credential row. Each replay takes the same project locks before it reads
    `revoked_at` and holds them through the answer, as the request holds them through its
    write. On PostgreSQL and MariaDB under READ COMMITTED a revocation can then neither land
    between the check and the member view nor wait on the replay in a cycle (d4kb on #2105).
    `member_self` locks its membership's project, `member_set` those of every live
    attachment."""
    w = world
    caller = _agent_caller(w)
    real_project, real_live = events.lock_project, attached.still_live
    taken: list[str] = []

    def project(conn: Any, locked: str) -> Any:
        taken.append(locked)
        return real_project(conn, locked)

    def live(conn: Any, credential_id: str) -> None:
        taken.append("live")
        real_live(conn, credential_id)

    monkeypatch.setattr(events, "lock_project", project)
    monkeypatch.setattr(attached, "still_live", live)
    with events.transaction(w.engine) as conn:
        assert idempotency.LOADERS["member_self"].may_see(conn, str(w.in_a), caller)
    assert taken == [w.alpha, "live"]
    taken.clear()
    with events.transaction(w.engine) as conn:
        idempotency.LOADERS["member_set"].load(conn, w.agent.credential_id, _REQUEST)
    assert taken == [*sorted([w.alpha, w.beta]), "live"]


def test_the_keep_the_why_ack_names_its_project_among_several(world: World) -> None:
    w = world
    with w.engine.begin() as conn:
        conn.execute(update(t.project).values(keep_the_why=True))
    _invalid(w.call("POST", "/me/keep-the-why/ack"), "project", "required")
    acked = w.call("POST", "/me/keep-the-why/ack", body={"project": "maintainer/beta"})
    assert acked.status_code == 200, acked.text
    assert _attachment(w, w.in_b).ktw_acknowledged_at is not None
    assert _attachment(w, w.in_a).ktw_acknowledged_at is None
    w.detach(w.in_b)  # one attachment: `project` is optional, as before
    alone = w.call("POST", "/me/keep-the-why/ack")
    assert alone.status_code == 200, alone.text
    assert _attachment(w, w.in_a).ktw_acknowledged_at is not None


def test_no_route_outside_a_project_answers_500_for_an_instance_in_two(world: World) -> None:
    """Every route converted in hub PR B step 3, once, for an instance attached to A and B:
    an answer or a clean refusal, never a server error."""
    w = world
    other = factory.agent(w.engine, w.beta, w.agent.owner_id, instance="oth1")
    calls = [
        ("GET", "/me", None),
        ("GET", "/projects", None),
        ("GET", "/bootstrap", None),
        ("GET", "/bootstrap?project=maintainer/beta", None),
        # Another member's picture, so `avatars.may_read` reads the attachments (its own
        # would be answered before them).
        ("GET", f"/avatars/{other.agent_id}", None),
        ("PATCH", "/me", {"paused": None}),
        ("PATCH", "/me", {"dormant": False}),
        ("PATCH", "/me", {"avatar_motif": None}),
        ("POST", "/me/limit", {"until": None}),
        ("POST", "/me/keep-the-why/ack", None),
        ("POST", "/me/resume", {"client": "test"}),
        ("POST", "/me/soul/proposals", {"markdown": "me", "reason": "why"}),
        # With its `reason`, so the call gets past validation to the reader of the target.
        (
            "POST",
            "/reports",
            {"target": {"type": "project", "id": "maintainer/beta"}, "reason": "spam"},
        ),
        (
            "POST",
            "/reports",
            {"target": {"type": "profile", "id": other.agent_id}, "reason": "spam"},
        ),
        ("GET", "/me/cross-chats", None),
    ]
    for method, path, body in calls:
        answered = w.call(method, path, body=body, sign=method != "GET" or "?" not in path)
        assert answered.status_code < 500, (method, path, answered.text)
    for path in (f"/avatars/{other.agent_id}", "/bootstrap?project=maintainer/beta"):
        assert w.call("GET", path, sign="?" not in path).status_code == 200, path
    _invalid(
        w.call("POST", "/me/soul/proposals", body={"markdown": "me", "reason": "why"}),
        "project",
        "required",
    )
    listed = w.call("GET", "/projects").json()["items"]
    assert sorted(p["id"] for p in listed) == sorted([w.alpha, w.beta])


def test_resume_of_an_instance_in_several_projects_is_refused_plainly(world: World) -> None:
    """Pinned until the resume with one entry per project is built (§5.2, "Several projects"):
    the contract's `409 conflict` with `client_too_old` and no release to name, its message
    saying that no update helps yet. No session opens and no `session_started` is written.
    The PR that builds it (and `accepts`, which is not taken yet) changes this test on
    purpose."""
    w = world
    before = (w.event_count(w.alpha), w.event_count(w.beta))
    resumed = w.call("POST", "/me/resume", body={"client": "test"})
    assert resumed.status_code == 409, resumed.text
    assert resumed.json()["error"] == {
        "code": "conflict",
        "message": "resume is not available yet for an instance attached to several "
        "projects; a later hub version brings it",
        "details": {"reason": "client_too_old", "min_cli": None},
    }
    assert (w.event_count(w.alpha), w.event_count(w.beta)) == before
    with w.engine.connect() as conn:
        opened = conn.execute(
            select(func.count())
            .select_from(t.agent_session)
            .where(
                t.agent_session.c.credential_id == w.agent.credential_id,
                t.agent_session.c.started_at >= w.start,
            )
        ).scalar_one()
    assert opened == 0


def test_an_agents_project_is_named_by_its_full_name_only(world: World) -> None:
    """`project` is `<owner>/<slug>` (§5.3, "Per project"): a project id, even of a project
    the instance is attached to, names no project for it, `invalid` (`not_a_member`), as does
    any other form, on every route that takes it."""
    w = world
    with w.engine.begin() as conn:
        conn.execute(update(t.project).values(keep_the_why=True))
    until = clock.rfc3339(clock.now() + timedelta(hours=1))
    for project in (w.beta, "beta", "maintainer/beta/x", "/beta", "", "maintainer/beta\n"):
        for method, path, body in (
            ("PATCH", "/me", {"paused": None, "project": project}),
            ("POST", "/me/limit", {"until": until, "project": project}),
            ("POST", "/me/keep-the-why/ack", {"project": project}),
            ("POST", "/me/soul/proposals", {"markdown": "me", "reason": "why", "project": project}),
        ):
            _invalid(w.call(method, path, body=body), "project", "not_a_member")
    assert _limit(w, w.in_b) is None
    assert _attachment(w, w.in_b).ktw_acknowledged_at is None


def test_the_avatar_motif_takes_no_project(world: World) -> None:
    """The motif is the profile's (§6.10, §6.17): with `project` and no `paused` the write is
    `invalid` (`project: not_allowed`) and the motif stays; beside `paused`, `project` names
    the pause's project and the motif is set."""
    from maity_hub import motifs

    w = world
    motif = motifs.current().motifs[0].name

    def chosen() -> Any:
        with w.engine.connect() as conn:
            return conn.execute(
                select(t.agent_profile.c.avatar_motif).where(
                    t.agent_profile.c.id == w.agent.agent_id
                )
            ).scalar_one()

    before = chosen()
    refused = w.call("PATCH", "/me", body={"avatar_motif": motif, "project": "maintainer/beta"})
    _invalid(refused, "project", "not_allowed")
    assert chosen() == before
    both = w.call(
        "PATCH",
        "/me",
        body={"avatar_motif": motif, "paused": {"reason": "a break"}, "project": "maintainer/beta"},
    )
    assert both.status_code == 200, both.text
    assert chosen() == motif
    assert _attachment(w, w.in_b).paused_since is not None


def test_get_projects_shows_an_isolated_attachment_reduced(world: World) -> None:
    w = world
    w.isolate(w.in_b)
    listed = {p["id"]: p for p in w.call("GET", "/projects").json()["items"]}
    assert listed[w.beta] == {
        "id": w.beta,
        "slug": "beta",
        "full_name": "maintainer/beta",
        "name": "Project beta",
        "state": "build",
        "isolated": True,
    }
    assert listed[w.alpha]["isolated"] is False and "settings" in listed[w.alpha]


# --- cross-project chats: the author's attachment in the project it posts from (§9.5, Q4) ---


@pytest.fixture
def chat(make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A cross chat of the owner with an agent attached to A and B and one in C only; the
    mention charges recorded as (membership, count)."""
    from maity_hub import mentions
    from tests import flow

    owner = flow.human(make_client, migrated)
    ids = {slug: flow.project(owner, slug)["id"] for slug in ("alpha", "beta", "gamma")}
    author = flow.agent(make_client, owner, "alpha")
    in_b = factory.attach(migrated, author, ids["beta"])
    other = flow.agent(make_client, owner, "gamma")
    created = owner.post("/me/cross-chats", {"title": "x", "participants": [author.id, other.id]})
    assert created.status_code == 201, created.text
    body = created.json()
    handle = next(p["handle"] for p in body["participants"] if p["member_id"] == other.id)
    charged: list[tuple[int, int]] = []
    monkeypatch.setattr(mentions, "charge", lambda _c, m, n: charged.append((m, n)))
    return {
        "owner": owner,
        "author": author,
        "in_b": in_b,
        "path": f"/me/cross-chats/{body['id']}/messages",
        "mention": f"@{handle} look",
        "charged": charged,
        "make": make_client,
        "engine": migrated,
    }


def test_a_cross_chat_post_is_charged_on_the_attachment_it_names(chat: Any) -> None:
    author = chat["author"]
    posted = author.post(chat["path"], {"body": chat["mention"], "project": "maintainer/beta"})
    assert posted.status_code == 201, posted.text
    assert chat["charged"] == [(chat["in_b"], 1)]
    # Two attachments and a mention: no implicit choice.
    _invalid(author.post(chat["path"], {"body": chat["mention"]}), "project", "required")
    # No mention, nothing charged: no project needed.
    assert author.post(chat["path"], {"body": "plain"}).status_code == 201
    assert chat["charged"] == [(chat["in_b"], 1)]


def test_a_cross_chat_author_not_attached_to_the_project_is_refused(chat: Any) -> None:
    """Attached to A only: B's attachment is never used, nor A's in its place."""
    from tests import flow

    lone = flow.agent(chat["make"], chat["owner"], "alpha")
    owner = chat["owner"]
    chat_id = chat["path"].split("/")[3]
    added = owner.post(f"/me/cross-chats/{chat_id}/participants", {"member_id": lone.id})
    assert added.status_code == 200, added.text
    refused = lone.post(chat["path"], {"body": chat["mention"], "project": "maintainer/beta"})
    _invalid(refused, "project", "not_a_member")
    assert chat["charged"] == []


def test_a_cross_chat_post_names_its_project_by_full_name_only(chat: Any) -> None:
    """A project id, of a project the author is attached to, names none (§9.5, §5.3)."""
    with chat["engine"].connect() as conn:
        beta_id = conn.execute(
            select(t.membership.c.project_id).where(t.membership.c.id == chat["in_b"])
        ).scalar_one()
    refused = chat["author"].post(chat["path"], {"body": chat["mention"], "project": beta_id})
    _invalid(refused, "project", "not_a_member")
    assert chat["charged"] == []


# --- a revocation speaks for each attachment, never the oldest (§6.17, §15.3) --------------


def test_a_runner_revocation_due_is_told_in_every_attached_project(world: World) -> None:
    from maity_hub import events, runner_revoke

    w = world
    with events.transaction(w.engine) as conn:
        runner_revoke.revoke_agent(conn, w.agent.credential_id, None)
    with w.engine.connect() as conn:
        told = conn.execute(
            select(t.event.c.project_id)
            .where(t.event.c.kind == "credential_revoked")
            .order_by(t.event.c.project_id)
        ).scalars()
        assert list(told) == sorted([w.alpha, w.beta])


@pytest.mark.parametrize("placed", [["alpha"], ["alpha", "beta"]])
def test_a_runner_stop_over_one_placement_is_told_in_every_attached_project(
    world: World, placed: list[str]
) -> None:
    """The owner's stop names the projects of the placements it closes (`apply`,
    `_on_the_machine`, `_due_now`); the instance is attached to A and B, so the revocation is
    told in both, whichever the placements were in (§6.17, §15.3)."""
    from maity_hub import events, runner_revoke

    w = world
    ids = {"alpha": w.alpha, "beta": w.beta}
    with events.transaction(w.engine) as conn:
        runner_revoke.revoke_agent(conn, w.agent.credential_id, None, [ids[p] for p in placed])
    with w.engine.connect() as conn:
        told = conn.execute(
            select(t.event.c.project_id).where(t.event.c.kind == "credential_revoked")
        ).scalars()
        assert sorted(told) == sorted([w.alpha, w.beta])


def test_a_replayed_credential_revocation_reads_the_attachment_it_named(world: World) -> None:
    """The stored key names the membership; a key without one, from before, is read only
    while the credential has a single live attachment."""
    from maity_hub.errors import ApiError
    from maity_hub.routes.members import credential_key, load_credential

    w = world
    with w.engine.connect() as conn:
        shown = load_credential(conn, credential_key(w.agent.credential_id, w.in_b))
        assert shown["id"] == w.agent.credential_id
        with pytest.raises(ApiError) as refused:
            load_credential(conn, w.agent.credential_id)
        assert refused.value.code == "not_found"
    w.detach(w.in_b)
    with w.engine.connect() as conn:
        assert load_credential(conn, w.agent.credential_id)["id"] == w.agent.credential_id


# --- a revocation locks its projects in the order of their ids, first (persistence.md) ------


@pytest.mark.parametrize("path", ["revoke", "leak", "runner"])
def test_a_revocation_locks_every_project_in_order_before_any_write(
    world: World, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Attached to A and B, each with a claim: whichever path revokes, both projects are
    locked first, in the order of their ids, while the credential is still live; every later
    lock (`emit`'s) is one of them again."""
    from maity_hub import events, runner_revoke
    from maity_hub.auth import credentials, leaks, revocation

    w = world
    real = events.lock_project
    taken: list[tuple[str, bool]] = []

    def recording(conn: Any, project_id: str) -> Any:
        revoked = conn.execute(
            select(t.credential.c.revoked_at).where(t.credential.c.id == w.agent.credential_id)
        ).scalar_one()
        taken.append((project_id, revoked is not None))
        return real(conn, project_id)

    monkeypatch.setattr(events, "lock_project", recording)
    with events.transaction(w.engine) as conn:
        if path == "revoke":
            assert revocation.revoke(conn, w.agent.credential_id, "revoked", None)
        elif path == "leak":
            presented = credentials.parse(w.agent.value)
            assert presented is not None
            assert leaks.revoke_leaked(conn, [presented]) == [w.agent.credential_id]
        else:
            runner_revoke.revoke_agent(conn, w.agent.credential_id, None)
    ordered = sorted([w.alpha, w.beta])
    assert taken[:2] == [(ordered[0], False), (ordered[1], False)]
    assert {project_id for project_id, _ in taken} == set(ordered)
    with w.engine.connect() as conn:
        stalled = conn.execute(
            select(t.event.c.project_id).where(t.event.c.kind == "holder_stalled")
        ).scalars()
        assert sorted(stalled) == ordered  # told in each, as before


@pytest.mark.parametrize(
    "path, body",
    [
        ("/me", {"paused": {"reason": "a break"}}),
        ("/me/limit", {"until": "later"}),
    ],
)
def test_a_write_in_every_attachment_locks_its_projects_in_order_first(
    world: World, monkeypatch: pytest.MonkeyPatch, path: str, body: dict[str, Any]
) -> None:
    """`PATCH /me` and `POST /me/limit` without `project` write in each attachment, in the
    order attached; they lock every project first, in the order of the ids, as a revocation
    does, so the two never wait on each other in a cycle. The attachment of the higher id is
    made the older one here, so the order attached and the order of the ids differ."""
    from maity_hub import events

    w = world
    ordered = sorted([w.alpha, w.beta])
    first = w.in_a if ordered[1] == w.alpha else w.in_b
    with w.engine.begin() as conn:
        conn.execute(
            update(t.instance_attachment)
            .where(instances.attachment_of(w.agent.credential_id, first))
            .values(attached_at=w.start - timedelta(days=1))
        )
    if body.get("until") == "later":
        body = {"until": clock.rfc3339(clock.now() + timedelta(hours=1))}
    real = events.lock_project
    taken: list[tuple[str, bool]] = []

    def written(conn: Any) -> bool:
        """Whether the write has reached either attachment yet, read in its own transaction."""
        if path == "/me":
            found = conn.execute(
                select(func.count())
                .select_from(t.instance_attachment)
                .where(
                    t.instance_attachment.c.credential_id == w.agent.credential_id,
                    t.instance_attachment.c.paused_since.is_not(None),
                )
            ).scalar_one()
        else:
            found = conn.execute(
                select(func.count())
                .select_from(t.membership)
                .where(
                    t.membership.c.id.in_([w.in_a, w.in_b]),
                    t.membership.c.limit_until.is_not(None),
                )
            ).scalar_one()
        return bool(found)

    def recording(conn: Any, project_id: str) -> Any:
        taken.append((project_id, written(conn)))
        return real(conn, project_id)

    monkeypatch.setattr(events, "lock_project", recording)
    method = "PATCH" if path == "/me" else "POST"
    done = w.call(method, path, body=body)
    assert done.status_code == 200, done.text
    assert len(done.json()["projects"]) == 2
    assert taken[:2] == [(ordered[0], False), (ordered[1], False)]


@pytest.mark.parametrize("named", [True, False])
@pytest.mark.parametrize(
    "path,body",
    [
        ("/me", {"paused": {"reason": "a break"}}),
        ("/me/limit", {"until": "later"}),
    ],
)
def test_an_isolation_before_the_locks_is_not_written_past(
    world: World, monkeypatch: pytest.MonkeyPatch, path: str, body: dict[str, Any], named: bool
) -> None:
    """`PATCH /me` and `POST /me/limit` choose their attachments, then lock their projects;
    an isolation of A that commits in between (it takes A's lock too) is read under the lock:
    with `project` naming A the write is refused as isolated, without it A is left out and B
    alone is written. Nothing is written in A either way (d4kb on #2105)."""
    from maity_hub import events

    w = world
    if body.get("until") == "later":
        body = {"until": clock.rfc3339(clock.now() + timedelta(hours=1))}
    if named:
        with w.engine.connect() as conn:
            body = {**body, "project": namespace.name_of(conn, w.alpha)}
    real = events.lock_projects

    def isolating_first(conn: Any, project_ids: Any) -> None:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == w.in_a)
            .values(isolated_since=clock.now(), isolated_reason="a rewrite", isolated_by="hub")
        )
        real(conn, project_ids)

    monkeypatch.setattr(events, "lock_projects", isolating_first)
    method = "PATCH" if path == "/me" else "POST"
    done = w.call(method, path, body=body)

    def written(membership_id: int) -> bool:
        with w.engine.connect() as conn:
            if path == "/me":
                found = conn.execute(
                    select(t.instance_attachment.c.paused_since).where(
                        instances.attachment_of(w.agent.credential_id, membership_id)
                    )
                ).scalar_one()
            else:
                found = conn.execute(
                    select(t.membership.c.limit_until).where(t.membership.c.id == membership_id)
                ).scalar_one()
        return found is not None

    if named:
        assert done.status_code == 403, done.text
        assert done.json()["error"]["details"]["reason"] == "isolated"
        assert not written(w.in_b)
    else:
        assert done.status_code == 200, done.text
        assert len(done.json()["projects"]) == 1
        assert written(w.in_b)
    assert not written(w.in_a)


# --- the rest of the boundary, per route (review of #2105) ----------------------------------


def _other_in(w: World, project_id: str) -> factory.Agent:
    """Another agent of the same owner, a member of `project_id` alone."""
    return factory.agent(w.engine, project_id, w.agent.owner_id, instance="oth1")


def test_a_bridge_in_b_carries_through_its_attachment_in_b_alone(world: World) -> None:
    """The instance is a bridge in B (its membership there, §2.3): a call with `Maity-For` on
    B's routes acts as the served agent through B's row; on A's routes, where it bridges
    nothing, the same header is refused, A's row never standing in for B's."""
    w = world
    served = _other_in(w, w.beta)
    with w.engine.begin() as conn:
        conn.execute(
            t.bridge.insert().values(
                id=new_id("bridge"),
                project_id=w.beta,
                served=served.membership_id,
                bridge=w.in_b,
                purpose="git for the designer",
                cross_owner=False,
                created_by=w.agent.owner_id,
                created_at=clock.now(),
            )
        )
    carried = {"Maity-For": served.agent_id}
    said = w.call("POST", f"{B}/events", sign=False, body=NOTICE, extra=carried)
    assert said.status_code == 201, said.text
    actor = said.json()["actor"]
    assert actor["member_id"] == served.agent_id, said.text
    assert w.agent.agent_id in json.dumps(actor["via"]), said.text
    before = w.event_count(w.alpha)
    refused = w.call("POST", f"{A}/events", sign=False, body=NOTICE, extra=carried)
    assert refused.status_code in (403, 404), refused.text
    assert w.event_count(w.alpha) == before


def test_patch_me_without_project_changes_nothing_when_one_project_refuses(
    world: World,
) -> None:
    """All or nothing (§5.3, "Per project"): A's own pause would be lifted, but in B a human
    paused the instance, which the agent may not lift; the call is refused with B named in
    `details.project`, and A's pause stays."""
    w = world
    own = w.call("PATCH", "/me", body={"paused": {"reason": "mine"}, "project": "maintainer/alpha"})
    assert own.status_code == 200, own.text
    with w.engine.begin() as conn:
        conn.execute(
            update(t.instance_attachment)
            .where(instances.attachment_of(w.agent.credential_id, w.in_b))
            .values(paused_since=clock.now(), paused_by=w.agent.owner_id, paused_reason="stop")
        )
    lifted = w.call("PATCH", "/me", body={"paused": None})
    _refused(lifted, "forbidden")
    details = lifted.json()["error"]["details"]
    assert details["reason"] == "paused_by_human"
    assert details["project"] == "maintainer/beta"
    assert _attachment(w, w.in_a).paused_since is not None  # A's change rolled back
    assert _attachment(w, w.in_b).paused_by == w.agent.owner_id


def test_post_me_limit_without_project_changes_nothing_when_one_project_refuses(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All or nothing for `POST /me/limit` too: the write in B is refused after A's, and
    neither stays; `details.project` names B."""
    from maity_hub import availability
    from maity_hub.errors import ApiError

    w = world
    real = availability.set_agent_limit

    def refusing(conn: Any, row: Any, *args: Any, **kwargs: Any) -> None:
        if row.id == w.in_b:
            raise ApiError(409, "conflict", "not here", {"reason": "test"})
        real(conn, row, *args, **kwargs)

    monkeypatch.setattr(availability, "set_agent_limit", refusing)
    until = clock.rfc3339(clock.now() + timedelta(hours=1))
    refused = w.call("POST", "/me/limit", body={"until": until})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"]["project"] == "maintainer/beta"
    assert _limit(w, w.in_a) is None and _limit(w, w.in_b) is None


def test_dormant_applies_per_project(world: World) -> None:
    """`dormant` with `project` in that attachment alone, without it in every one that is
    not isolated; `GET /me` shows it per project."""
    w = world
    one = w.call("PATCH", "/me", body={"dormant": True, "project": "maintainer/beta"})
    assert one.status_code == 200, one.text
    assert _attachment(w, w.in_b).dormant_since is not None
    assert _attachment(w, w.in_a).dormant_since is None
    shown = {p["id"]: p["dormant"] for p in w.call("GET", "/me").json()["projects"]}
    assert shown[w.alpha] is None and shown[w.beta] is not None
    w.isolate(w.in_b)
    woke = w.call("PATCH", "/me", body={"dormant": False})
    assert woke.status_code == 200, woke.text
    assert _attachment(w, w.in_b).dormant_since is not None  # B is isolated, skipped
    both = w.call("PATCH", "/me", body={"dormant": True})
    assert both.status_code == 200, both.text
    assert _attachment(w, w.in_a).dormant_since is not None


def test_a_soul_proposal_is_filed_in_the_project_it_names(world: World) -> None:
    """`POST /me/soul/proposals` files its consent request in the project named (202); an
    isolated one there is `isolated`, and nothing is filed."""
    w = world

    def requests_in(project_id: str) -> int:
        with w.engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(t.request)
                    .where(t.request.c.project_id == project_id)
                ).scalar_one()
            )

    proposal = {"markdown": "me", "reason": "why", "project": "maintainer/beta"}
    filed = w.call("POST", "/me/soul/proposals", body=proposal)
    assert filed.status_code == 202, filed.text
    assert (requests_in(w.alpha), requests_in(w.beta)) == (0, 1)
    w.isolate(w.in_b)
    refused = w.call("POST", "/me/soul/proposals", body=proposal)
    _refused(refused, "forbidden")
    assert refused.json()["error"]["details"]["reason"] == "isolated"
    assert (requests_in(w.alpha), requests_in(w.beta)) == (0, 1)


def test_a_cross_chat_post_from_an_isolated_project_is_refused(chat: Any) -> None:
    """The author is isolated in B: a mention posted from B is `isolated` and charges
    nothing; from A it goes on (§9.5, §6.2)."""
    author = chat["author"]
    with chat["engine"].begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == chat["in_b"])
            .values(isolated_since=clock.now(), isolated_reason="a rewrite", isolated_by="hub")
        )
    refused = author.post(chat["path"], {"body": chat["mention"], "project": "maintainer/beta"})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "isolated"
    assert chat["charged"] == []
    posted = author.post(chat["path"], {"body": chat["mention"], "project": "maintainer/alpha"})
    assert posted.status_code == 201, posted.text


def test_a_cross_chat_author_acts_through_its_own_live_attachment_only(world: World) -> None:
    """`_author_actor`: in a project the instance is attached to and not isolated in, the
    member actor of that attachment; isolated there, detached from it, or in a project where
    only its profile is a member, an agent that is no member there (§9.5, Q4)."""
    from maity_hub import cross_chats
    from maity_hub.auth.caller import Caller

    w = world
    gamma = factory.project(w.engine, "gamma")
    factory.membership(w.engine, gamma, agent_id=w.agent.agent_id)  # the profile, not attached
    caller = Caller(
        kind="agent",
        via="signed",
        agent_id=w.agent.agent_id,
        owner_id=w.agent.owner_id,
        credential_id=w.agent.credential_id,
        instance=w.agent.instance,
    )

    def acting(project_id: str) -> int | None:
        with w.engine.connect() as conn:
            found: int | None = cross_chats._author_actor(conn, caller, project_id).membership_id
        return found

    assert (acting(w.alpha), acting(w.beta), acting(gamma)) == (w.in_a, w.in_b, None)
    w.isolate(w.in_a)
    w.detach(w.in_b)
    assert (acting(w.alpha), acting(w.beta)) == (None, None)


def test_a_member_in_b_alone_is_read_through_bs_attachment_only(world: World) -> None:
    """Another agent is a member of B alone: the instance reads its picture and may report it
    while attached to B and not isolated there; isolated in B, or detached from it, neither,
    though A stays (§6.10, §16.8, §6.17)."""
    w = world
    other = _other_in(w, w.beta)
    avatar = f"/avatars/{other.agent_id}"

    def report() -> Any:
        return w.call(
            "POST",
            "/reports",
            body={"target": {"type": "profile", "id": other.agent_id}, "reason": "spam"},
        )

    assert w.call("GET", avatar).status_code == 200
    filed = report()
    assert filed.status_code in (200, 201, 202), filed.text
    w.isolate(w.in_b)
    assert w.call("GET", avatar).status_code == 404
    assert report().status_code == 404
    with w.engine.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == w.in_b).values(isolated_since=None)
        )
    w.detach(w.in_b)
    assert w.call("GET", avatar).status_code == 404
    assert report().status_code == 404


def test_bootstrap_with_project_reads_through_that_attachment(world: World) -> None:
    """`GET /bootstrap?project=` answers the project's parts as its single routes would: in
    B while attached and free there; `isolated` once isolated, `not_found` once detached, `me`
    answering either way (§5.4, §6.2)."""
    w = world

    def parts() -> tuple[int, int, int]:
        found = w.call("GET", "/bootstrap?project=maintainer/beta", sign=False)
        assert found.status_code == 200, found.text
        body = found.json()
        return body["me"]["status"], body["head"]["status"], body["project"]["status"]

    assert parts() == (200, 200, 200)
    w.isolate(w.in_b)
    assert parts() == (200, 403, 403)
    w.detach(w.in_b)
    assert parts() == (200, 404, 404)
