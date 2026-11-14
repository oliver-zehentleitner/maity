"""docs/api.md §1.5: a replayed `Idempotency-Key` passes the read a fresh request would.

The replay answers with the resource as it is now, so it asks first whether the caller may
still read it: a member removed since gets `not_found`, as their GET does, and never the
current state. Every registered resource type says how its replay re-checks (`register`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, idempotency, listening
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_jour_fixe import listen

PROJECT = "/projects/maintainer/maity"
TASKS = f"{PROJECT}/tasks"
CHATS = f"{PROJECT}/conversations"


class World:
    def __init__(self, make_client: ClientFactory, engine: Engine) -> None:
        self.engine = engine
        self.owner = flow.human(make_client, engine)
        project = flow.project(self.owner)
        self.project_id: str = project["id"]
        self.bea = flow.human(make_client, engine, "bea")
        factory.membership(engine, self.project_id, "admin", human_id=self.bea.id)
        self.agent = flow.agent(make_client, self.owner)
        card = self.owner.post(TASKS, {"title": "A card"})
        assert card.status_code == 201, card.text
        self.card_id: str = card.json()["id"]

    def send(self, who: flow.Human, call: tuple[str, str, Any], key: str) -> Any:
        method, path, body = call
        return who.client.request(
            method,
            f"/api/v1{path}",
            json=body,
            headers={"X-CSRF-Token": who.csrf, "Idempotency-Key": key},
        )

    def remove_bea(self) -> None:
        removed = self.owner.delete(f"{PROJECT}/members/{self.bea.id}")
        assert removed.status_code == 200, removed.text

    def history_id(self) -> str:
        with self.engine.connect() as conn:
            found = conn.execute(
                select(t.card_history.c.id)
                .where(t.card_history.c.card_id == self.card_id)
                .order_by(t.card_history.c.id)
            ).scalar()
        assert found is not None
        return str(found)

    def group_chat(self) -> str:
        made = self.bea.post(CHATS, {"title": "Bea's chat", "participants": [self.owner.id]})
        assert made.status_code == 201, made.text
        chat_id: str = made.json()["id"]
        return chat_id


# Each case: the write Bea makes with a key (built once the world exists), and a change the
# owner makes afterwards that a replay must not show her.
Case = Callable[[World], tuple[str, str, Any]]
CASES: dict[str, Case] = {
    "project": lambda w: ("PATCH", PROJECT, {"name": "Bea named it"}),
    "note": lambda w: ("POST", f"{TASKS}/{w.card_id}/notes", {"body": "bea's note"}),
    "link": lambda w: (
        "POST",
        f"{TASKS}/{w.card_id}/links",
        {"kind": "url", "url": "https://example.com/bea"},
    ),
    "history": lambda w: (
        "POST",
        f"{TASKS}/{w.card_id}/history/{w.history_id()}/redact",
        {"reason": "bea redacted it"},
    ),
    "invitation": lambda w: ("POST", f"{PROJECT}/invitations", {"role": "coder"}),
    "join": lambda w: (
        "POST",
        f"{PROJECT}/joins",
        {"agent": {"handle": "bea-agent", "display_name": "Bea's agent"}},
    ),
    "request": lambda w: (
        "POST",
        f"{PROJECT}/requests",
        {"class": "info", "title": "Bea asks", "to": "owner"},
    ),
    "credential": lambda w: (
        "POST",
        f"{PROJECT}/credentials/{w.agent.credential_id}/revoke",
        {},
    ),
    "event": lambda w: (
        "POST",
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "bea notes"},
    ),
    "message": lambda w: ("POST", f"{CHATS}/{w.group_chat()}/messages", {"body": "bea says"}),
    "participation": lambda w: (
        "DELETE",
        f"{CHATS}/{w.group_chat()}/participants/{w.bea.id}",
        None,
    ),
    "jour_fixe_series": lambda w: (
        "POST",
        f"{PROJECT}/jour-fixe/series",
        {"topic": "Bea's series", "circle": "all", "reason": "t"},
    ),
}


@pytest.mark.parametrize("kind", sorted(CASES))
def test_a_member_removed_since_gets_not_found_on_replay(
    kind: str, make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    call = CASES[kind](world)
    key = f"replay-access-{kind}"
    first = world.send(world.bea, call, key)
    assert 200 <= first.status_code < 300, first.text
    again = world.send(world.bea, call, key)
    assert again.status_code == first.status_code, again.text
    assert again.headers["Idempotent-Replayed"] == "true"  # the happy path stays
    world.remove_bea()
    gone = world.send(world.bea, call, key)
    assert gone.status_code == 404, gone.text
    assert gone.json()["error"]["code"] == "not_found"
    assert "Idempotent-Replayed" not in gone.headers


def test_a_replay_never_shows_what_changed_after_the_removal(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    call = CASES["project"](world)
    assert world.send(world.bea, call, "replay-access-rename").status_code == 200
    world.remove_bea()
    renamed = world.owner.patch(PROJECT, {"name": "Secret plans"})
    assert renamed.status_code == 200, renamed.text
    gone = world.send(world.bea, call, "replay-access-rename")
    assert gone.status_code == 404
    assert "Secret plans" not in gone.text


def test_a_guests_no_op_patch_does_not_replay_after_the_removal(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """A `PATCH` of the project that needs no write scope (only a `reason`) still stores its
    key; once the guest is removed, its replay is `not_found`, not the project as it is."""
    world = World(make_client, migrated)
    guest = flow.human(make_client, migrated, "gus")
    factory.membership(migrated, world.project_id, "guest", human_id=guest.id)
    call = ("PATCH", PROJECT, {"reason": "x"})
    first = world.send(guest, call, "replay-access-guest")
    assert first.status_code == 200, first.text
    again = world.send(guest, call, "replay-access-guest")
    assert again.headers["Idempotent-Replayed"] == "true"
    removed = world.owner.delete(f"{PROJECT}/members/{guest.id}")
    assert removed.status_code == 200, removed.text
    world.owner.patch(PROJECT, {"name": "Secret plans"})
    gone = world.send(guest, call, "replay-access-guest")
    assert gone.status_code == 404, gone.text
    assert "Secret plans" not in gone.text


def test_a_takeovers_replay_checks_the_project(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Through the check itself: a takeover needs a stalled holder to open."""
    world = World(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            t.takeover.insert().values(
                **_takeover_row(conn, world.project_id, world.card_id, world.owner.id)
            )
        )
    check = idempotency.LOADERS["takeover"].may_see
    bea = _caller(migrated, world.bea.id)
    with migrated.connect() as conn:
        assert check(conn, "tko-replay-1", bea)
    world.remove_bea()
    with migrated.connect() as conn:
        assert not check(conn, "tko-replay-1", bea)


