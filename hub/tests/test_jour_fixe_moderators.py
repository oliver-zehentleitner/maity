"""docs/api.md §20.2: the right to moderate a jour fixe series, given with two consents; rights
that end on their own; the keepers told of a round nobody could moderate."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, listening
from maity_hub import tables as t
from maity_hub.jourfixe import rounds, worker
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_jour_fixe import BASE, ensure_series, listen

DAILY_UTC = {
    "enabled": True,
    "recurrence": {"freq": "daily"},
    "time": "10:00",
    "timezone": "UTC",
}


@pytest.fixture(autouse=True)
def _no_listeners() -> Iterator[None]:
    yield
    listening.reset()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(select(t.project.c.id)).scalar_one())


def _human(make_client: ClientFactory, engine: Engine, handle: str, role: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, _project_id(engine), role, human_id=human.id)
    return human


def grant(who: flow.Human, sid: str, member_id: str) -> Any:
    return who.post(
        f"{BASE}/jour-fixe/series/{sid}/moderators", {"member_id": member_id, "reason": "t"}
    )


def answer(who: Any, request_id: str, reply: str) -> Any:
    """A personal request is answered at `/requests/{id}`, one to `owner` in the project."""
    personal = who.post(f"/requests/{request_id}/answer", {"reply_id": reply})
    if personal.status_code != 404:
        return personal
    return who.post(f"{BASE}/requests/{request_id}/answer", {"reply_id": reply})


def series(who: Any, sid: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        s for s in who.get(f"{BASE}/jour-fixe/series").json()["items"] if s["id"] == sid
    )
    return found


def test_a_keeper_granting_anothers_agent_waits_for_its_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _human(make_client, migrated, "friend", "member")
    agent = flow.agent(make_client, friend)
    sid = ensure_series(owner)
    pending = grant(owner, sid, agent.id)
    assert pending.status_code == 202, pending.text
    [request_id] = pending.json()["requests"]
    shown = series(owner, sid)
    assert [p["member_id"] for p in shown["pending_moderators"]] == [agent.id]
    assert shown["moderators"] == []
    refused = answer(owner, request_id, "go")  # the agent's owner answers in person
    assert refused.status_code != 200, refused.text
    with migrated.connect() as conn:
        still = conn.execute(
            select(t.request.c.status).where(t.request.c.id == request_id)
        ).scalar_one()
    assert still == "open"
    assert answer(friend, request_id, "go").status_code == 200
    shown = series(owner, sid)
    assert [m["member_id"] for m in shown["moderators"]] == [agent.id]
    assert shown["pending_moderators"] == []


def test_an_owner_granting_its_own_agent_waits_for_a_keeper(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _human(make_client, migrated, "friend", "member")
    agent = flow.agent(make_client, friend)
    sid = ensure_series(owner)
    pending = grant(friend, sid, agent.id)
    assert pending.status_code == 202, pending.text
    [request_id] = pending.json()["requests"]
    assert answer(friend, request_id, "go").status_code in (403, 404)  # no keeper
    assert answer(owner, request_id, "go").status_code == 200
    assert [m["member_id"] for m in series(owner, sid)["moderators"]] == [agent.id]


def test_a_no_drops_the_grant(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A `no` of the agent's owner drops the pending grant (§20.2); every holder of
    `members:admin` is a keeper too, so a grant never misses both consents here."""
    friend = _human(make_client, migrated, "friend", "member")
    agent = flow.agent(make_client, friend)
    sid = ensure_series(owner)
    pending = grant(owner, sid, agent.id)
    assert pending.status_code == 202, pending.text
    [request_id] = pending.json()["requests"]
    assert answer(friend, request_id, "no").status_code == 200
    with migrated.connect() as conn:
        rows = conn.execute(select(t.jour_fixe_moderator)).all()
    assert rows == [] and series(owner, sid)["pending_moderators"] == []


def test_a_right_ends_with_its_membership_and_the_upgrades_consents_are_filed(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    friend = _human(make_client, migrated, "friend", "member")
    mine = flow.agent(make_client, owner)
    theirs = flow.agent(make_client, friend)
    sid = ensure_series(owner)
    assert grant(owner, sid, mine.id).status_code == 201
    with migrated.begin() as conn:
        member_of = dict(conn.execute(select(t.membership.c.agent_id, t.membership.c.id)).all())
        conn.execute(  # as the upgrade leaves a grant whose owner did not set the policy
            insert(t.jour_fixe_moderator).values(
                series_id=sid,
                membership_id=member_of[theirs.id],
                state="pending",
                granted_by=owner.id,
                granted_at=clock.now(),
                owner_consent=False,
                keeper_consent=True,
            )
        )
    assert owner.delete(f"{BASE}/members/{mine.id}").status_code == 200
    worker.sweep(migrated)
    with migrated.connect() as conn:
        rows = {r.membership_id: r for r in conn.execute(select(t.jour_fixe_moderator))}
        filed = conn.execute(
            select(t.request).where(t.request.c.id == rows[member_of[theirs.id]].owner_request_id)
        ).one()
    assert member_of[mine.id] not in rows  # the removed member's right ended
    assert filed.to_human == friend.id and filed.proposal["side"] == "owner"
    assert answer(friend, filed.id, "go").status_code == 200
    assert [m["member_id"] for m in series(owner, sid)["moderators"]] == [theirs.id]


def test_a_slot_nobody_could_moderate_is_an_inbox_item_for_the_keepers(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    member = flow.agent(make_client, owner)
    listen(member)
    sid = ensure_series(owner)
    owner.patch(f"{BASE}/jour-fixe/series/{sid}", {**DAILY_UTC, "reason": "t"})
    next_at = datetime.fromisoformat(owner.get(f"{BASE}/jour-fixe").json()["series"][0]["next_at"])
    now[0] = next_at + timedelta(seconds=30)
    owner.get("/me")
    worker.sweep(migrated)
    items = owner.get("/me/notifications").json()["items"]
    skipped = [i for i in items if (i.get("target") or {}).get("type") == "jour_fixe_series"]
    assert len(skipped) == 1 and skipped[0]["kind"] == "inbox"
    assert skipped[0]["title"] == "Jour fixe skipped, nobody to moderate: How we work"


def test_a_human_online_counts_its_minutes_too(
    owner: flow.Human, migrated: Engine, now: list[datetime]
) -> None:
    owner.get("/me")
    with migrated.begin() as conn:
        rounds.record_presence(conn, now[0])
        counted = set(conn.execute(select(t.presence_minute.c.membership_id)).scalars())
        human_member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == owner.id)
        ).scalar_one()
    assert human_member in counted


