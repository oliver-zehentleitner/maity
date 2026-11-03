"""docs/api.md §5.3 "The owner's digest", the `bell` mode: the record
`agents_not_listening` and its item in the bell (§18.1, §18.2)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select, update

from maity_hub import clock, not_listening_digest
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    human.patch("/me/notification-settings", {"not_listening": {"mode": "bell"}})
    return human


def _episode(engine: Engine, agent: flow.Agent, ago: timedelta | None) -> None:
    """Start (or with `None` end) the episode of the agent's session `ago` back."""
    with engine.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == agent.credential_id)
            .values(not_listening_since=None if ago is None else clock.now() - ago)
        )


def _records(engine: Engine, owner: flow.Human) -> list[Any]:
    with engine.connect() as conn:
        return [
            r.data
            for r in conn.execute(
                select(t.account_record)
                .where(
                    t.account_record.c.human_id == owner.id,
                    t.account_record.c.type == "agents_not_listening",
                )
                .order_by(t.account_record.c.n)
            )
        ]


def _bell(owner: flow.Human) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = owner.get("/me/notifications", params={"limit": 50}).json()[
        "items"
    ]
    return [i for i in items if (i.get("target") or {}).get("type") == "agents"]


def _agent(make_client: ClientFactory, owner: flow.Human) -> flow.Agent:
    agent = flow.agent(make_client, owner)
    assert agent.resume().status_code == 200  # a session to be not listening in
    return agent


def test_an_instance_away_for_the_threshold_is_in_the_bell(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(minutes=30))  # under the default 60
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [] and _bell(owner) == []
    _episode(migrated, agent, timedelta(minutes=61))
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [{"instances": 1, "holding": 0}]
    [item] = _bell(owner)
    assert item["kind"] == "inbox"
    assert item["title"] == "1 of your agent instances are not listening"
    assert item["target"] == {"type": "agents"} and item["url"].endswith("/agents")
    counts = owner.get("/me/notifications", params={"limit": 0}).json()["counts"]
    assert counts["inbox"] == 1
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [
        {"instances": 1, "holding": 0}
    ]  # one record while it lasts