# --- a jour fixe round of an owner's series stays with its circle (§20.7) ---------------------


@pytest.fixture
def _no_listeners() -> Iterator[None]:
    yield
    listening.reset()


class OwnersCircle:
    """`friend`'s own series, moderated by its agent `lead`; `carl` is a member outside the
    circle whose agent `outsider` holds the series' moderator right too, and starts a round
    that `lead` moderates. `worker`, friend's other agent, answers it by name."""

    def __init__(self, make_client: ClientFactory, engine: Engine) -> None:
        self.engine = engine
        self.owner = flow.human(make_client, engine)
        self.project_id: str = flow.project(self.owner)["id"]
        self.friend = self._member(make_client, "friend")
        self.carl = self._member(make_client, "carl")
        self.lead = flow.agent(make_client, self.friend)
        self.worker = flow.agent(make_client, self.friend)
        self.outsider = flow.agent(make_client, self.carl)
        listen(self.lead)
        listen(self.worker)
        made = self.friend.post(
            f"{PROJECT}/jour-fixe/series",
            {
                "topic": "My agents",
                "circle": "owner",
                "circle_owner": self.friend.id,
                "reason": "t",
            },
        )
        assert made.status_code == 201, made.text
        self.series: str = made.json()["id"]
        assert self._grant(self.lead.id).status_code == 201
        pending = self._grant(self.outsider.id)
        assert pending.status_code == 202, pending.text
        [request_id] = pending.json()["requests"]
        consent = self.carl.post(f"/requests/{request_id}/answer", {"reply_id": "go"})
        if consent.status_code == 404:
            consent = self.carl.post(f"{PROJECT}/requests/{request_id}/answer", {"reply_id": "go"})
        assert consent.status_code == 200, consent.text
        self._online(self.lead.id)  # the most minutes online: `lead` moderates (§20.2)
        self.start = (
            "POST",
            f"{PROJECT}/jour-fixe/series/{self.series}/rounds",
            {"reason": "look back"},
        )
        started = self.send_as_outsider(self.start, "replay-circle-start")
        assert started.status_code == 201, started.text
        assert started.json()["moderator"]["member_id"] == self.lead.id
        self.round: str = started.json()["id"]
        answered = self.worker.post(
            f"{PROJECT}/jour-fixe/rounds/{self.round}/answers", {"went_well": "a"}
        )
        assert answered.status_code == 201, answered.text
        self.answer: str = answered.json()["id"]

    def _member(self, make_client: ClientFactory, handle: str) -> flow.Human:
        human = flow.human(make_client, self.engine, handle)
        factory.membership(
            self.engine, self.project_id, "member", human_id=human.id, last_seen_at=clock.now()
        )
        return human

    def _grant(self, member_id: str) -> Any:
        return self.friend.post(
            f"{PROJECT}/jour-fixe/series/{self.series}/moderators",
            {"member_id": member_id, "reason": "t"},
        )

    def _online(self, agent_id: str) -> None:
        with self.engine.begin() as conn:
            membership_id = conn.execute(
                select(t.membership.c.id).where(t.membership.c.agent_id == agent_id)
            ).scalar_one()
            now = clock.now().replace(second=0, microsecond=0)
            for minute in range(1, 6):
                conn.execute(
                    insert(t.presence_minute).values(
                        membership_id=membership_id, minute=now - timedelta(minutes=minute)
                    )
                )

    def send_as_outsider(self, call: tuple[str, str, Any], key: str) -> Any:
        method, path, body = call
        return self.outsider.client.request(
            method,
            f"/api/v1{path}",
            json=body,
            headers=self.outsider.auth | {"Idempotency-Key": key},
        )


