"""docs/api.md §1.5: a replayed `Idempotency-Key` passes the read a fresh request would.

The replay answers with the resource as it is now, so it asks first whether the caller may
still read it: a member removed since gets `not_found`, as their GET does, and never the
current state. Every registered resource type says how its replay re-checks (`register`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import idempotency
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

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
            found: str = (
                conn.execute(
                    select(t.card_history.c.id)
                    .where(t.card_history.c.card_id == self.card_id)
                    .order_by(t.card_history.c.id)
                )
                .scalars()
                .first()
            )
        return found

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
    "message": lambda w: ("POST", f"{CHATS}/{w.group_chat()}/messages", {"body": "bea says"}),
    "participation": lambda w: (
        "DELETE",
        f"{CHATS}/{w.group_chat()}/participants/{w.bea.id}",
        None,
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