def _status(engine: Engine, request_id: str) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                select(t.request.c.status).where(t.request.c.id == request_id)
            ).scalar_one()
        )


def test_no_consent_request_outlives_its_grant_or_its_series(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """ap44 at #947: ending a pending grant, or deleting its series, withdraws its consent
    request; a second grant from the same side asks nobody again."""
    friend = _human(make_client, migrated, "friend", "member")
    first, second = flow.agent(make_client, friend), flow.agent(make_client, friend)
    sid = ensure_series(owner)
    [ended] = grant(owner, sid, first.id).json()["requests"]
    again = grant(owner, sid, first.id)
    assert again.status_code == 202 and again.json()["requests"] == [ended]  # not asked twice
    gone = owner.delete(f"{BASE}/jour-fixe/series/{sid}/moderators/{first.id}")
    assert gone.status_code == 200, gone.text
    assert _status(migrated, ended) == "withdrawn"
    [orphan] = grant(owner, sid, second.id).json()["requests"]
    deleted = owner.client.request(
        "DELETE",
        f"/api/v1{BASE}/jour-fixe/series/{sid}",
        json={"reason": "t"},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert deleted.status_code == 200, deleted.text
    assert _status(migrated, orphan) == "withdrawn"


def test_the_missing_side_granting_too_makes_the_right_active(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """ap44 at #947: the agent's owner granting a grant the keeper made pending gives the
    missing consent: the right takes effect and the request it no longer needs is withdrawn."""
    friend = _human(make_client, migrated, "friend", "member")
    agent = flow.agent(make_client, friend)
    sid = ensure_series(owner)
    [asked] = grant(owner, sid, agent.id).json()["requests"]
    done = grant(friend, sid, agent.id)
    assert done.status_code == 201, done.text
    assert [m["member_id"] for m in series(owner, sid)["moderators"]] == [agent.id]
    assert _status(migrated, asked) == "withdrawn"
    with migrated.connect() as conn:
        rows = conn.execute(select(t.jour_fixe_moderator.c.state)).scalars().all()
    assert rows == ["active"]  # the withdrawal left the right as it is


def test_the_no_moderator_item_goes_with_its_series(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    member = flow.agent(make_client, owner)
    listen(member)
    sid = ensure_series(owner)
    owner.patch(f"{BASE}/jour-fixe/series/{sid}", {**DAILY_UTC, "reason": "t"})
    next_at = datetime.fromisoformat(owner.get(f"{BASE}/jour-fixe").json()["series"][0]["next_at"])
    now[0] = next_at + timedelta(seconds=30)
    owner.get("/me")
    worker.sweep(migrated)

    def items() -> list[Any]:
        found = owner.get("/me/notifications").json()["items"]
        return [i for i in found if (i.get("target") or {}).get("type") == "jour_fixe_series"]

    assert len(items()) == 1
    owner.client.request(
        "DELETE",
        f"/api/v1{BASE}/jour-fixe/series/{sid}",
        json={"reason": "t"},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert items() == []  # §18.1: dropped once the series cannot be read


def test_a_replayed_grant_names_the_same_consent_requests(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """dzse at #947: a replay of the `202` names that grant's requests, not another's."""
    friend = _human(make_client, migrated, "friend", "member")
    first, second = flow.agent(make_client, friend), flow.agent(make_client, friend)
    sid = ensure_series(owner)
    assert grant(owner, sid, first.id).status_code == 202  # another pending grant beside it
    headers = {"X-CSRF-Token": owner.csrf, "Idempotency-Key": "jf-grant-replay-1"}
    path = f"/api/v1{BASE}/jour-fixe/series/{sid}/moderators"
    body = {"member_id": second.id, "reason": "t"}
    original = owner.client.post(path, json=body, headers=headers)
    replayed = owner.client.post(path, json=body, headers=headers)
    assert original.status_code == replayed.status_code == 202, replayed.text
    assert replayed.json()["requests"] == original.json()["requests"]