def test_the_count_is_read_live_and_the_item_goes_when_none_is_away(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = _agent(make_client, owner), _agent(make_client, owner)
    _episode(migrated, first, timedelta(hours=2))
    not_listening_digest.run(migrated)
    _episode(migrated, second, timedelta(hours=2))
    assert _bell(owner)[0]["title"] == "2 of your agent instances are not listening"
    _episode(migrated, first, None)
    _episode(migrated, second, None)
    assert _bell(owner) == []  # no instance away: not listed, before the next hour
    not_listening_digest.run(migrated)
    # One was away at the first hour; the record keeps that count, the title reads live.
    assert _records(migrated, owner) == [
        {"instances": 1, "holding": 0},
        {"instances": 0, "holding": 0},
    ]
    _episode(migrated, first, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert _records(migrated, owner)[-1] == {
        "instances": 1,
        "holding": 0,
    }  # a new phase, a new item
    assert len(_bell(owner)) == 1


def test_the_projects_own_threshold_overrides_the_personal_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _agent(make_client, owner)
    owner.patch(f"{BASE}/me/settings", {"not_listening": {"minutes": 180}})
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert _bell(owner) == []
    owner.patch(f"{BASE}/me/settings", {"not_listening": {"minutes": 90}})
    assert len(_bell(owner)) == 0  # the record waits for the hour
    not_listening_digest.run(migrated)
    assert len(_bell(owner)) == 1


@pytest.mark.parametrize("mode", ["inbox", "off"])
def test_only_bell_writes_the_record_and_leaving_it_closes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, mode: str
) -> None:
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert len(_bell(owner)) == 1
    changed = owner.patch("/me/notification-settings", {"not_listening": {"mode": mode}})
    assert changed.status_code == 200, changed.text
    assert _records(migrated, owner) == [
        {"instances": 1, "holding": 0},
        {"instances": 0, "holding": 0},
    ]  # at the PATCH
    assert _bell(owner) == []
    not_listening_digest.run(migrated)
    assert _records(migrated, owner)[-1] == {"instances": 0, "holding": 0}


def test_the_worker_runs_on_the_hour() -> None:
    now = clock.now().replace(minute=37, second=5, microsecond=12)
    due = not_listening_digest.next_hour(now)
    assert (due.minute, due.second, due.microsecond) == (0, 0, 0)
    assert timedelta(0) < due - now <= timedelta(hours=1)


def test_a_closed_record_lists_nothing_until_the_next_hour_writes_a_new_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """After `{instances: 0}` the bell waits for the worker: neither a new episode nor
    the switch back to `bell` lists the closed record again."""
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    owner.patch("/me/notification-settings", {"not_listening": {"mode": "off"}})
    assert _records(migrated, owner)[-1] == {"instances": 0, "holding": 0}
    owner.patch("/me/notification-settings", {"not_listening": {"mode": "bell"}})
    assert _bell(owner) == []  # back under bell, an instance away, the newest record closed
    _episode(migrated, agent, None)
    not_listening_digest.run(migrated)
    _episode(migrated, agent, timedelta(hours=3))  # a new episode, before the next hour
    assert _bell(owner) == []
    not_listening_digest.run(migrated)
    assert _records(migrated, owner)[-1] == {"instances": 1, "holding": 0}
    assert len(_bell(owner)) == 1


def test_an_open_record_older_than_the_bell_reads_is_written_anew(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The bell reads records of the last 90 days (`records.KEPT`); an away phase that
    outlasts them gets a new record at the next hour, so it stays listed."""
    from maity_hub.notifications import records

    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.account_record)
            .where(t.account_record.c.type == "agents_not_listening")
            .values(at=clock.now() - records.KEPT - timedelta(days=1))
        )
    assert _bell(owner) == []  # out of the window the bell reads
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [
        {"instances": 1, "holding": 0},
        {"instances": 1, "holding": 0},
    ]
    assert len(_bell(owner)) == 1


def test_marking_it_read_leaves_it_unread_while_an_instance_is_away(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The third open matter (§18.2, §18.3): no caller marks it read; it reads as read
    once no instance is away any more."""
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [item] = _bell(owner)
    marked = owner.post("/me/notifications/read", {"ids": [item["id"]]})
    assert marked.status_code == 200, marked.text
    assert marked.json()["counts"]["inbox"] == 1
    [again] = _bell(owner)
    assert again["read"] is False
    unread = owner.get("/me/notifications", params={"limit": 50, "unread": "true"}).json()
    assert any((i.get("target") or {}).get("type") == "agents" for i in unread["items"])


# --- inbox: one digest request per owner -------------------------------------------------


@pytest.fixture
def inbox_owner(owner: flow.Human) -> flow.Human:
    changed = owner.patch("/me/notification-settings", {"not_listening": {"mode": "inbox"}})
    assert changed.status_code == 200, changed.text
    return owner


def _digests(owner: flow.Human, status: str = "all") -> list[dict[str, Any]]:
    items = owner.get("/requests", params={"status": status}).json()["items"]
    return [r for r in items if r["filed_by"] == "hub" and r["project"] is None]


def _created_records(engine: Engine, owner: flow.Human) -> int:
    with engine.connect() as conn:
        return len(
            conn.execute(
                select(t.account_record.c.n).where(
                    t.account_record.c.human_id == owner.id,
                    t.account_record.c.type == "personal_request_created",
                )
            ).all()
        )


def test_inbox_keeps_one_digest_request_while_an_instance_is_away(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(minutes=30))  # under the threshold
    not_listening_digest.run(migrated)
    assert _digests(owner) == []
    _episode(migrated, agent, timedelta(minutes=61))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert (digest["class"], digest["status"], digest["personal"]) == ("info", "open", True)
    assert [o["id"] for o in digest["options"]] == ["seen"]
    assert (digest["project"], digest["org"], digest["asked_by"]) == (None, None, None)
    assert digest["title"] == "1 of your agent instances are not listening"
    handle = owner.get(f"{BASE}/members/{agent.id}").json()["handle"]
    first, _, advice = digest["summary"].partition("\n\n")
    assert first.startswith(f"{handle} ({agent.instance}) in maintainer/maity, since ")
    assert first.endswith(" (UTC)")
    assert advice.startswith("Their harness may have stopped its wait loop")
    shown = owner.get(f"/requests/{digest['id']}").json()
    assert (shown["project"], shown["org"]) == (None, None)
    bell = owner.get("/me/notifications", params={"limit": 50}).json()
    assert bell["counts"]["inbox"] == 1
    [item] = [i for i in bell["items"] if (i["target"] or {}).get("id") == digest["id"]]
    assert item["title"] == "Maity asks you: 1 of your agent instances are not listening"
    assert item["project"] is None
    not_listening_digest.run(migrated)
    assert [d["id"] for d in _digests(owner)] == [digest["id"]]  # one, not a second


def test_a_changed_set_withdraws_the_request_and_files_a_new_one(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The request is never rewritten: an answer from a page that has not seen the change is
    refused, and the new request shows what changed (§5.3)."""
    owner = inbox_owner
    first, second = _agent(make_client, owner), _agent(make_client, owner)
    _episode(migrated, first, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    created = _created_records(migrated, owner)
    _episode(migrated, second, timedelta(hours=2))
    not_listening_digest.run(migrated)
    old, new = sorted(_digests(owner), key=lambda d: d["id"] != digest["id"])
    assert (old["id"], old["status"]) == (digest["id"], "withdrawn")
    assert new["status"] == "open"
    assert new["title"] == "2 of your agent instances are not listening"
    assert len(new["summary"].partition("\n\n")[0].splitlines()) == 2
    assert _created_records(migrated, owner) == created + 1
    stale = owner.post(f"/requests/{digest['id']}/answer", {"reply_id": "seen"})
    assert (stale.status_code, stale.headers["Maity-Error"]) == (409, "request_not_open")
    not_listening_digest.run(migrated)
    assert [d["id"] for d in _digests(owner, "open")] == [new["id"]]  # nothing changed


def test_the_hub_withdraws_it_when_none_is_away(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    _episode(migrated, agent, None)
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert digest["status"] == "withdrawn"
    assert owner.get("/me/notifications", params={"limit": 0}).json()["counts"]["inbox"] == 0


def test_a_request_from_before_the_stored_lines_is_withdrawn_when_none_is_away(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A digest filed before the migration stored no lines: with nobody away the hour's lines
    are empty too, and the request must still go, as the migration says."""
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.request).where(t.request.c.id == digest["id"]).values(not_listening=None)
        )
    _episode(migrated, agent, None)
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert digest["status"] == "withdrawn"


def test_after_seen_only_a_later_episode_files_a_new_one(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner = inbox_owner
    known, later = _agent(make_client, owner), _agent(make_client, owner)
    _episode(migrated, known, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    answered = owner.post(f"/requests/{digest['id']}/answer", {"reply_id": "seen"})
    assert answered.status_code == 200, answered.text
    not_listening_digest.run(migrated)
    assert [d["status"] for d in _digests(owner)] == ["answered"]  # the same one still away
    later_start = clock.now() + timedelta(minutes=1)
    clock.set_source(lambda: later_start + timedelta(hours=2))
    with migrated.begin() as conn:  # an episode that started after the answer
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == later.credential_id)
            .values(not_listening_since=later_start)
        )
    not_listening_digest.run(migrated)
    [new] = _digests(owner, "open")
    # Every away instance is listed, the silenced one too, so the owner sees the whole set.
    assert new["title"] == "2 of your agent instances are not listening"
    assert f"({later.instance})" in new["summary"] and f"({known.instance})" in new["summary"]


@pytest.mark.parametrize("mode", ["bell", "off"])
def test_leaving_inbox_withdraws_the_digest_at_the_patch(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine, mode: str
) -> None:
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    changed = owner.patch("/me/notification-settings", {"not_listening": {"mode": mode}})
    assert changed.status_code == 200, changed.text
    assert [d["status"] for d in _digests(owner)] == ["withdrawn"]  # at the PATCH
    not_listening_digest.run(migrated)
    assert _digests(owner, "open") == []


def test_a_new_owner_hears_of_the_instance_at_the_next_hour(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests import factory

    owner = inbox_owner
    agent = _agent(make_client, owner)
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    heir = factory.human(migrated, "heir")
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile).where(t.agent_profile.c.id == agent.id).values(owner_id=heir)
        )
    not_listening_digest.run(migrated)
    assert [d["status"] for d in _digests(owner)] == ["withdrawn"]
    with migrated.connect() as conn:
        theirs = conn.execute(
            select(t.request.c.status).where(
                t.request.c.to_human == heir, t.request.c.project_id.is_(None)
            )
        ).all()
    assert [r.status for r in theirs] == ["open"]


