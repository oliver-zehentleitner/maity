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

from maity_hub import clock, instances
from maity_hub import tables as t
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

    def call(self, method: str, path: str, *, sign: bool = True, body: Any = None) -> Any:
        """The agent's call to `path` below /api/v1, signed or as Bearer."""
        full = f"{API}{path}"
        raw = json.dumps(body).encode() if body is not None else b""
        route, _, query = full.partition("?")
        headers = (
            signed(self.agent, method, route, query, raw) if sign else bearer(self.agent)
        ) | {"Content-Type": "application/json"}
        if method != "GET":
            headers["Idempotency-Key"] = f"key-{secrets.token_hex(12)}"
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


def test_a_detached_attachment_alone_makes_bearer_work_again(world: World) -> None:
    w = world
    w.require_signing(w.alpha)
    _refused(w.call("GET", "/me", sign=False), "signature_required")
    _refused(w.call("GET", f"{B}/tasks", sign=False), "signature_required")
    w.detach(w.in_a)
    assert w.call("GET", f"{B}/tasks", sign=False).status_code == 200
    me = w.call("GET", "/me", sign=False)
    assert me.status_code == 200, me.text
    assert [p["id"] for p in me.json()["projects"]] == [w.beta]


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