def test_a_member_outside_the_circle_gets_not_found_on_a_rounds_replay(
    make_client: ClientFactory, migrated: Engine, _no_listeners: None
) -> None:
    """The outsider started the round but does not read it: its `GET` is `not_found`, and so
    is the replay of its start, which would answer with the round as it is now."""
    world = OwnersCircle(make_client, migrated)
    assert world.outsider.get(f"{PROJECT}/jour-fixe/rounds/{world.round}").status_code == 404
    again = world.send_as_outsider(world.start, "replay-circle-start")
    assert again.status_code == 404, again.text
    assert again.json()["error"]["code"] == "not_found"
    assert "Idempotent-Replayed" not in again.headers
    assert "My agents" not in again.text


# Each jour fixe type: the id its stored key names, in `friend`'s round or series. `carl`, a
# member outside the circle who does not see the series, may not see it on a replay; `friend`
# may (§20.1, §20.7).
CIRCLE_CASES: dict[str, Callable[[OwnersCircle], str]] = {
    "jour_fixe_round": lambda w: w.round,
    "jour_fixe_report": lambda w: w.round,
    "jour_fixe_answer": lambda w: w.answer,
    "jour_fixe_post": lambda w: f"{w.round}/p1",
    "jour_fixe_series": lambda w: w.series,
    "jour_fixe_grant": lambda w: w.series,
}


def test_every_jour_fixe_type_has_a_circle_case(make_client: ClientFactory) -> None:
    make_client()
    assert set(CIRCLE_CASES) == {n for n in idempotency.LOADERS if n.startswith("jour_fixe_")}


@pytest.mark.parametrize("kind", sorted(CIRCLE_CASES))
def test_a_jour_fixe_replay_stays_with_the_circle(
    kind: str, make_client: ClientFactory, migrated: Engine, _no_listeners: None
) -> None:
    world = OwnersCircle(make_client, migrated)
    check = idempotency.LOADERS[kind].may_see
    ref = CIRCLE_CASES[kind](world)
    with migrated.connect() as conn:
        assert check(conn, ref, _caller(migrated, world.friend.id))
        assert not check(conn, ref, _caller(migrated, world.carl.id))


def _caller(engine: Engine, human_id: str) -> Any:
    from maity_hub.auth.caller import Caller

    return Caller(kind="human", via="cookie", human_id=human_id)


def _takeover_row(conn: Any, project_id: str, card_id: str, human_id: str) -> dict[str, Any]:
    from maity_hub import clock

    owner = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project_id, t.membership.c.human_id == human_id
        )
    ).scalar_one()
    now = clock.now()
    return {
        "id": "tko-replay-1",
        "project_id": project_id,
        "task_id": card_id,
        "from_member": owner,
        "to_member": owner,
        "reason": "silent",
        "status": "open",
        "window_minutes": 30,
        "window_ends_at": now,
        "created_at": now,
    }


# --- every resource type says how its replay re-checks ---------------------------------------

# How each type's replay re-checks the caller. A new type fails here until it is named, so a
# loader cannot be added without deciding what its replay may show (§1.5).
OWN = {"chat_access", "abuse_report"}
CALLERS_RECORD = {"me", "human_profile", "preferences"}
ROUTE_CHECKS = {"avatar"}


def test_every_loader_is_registered_with_a_check(make_client: ClientFactory) -> None:
    make_client()  # imports every route, and with it every registration
    assert all(callable(r.may_see) for r in idempotency.LOADERS.values())
    by_check = {
        name: r.may_see
        for name, r in idempotency.LOADERS.items()
        if name != "probe"  # test_idempotency's own
    }
    assert {n for n, c in by_check.items() if c is idempotency.own} == OWN
    assert {n for n, c in by_check.items() if c is idempotency.is_caller} == CALLERS_RECORD
    assert {n for n, c in by_check.items() if c is idempotency.checked_by_route} == ROUTE_CHECKS
    assert set(by_check) == EXPECTED


EXPECTED = {
    "abuse_report",
    "agent",
    "attachment",
    "avatar",
    "blind_redaction",
    "bridge",
    "chat_access",
    "conversation",
    "credential",
    "cross_chat",
    "cross_message",
    "cross_participation",
    "event",
    "forge_webhook",
    "history",
    "human_profile",
    "invitation",
    "join",
    "jour_fixe_answer",
    "jour_fixe_grant",
    "jour_fixe_post",
    "jour_fixe_report",
    "jour_fixe_round",
    "jour_fixe_series",
    "link",
    "me",
    "member",
    "member_patch",
    "member_read",
    "member_team",
    "memory",
    "message",
    "note",
    "participation",
    "placement",
    "preferences",
    "project",
    "project_banner",
    "project_logo",
    "proposal_request",
    "removed_link",
    "request",
    "restricted_text",
    "roles",
    "runner",
    "runner_attachment",
    "runner_enrollment",
    "runner_removal",
    "runner_revoked",
    "soul",
    "takeover",
    "task",
    "ticker_subscription",
}