# --- stalled holders (§5.3: an instance that holds cards and has stopped calling) ---


def _holding(owner: flow.Human, agent: flow.Agent) -> str:
    """The agent claims a fresh card; returns its id."""
    from tests.test_tasks import task

    card = task(owner)
    claimed = agent.post(f"{BASE}/tasks/{card['id']}/claim", {})
    assert claimed.status_code == 200, claimed.text
    return str(card["id"])


def _silent(engine: Engine, agent: flow.Agent, ago: timedelta) -> None:
    """The agent's last call was `ago` back: its latest session's `last_seen_at`."""
    with engine.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == agent.credential_id)
            .values(last_seen_at=clock.now() - ago)
        )


def test_only_the_latest_session_is_read_however_long_the_history(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The bell reads holders live: the ended sessions before the latest are never fetched,
    and an ended older one does not make a live holder `session_ended`."""
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _holding(owner, agent)
    _silent(migrated, agent, timedelta(hours=2))
    with migrated.begin() as conn:
        latest = conn.execute(
            select(t.agent_session).where(t.agent_session.c.credential_id == agent.credential_id)
        ).one()
        conn.execute(
            insert(t.agent_session),
            [
                {
                    **{k: v for k, v in latest._mapping.items() if k != "id"},
                    "id": f"ses-old{n:05d}",
                    "live": None,
                    "started_at": latest.started_at - timedelta(days=1, minutes=n),
                    "ended_at": latest.started_at - timedelta(days=1),
                    "not_listening_seq": None,
                    "not_listening_since": None,
                    "not_listening_request_id": None,
                }
                for n in range(200)
            ],
        )
        rows = not_listening_digest._latest_sessions(conn, {agent.credential_id})
    assert [r.id for r in rows] == [latest.id]
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert digest["summary"].partition("\n\n")[0].endswith(", silent")


def test_the_latest_session_lookup_reads_along_the_credential_start_index(
    migrated: Engine,
) -> None:
    """The plan, not only the rows: each credential's latest start comes from the index on
    (credential, start), never from a scan per candidate session (SQLite's plan; the index
    itself is in the schema for every database)."""
    if migrated.dialect.name != "sqlite":
        pytest.skip("the plan check reads SQLite's EXPLAIN QUERY PLAN")
    with migrated.connect() as conn:
        s = t.agent_session
        query = (
            select(s.c.credential_id, func.max(s.c.started_at))
            .where(s.c.credential_id.in_(["crd-a", "crd-b"]))
            .group_by(s.c.credential_id)
        )
        compiled = query.compile(migrated, compile_kwargs={"literal_binds": True})
        plan = " ".join(
            str(row[-1]) for row in conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled}")
        )
    assert "ix_agent_session_credential_started" in plan, plan


def test_a_stalled_holder_is_listed_with_its_cards_and_reason(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner = inbox_owner
    agent = _agent(make_client, owner)
    card = _holding(owner, agent)
    _silent(migrated, agent, timedelta(minutes=30))  # under the threshold
    not_listening_digest.run(migrated)
    assert _digests(owner) == []
    _silent(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert digest["title"] == "1 of your agent instances are away"
    line, _, advice = digest["summary"].partition("\n\n")
    assert f"({agent.instance}) in maintainer/maity holds {card}, last seen " in line
    assert line.endswith(" (UTC), silent")
    assert advice == not_listening_digest.HOLDER_ADVICE


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_a_closed_card_makes_no_holder(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine, status: str
) -> None:
    """A closed card keeps `claim_holder` and `claim_instance`; it is held by nobody."""
    owner = inbox_owner
    agent = _agent(make_client, owner)
    card = _holding(owner, agent)
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card).values(status=status))
    _silent(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert _digests(owner) == []


def test_an_instance_both_away_and_holding_is_listed_once_as_a_stalled_holder(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _holding(owner, agent)
    _silent(migrated, agent, timedelta(hours=2))
    _episode(migrated, agent, timedelta(hours=2))
    other = _agent(make_client, owner)
    _episode(migrated, other, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert digest["title"] == "2 of your agent instances are away"
    shown, _, advice = digest["summary"].partition("\n\n")
    first, second = shown.splitlines()
    assert f"({other.instance})" in first and ", since " in first  # episodes first
    assert f"({agent.instance})" in second and second.endswith(", not_listening")
    assert advice == f"{not_listening_digest.ADVICE} {not_listening_digest.HOLDER_ADVICE}"


def test_a_revoked_holder_is_listed_as_session_ended(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _holding(owner, agent)
    _silent(migrated, agent, timedelta(hours=2))
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(revoked_at=clock.now())
        )
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert digest["summary"].partition("\n\n")[0].endswith(", session_ended")


@pytest.mark.parametrize("on", ["membership", "credential"])
@pytest.mark.parametrize("by_itself", [True, False])
def test_a_pause_by_someone_else_leaves_a_holder_out_its_own_does_not(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine, by_itself: bool, on: str
) -> None:
    owner = inbox_owner
    agent = _agent(make_client, owner)
    _holding(owner, agent)
    _silent(migrated, agent, timedelta(hours=2))
    paused = {"paused_since": clock.now(), "paused_by": agent.id if by_itself else owner.id}
    with migrated.begin() as conn:
        if on == "membership":
            conn.execute(
                update(t.membership).where(t.membership.c.agent_id == agent.id).values(**paused)
            )
        else:
            conn.execute(
                update(t.credential)
                .where(t.credential.c.id == agent.credential_id)
                .values(**paused)
            )
    not_listening_digest.run(migrated)
    found = _digests(owner)
    if by_itself:
        [digest] = found
        assert digest["summary"].partition("\n\n")[0].endswith(", paused")
    else:
        assert found == []


def test_seen_silences_a_holder_until_it_calls_moving_its_cards_asks_nothing(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Rule 1: no call since a request the owner answered showed it, whatever its kind turns
    into; once it called, a new stop is new (§5.3, the table)."""
    owner = inbox_owner
    agent = _agent(make_client, owner)
    card = _holding(owner, agent)
    _silent(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert owner.post(f"/requests/{digest['id']}/answer", {"reply_id": "seen"}).status_code == 200
    with migrated.begin() as conn:  # its card moved, the move starts an episode, no call
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card)
            .values(claim_holder=None, claim_instance=None, claim_session_id=None)
        )
    _episode(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert _digests(owner, "open") == []
    _episode(migrated, agent, None)
    _holding(owner, agent)  # it calls (the claim), works, and stops again
    _silent(migrated, agent, timedelta(hours=1, minutes=30))
    not_listening_digest.run(migrated)
    [again] = _digests(owner, "open")
    assert again["title"] == "1 of your agent instances are away"


def test_seen_is_the_answering_owners_a_new_owner_hears_of_it(
    inbox_owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests import factory

    owner = inbox_owner
    agent = _agent(make_client, owner)
    _holding(owner, agent)
    _silent(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    [digest] = _digests(owner)
    assert owner.post(f"/requests/{digest['id']}/answer", {"reply_id": "seen"}).status_code == 200
    with migrated.connect() as conn:
        [record] = conn.execute(select(t.not_listening_seen)).all()
    assert (record.human_id, record.instance) == (owner.id, agent.instance)
    heir = factory.human(migrated, "heir")
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile).where(t.agent_profile.c.id == agent.id).values(owner_id=heir)
        )
    not_listening_digest.run(migrated)
    with migrated.connect() as conn:
        theirs = conn.execute(
            select(t.request.c.status).where(
                t.request.c.to_human == heir, t.request.c.project_id.is_(None)
            )
        ).all()
    assert [r.status for r in theirs] == ["open"]


def test_the_bell_counts_holders_and_takes_the_requests_title(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = _agent(make_client, owner)
    _holding(owner, agent)
    _silent(migrated, agent, timedelta(hours=2))
    not_listening_digest.run(migrated)
    assert _records(migrated, owner) == [{"instances": 1, "holding": 1}]
    [item] = _bell(owner)
    assert item["title"] == "1 of your agent instances are away"
