"""docs/api.md §6.17, "One instance in several projects": what belongs to an instance in one
project lives on its attachment there (`instance_attachment`), and a session's position and
not-listening episode on its row for that project (`agent_session_project`). Each test
attaches one instance to two projects, A and B, acts in one and finds the other untouched.

Until hub PR B a credential authenticates in its oldest attachment (QA6), here A: the agent's
own calls act in A, a human's act in the project of the route."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from maity_hub import (
    clock,
    commitment,
    cross_chats,
    events,
    instances,
    landing_stats,
    moderation,
    not_listening,
)
from maity_hub import tables as t
from maity_hub.app import create_app
from maity_hub.config import Settings
from maity_hub.db import migrate
from maity_hub.errors import ApiError
from tests import factory, flow
from tests.conftest import ClientFactory

A = "/projects/maintainer/alpha"
B = "/projects/maintainer/beta"


class World:
    """An owner with projects A and B, and one agent instance attached to both, resumed."""

    def __init__(self, make_client: ClientFactory, engine: Engine) -> None:
        self.engine = engine
        self.owner = flow.human(make_client, engine)
        self.alpha = flow.project(self.owner, "alpha")["id"]
        self.beta = flow.project(self.owner, "beta")["id"]
        self.agent = flow.agent(make_client, self.owner, "alpha")
        with engine.connect() as conn:
            self.in_a = conn.execute(
                select(t.membership.c.id).where(
                    t.membership.c.project_id == self.alpha,
                    t.membership.c.agent_id == self.agent.id,
                )
            ).scalar_one()
        self.in_b = factory.attach(engine, self.agent, self.beta)
        resumed = self.agent.resume()
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["project"]["id"] == self.alpha  # the oldest attachment (QA6)

    def attachment(self, membership_id: int) -> Any:
        a = t.instance_attachment
        with self.engine.connect() as conn:
            return conn.execute(
                select(a).where(
                    a.c.credential_id == self.agent.credential_id,
                    a.c.membership_id == membership_id,
                )
            ).one()

    def position(self, membership_id: int) -> Any:
        """The live session's row in the project of `membership_id`."""
        p = t.agent_session_project
        with self.engine.connect() as conn:
            return conn.execute(
                select(p)
                .join(t.agent_session, t.agent_session.c.id == p.c.session_id)
                .where(
                    t.agent_session.c.credential_id == self.agent.credential_id,
                    t.agent_session.c.live.is_(True),
                    p.c.membership_id == membership_id,
                )
            ).one()

    def view(self, project: str) -> dict[str, Any]:
        """The agent's one instance view in the member view of `project`."""
        shown = self.owner.get(f"{project}/members/{self.agent.id}")
        assert shown.status_code == 200, shown.text
        [instance] = shown.json()["instances"]
        found: dict[str, Any] = instance
        return found

    def member(self, project: str, body: dict[str, Any]) -> Any:
        response = self.owner.patch(f"{project}/members/{self.agent.id}", body)
        assert response.status_code == 200, response.text
        return response

    def detach(self, membership_id: int, at: datetime | None = None) -> None:
        """End the attachment to `membership_id` by hand: nothing writes `detached_at` yet
        (hub PR D)."""
        with self.engine.begin() as conn:
            conn.execute(
                update(t.instance_attachment)
                .where(instances.attachment_of(self.agent.credential_id, membership_id))
                .values(detached_at=at or clock.now(), detached_reason="detached")
            )

    def events(self, kind: str) -> list[str]:
        """The projects of every event of `kind`, oldest first."""
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    select(t.event.c.project_id)
                    .where(t.event.c.kind == kind)
                    .order_by(t.event.c.seq)
                ).scalars()
            )

    def say(self, project: str, body: str) -> int:
        said = self.owner.post(
            f"{project}/events", {"kind": "message", "type": "notice", "to": "all", "body": body}
        )
        assert said.status_code == 201, said.text
        return int(said.json()["seq"])


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine) -> World:
    return World(make_client, migrated)


def test_a_pause_in_one_project_leaves_the_other_alone(world: World) -> None:
    """1: a human admin pauses the instance in A (PATCH …/members/{id} with `instance`): B's
    row and B's member view stay unpaused; pausing and lifting it in B leaves A's pause."""
    w = world
    w.member(A, {"paused": {"reason": "hold in A", "instance": w.agent.instance}})
    assert w.attachment(w.in_a).paused_reason == "hold in A"
    assert w.attachment(w.in_b).paused_since is None
    assert w.view(A)["paused"]["reason"] == "hold in A"
    assert w.view(B)["paused"] is None and w.view(B)["presence"] != "paused"
    w.member(B, {"paused": {"reason": "hold in B", "instance": w.agent.instance}})
    w.member(B, {"paused": None, "instance": w.agent.instance})
    assert w.attachment(w.in_b).paused_since is None
    kept = w.attachment(w.in_a)
    assert (kept.paused_reason, kept.paused_by) == ("hold in A", w.owner.id)
    assert w.view(A)["paused"]["reason"] == "hold in A"


def test_dormancy_in_one_project_is_not_dormancy_in_the_other(world: World) -> None:
    """2: put to rest in A, the instance is awake in B: its token is not dormant there, B's
    member is not among the dormant ones, and B's instance view shows no `dormant`."""
    w = world
    w.member(A, {"dormant": True, "instance": w.agent.instance})
    token = instances.token(w.agent.id, w.agent.instance)
    with w.engine.connect() as conn:
        assert instances.token_is_dormant(conn, w.alpha, token)
        assert not instances.token_is_dormant(conn, w.beta, token)
        assert instances.dormant_members(conn, [w.in_a, w.in_b]) == {w.in_a}
    assert w.attachment(w.in_a).dormant_since is not None
    assert w.attachment(w.in_b).dormant_since is None
    assert w.view(A)["dormant"]["by"] == w.owner.id
    assert w.view(B)["dormant"] is None


def _ktw(row: Any) -> tuple[Any, ...]:
    return (
        row.ktw_acknowledged_at,
        row.ktw_acknowledged_session,
        row.ktw_acknowledge_by,
        row.ktw_session_id,
        row.ktw_reminded_at,
        row.ktw_request_id,
    )


def test_the_keep_the_why_commitment_is_per_project(world: World) -> None:
    """3: the deadline the resume in A set and the confirmation in A leave B's commitment
    empty; with a deadline outstanding in B only, the worker reminds in B, not in A."""
    w = world
    assert w.attachment(w.in_a).ktw_acknowledge_by is not None  # the resume's, in A
    assert _ktw(w.attachment(w.in_b)) == (None,) * 6
    acked = w.agent.post("/me/keep-the-why/ack")
    assert acked.status_code == 200, acked.text
    assert w.attachment(w.in_a).ktw_acknowledged_at is not None
    assert _ktw(w.attachment(w.in_b)) == (None,) * 6
    session = w.position(w.in_b).session_id
    with w.engine.begin() as conn:
        conn.execute(
            update(t.instance_attachment)
            .where(instances.attachment_of(w.agent.credential_id, w.in_b))
            .values(ktw_acknowledge_by=clock.now() - timedelta(minutes=1), ktw_session_id=session)
        )
    commitment.sweep(w.engine)
    with w.engine.connect() as conn:
        reminders = conn.execute(
            select(t.event).where(t.event.c.kind == "keep_the_why_reminder")
        ).all()
    assert [(r.project_id, r.payload["project"]) for r in reminders] == [
        (w.beta, "maintainer/beta")
    ]
    assert w.attachment(w.in_b).ktw_reminded_at is not None
    assert w.attachment(w.in_a).ktw_reminded_at is None


def test_the_isolation_lift_in_one_project_moves_only_that_position(world: World) -> None:
    """4: lifting the isolation in A moves A's position row to A's head; B's row stays where it
    was, and B never saw the agent isolated."""
    w = world
    in_b = w.position(w.in_b).acknowledged_seq
    isolated = w.owner.post(f"{A}/members/{w.agent.id}/isolate", {"reason": "a rewrite"})
    assert isolated.status_code == 200, isolated.text
    meanwhile = w.say(A, "while you were out")
    lifted = w.owner.delete(f"{A}/members/{w.agent.id}/isolate")
    assert lifted.status_code == 200, lifted.text
    moved = w.position(w.in_a).acknowledged_seq
    assert moved >= meanwhile > in_b  # B's row was below the head A's moved to
    assert w.position(w.in_b).acknowledged_seq == in_b
    shown = w.owner.get(f"{B}/members/{w.agent.id}").json()
    assert shown["isolated"] is None


def test_reading_events_after_n_moves_the_position_of_that_project_only(world: World) -> None:
    """5: `GET …/events?after=N` in A acknowledges up to N on A's row; B's stays."""
    w = world
    in_b = w.position(w.in_b).acknowledged_seq
    seq = w.say(A, "news in A")
    read = w.agent.get(f"{A}/events", params={"after": seq, "wait": 0})
    assert read.status_code == 200, read.text
    assert w.position(w.in_a).acknowledged_seq == seq
    assert w.position(w.in_b).acknowledged_seq == in_b


def test_an_event_waiting_in_one_project_starts_an_episode_there_only(world: World) -> None:
    """6: a message waiting in B for ten minutes starts the not-listening episode on the
    session's row for B; A's row has none."""
    w = world
    start = clock.now()
    clock.set_source(lambda: start)
    said = w.owner.post(f"{B}/conversations/{w.agent.id}/messages", {"body": "are you there?"})
    assert said.status_code == 201, said.text
    clock.set_source(lambda: start + timedelta(minutes=11))
    not_listening.sweep(w.engine)
    assert w.position(w.in_b).not_listening_since is not None
    assert w.position(w.in_a).not_listening_since is None
    with w.engine.connect() as conn:
        started = conn.execute(
            select(t.event.c.project_id).where(t.event.c.kind == "member_not_listening")
        ).scalars()
        assert list(started) == [w.beta]


def test_an_instance_in_two_projects_counts_once_in_each(world: World) -> None:
    """7: `max_instances` and the instance counts see the instance once in A and once in B;
    across the hub it is one instance."""
    w = world
    with w.engine.begin() as conn:
        assert instances.active_count(conn, w.in_a) == 1
        assert instances.active_count(conn, w.in_b) == 1
        b = conn.execute(select(t.membership).where(t.membership.c.id == w.in_b)).one()
        with pytest.raises(ApiError) as refused:  # max_instances 1: no room for another
            instances.refuse_over_quota(conn, b)
        assert refused.value.code == "instance_quota"
        conn.execute(
            update(t.membership).where(t.membership.c.id == w.in_b).values(max_instances=2)
        )
        b = conn.execute(select(t.membership).where(t.membership.c.id == w.in_b)).one()
        instances.refuse_over_quota(conn, b)  # counted once, so one more fits under 2
        landing_stats.reset()
        assert landing_stats.compute(conn)["instances"] == 1
    for project in (A, B):
        shown = w.owner.get(f"{project}/members/{w.agent.id}").json()
        assert [i["id"] for i in shown["instances"]] == [w.agent.instance]


# A detached attachment (§6.17, "Detaching") keeps its row: every reader that speaks for the
# instance in a project reads only the live ones. Nothing writes `detached_at` yet (hub PR D),
# so these tests set it by hand.


def test_a_leak_is_told_only_where_the_instance_is_attached_now(world: World) -> None:
    """A leaked credential is revoked, and `credential_revoked` and `credential_in_payload`
    are written in A; B, which the instance left, hears nothing."""
    w = world
    w.detach(w.in_b)
    leaked = w.owner.post(
        f"{A}/events",
        {"kind": "message", "type": "notice", "to": "all", "body": f"oops {w.agent.credential}"},
    )
    assert leaked.status_code == 400, leaked.text
    with w.engine.connect() as conn:
        reason = conn.execute(
            select(t.credential.c.revoked_reason).where(t.credential.c.id == w.agent.credential_id)
        ).scalar_one()
    assert reason == "leaked_in_payload"
    assert w.events("credential_revoked") == [w.alpha]
    assert w.events("credential_in_payload") == [w.alpha]


def test_a_suspension_neither_locks_nor_tells_a_project_the_instance_left(world: World) -> None:
    """The owner's suspension locks A only and writes `credential_revoked` in A only."""
    w = world
    w.detach(w.in_b)
    m = t.membership.c
    agents = select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == w.owner.id)
    own = (m.human_id == w.owner.id) | m.agent_id.in_(agents)
    with events.transaction(w.engine) as conn:
        assert moderation._projects_to_lock(conn, [], own) == [w.alpha]
        moderation.suspend(conn, w.owner.id, "rpt-000000000000")
    assert w.events("credential_revoked") == [w.alpha]


def test_the_commitment_of_a_detached_attachment_ends(world: World) -> None:
    """An overdue deadline on B's attachment, once detached, reminds nobody: the sweep ends
    it as it ends a revoked instance's."""
    w = world
    acked = w.agent.post("/me/keep-the-why/ack")  # A owes nothing
    assert acked.status_code == 200, acked.text
    session = w.position(w.in_b).session_id
    with w.engine.begin() as conn:
        conn.execute(
            update(t.instance_attachment)
            .where(instances.attachment_of(w.agent.credential_id, w.in_b))
            .values(ktw_acknowledge_by=clock.now() - timedelta(minutes=1), ktw_session_id=session)
        )
    w.detach(w.in_b)
    commitment.sweep(w.engine)
    assert w.events("keep_the_why_reminder") == []
    ended = w.attachment(w.in_b)
    assert (ended.ktw_acknowledge_by, ended.ktw_reminded_at) == (None, None)


def test_a_detached_attachment_starts_no_episode(world: World) -> None:
    """A message waiting in B for ten minutes starts no not-listening episode once the
    instance left B."""
    w = world
    w.detach(w.in_b)
    start = clock.now()
    clock.set_source(lambda: start)
    said = w.owner.post(f"{B}/conversations/{w.agent.id}/messages", {"body": "are you there?"})
    assert said.status_code == 201, said.text
    clock.set_source(lambda: start + timedelta(minutes=11))
    not_listening.sweep(w.engine)
    assert w.position(w.in_b).not_listening_since is None
    assert w.events("member_not_listening") == []


def test_the_credentials_list_shows_a_detached_instance_for_30_days(world: World) -> None:
    """§10: B lists the credential detached from it for 30 days, after the live ones, as
    it lists a revoked one; then no more. A lists it as active throughout."""
    w = world

    def listed(project: str) -> list[str]:
        found = w.owner.get(f"{project}/members/{w.agent.id}/credentials")
        assert found.status_code == 200, found.text
        return [c["id"] for c in found.json()["items"]]

    w.detach(w.in_b)
    assert listed(B) == [w.agent.credential_id]
    w.detach(w.in_b, clock.now() - timedelta(days=31))
    assert listed(B) == []
    assert listed(A) == [w.agent.credential_id]


def test_a_project_the_instance_left_cannot_revoke_it(world: World) -> None:
    """B's admin revokes nothing of an instance detached from B: `not_found`, and the
    credential stays live in A."""
    w = world
    w.detach(w.in_b)
    refused = w.owner.post(f"{B}/credentials/{w.agent.credential_id}/revoke", {})
    assert refused.status_code == 404, refused.text
    with w.engine.connect() as conn:
        revoked = conn.execute(
            select(t.credential.c.revoked_at).where(t.credential.c.id == w.agent.credential_id)
        ).scalar_one()
    assert revoked is None
    assert w.events("credential_revoked") == []


def test_a_revocation_clears_the_lead_only_where_the_instance_is_attached(world: World) -> None:
    """The instance leads in A and, left over, in B it was detached from: its revocation
    clears A's lead and tells A; B's row and B's events are untouched."""
    w = world
    m = t.membership
    with w.engine.begin() as conn:
        conn.execute(
            update(m).where(m.c.id.in_([w.in_a, w.in_b])).values(lead_instance=w.agent.instance)
        )
    w.detach(w.in_b)
    told = len(w.events("member_updated"))
    revoked = w.owner.post(f"{A}/credentials/{w.agent.credential_id}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    with w.engine.connect() as conn:
        leads = dict(
            conn.execute(
                select(m.c.id, m.c.lead_instance).where(m.c.id.in_([w.in_a, w.in_b]))
            ).all()
        )
    assert leads == {w.in_a: None, w.in_b: w.agent.instance}
    assert w.events("member_updated")[told:] == [w.alpha]


def test_a_mention_finds_the_instance_where_it_is_attached_now(world: World) -> None:
    """A cross-chat mention's home: the membership the instance is attached to now. Here A
    is the detached one, as A's membership is the older, whose lower id would win the tie
    of `_mention_home` and come first in `_instance_home`; B is picked."""
    w = world
    w.detach(w.in_a)
    with w.engine.connect() as conn:
        assert cross_chats._mention_home(conn, w.agent.id).id == w.in_b
        assert cross_chats._instance_home(conn, w.agent.id, w.agent.instance).id == w.in_b


def test_a_mention_of_an_instance_attached_only_where_it_is_isolated_is_a_profile_mention(
    world: World, make_client: ClientFactory
) -> None:
    """§9.5: the instance is attached now only in A, whose membership is isolated, and was
    in B, detached. The live attachment decides: no instance mention goes to B, the project
    it left; the mention is written as a mention of the profile, in its one non-isolated
    membership."""
    w = world
    flow.project(w.owner, "gamma")
    other = flow.agent(make_client, w.owner, "gamma")  # no project shared: a cross chat
    chat = w.owner.post(
        "/me/cross-chats", {"title": "Across", "participants": [w.agent.id, other.id]}
    )
    assert chat.status_code == 201, chat.text
    handle = next(p["handle"] for p in chat.json()["participants"] if p["member_id"] == w.agent.id)
    w.detach(w.in_b)
    with w.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == w.in_a)
            .values(isolated_since=clock.now(), isolated_reason="hold", isolated_by="hub")
        )
    with w.engine.connect() as conn:
        assert cross_chats._instance_home(conn, w.agent.id, w.agent.instance) is None
    posted = w.owner.post(
        f"/me/cross-chats/{chat.json()['id']}/messages",
        {"body": f"@{handle}#{w.agent.instance} over here"},
    )
    assert posted.status_code == 201, posted.text
    with w.engine.connect() as conn:
        places = conn.execute(
            select(t.event.c.project_id, t.event.c.audience).where(
                t.event.c.kind == "cross_chat_mention"
            )
        ).all()
    assert [(row.project_id, list(row.audience)) for row in places] == [
        (w.beta, [f"member:{w.agent.id}"])
    ]


def test_auth_resolves_the_oldest_attachment_that_is_not_detached(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """9 (QA6): with several attachments a credential authenticates in the oldest by
    `attached_at`, then by id; a detached one is skipped. TODO(hub PR B): the route's."""
    owner = flow.human(make_client, migrated)
    alpha = flow.project(owner, "alpha")["id"]
    beta = flow.project(owner, "beta")["id"]
    gamma = flow.project(owner, "gamma")["id"]
    agent = flow.agent(make_client, owner, "alpha")
    a = t.instance_attachment
    with migrated.connect() as conn:
        joined = conn.execute(
            select(a.c.attached_at).where(a.c.credential_id == agent.credential_id)
        ).scalar_one()

    def resolved() -> str:
        me = agent.get("/me")
        assert me.status_code == 200, me.text
        [project] = me.json()["projects"]
        found: str = project["id"]
        return found

    assert resolved() == alpha
    # Attached later, but at the same moment as A: the lower id, A's, decides.
    factory.attach(migrated, agent, gamma, attached_at=joined)
    assert resolved() == alpha
    # Attached later, with an older `attached_at`: the oldest wins, whatever its id.
    in_beta = factory.attach(migrated, agent, beta, attached_at=joined - timedelta(days=1))
    assert resolved() == beta
    # A detached attachment is skipped.
    with migrated.begin() as conn:
        conn.execute(
            update(a)
            .where(a.c.membership_id == in_beta)
            .values(detached_at=clock.now(), detached_reason="detached")
        )
    assert resolved() == alpha


def test_a_single_project_instance_reads_as_before_after_the_migration(
    engine: Engine, settings: Settings
) -> None:
    """8: seeded below 20261121120000_inst_attach, an instance in one project reads the same
    values afterwards: `GET /me`, the resume packet (the handover, `keep_the_why`, `paused`,
    `dormant`, the cursor) and the member view."""
    from tests.test_migrations import _before

    revision = "20261121120000_inst_attach"
    migrate(engine, _before(engine, revision))
    aware = datetime(2026, 11, 21, 9, 30, 0, 250000, tzinfo=UTC)
    then = aware.replace(tzinfo=None)  # the reflected columns store UTC without a zone
    project = factory.project(engine, "alpha", keep_the_why=True)
    with engine.connect() as conn:
        owner = conn.execute(
            select(t.human.c.id).where(t.human.c.handle == "maintainer")
        ).scalar_one()
    factory.membership(engine, project, "owner", human_id=owner)
    old = factory.agent(engine, project, owner, "coder", instance="aaaa", picture=False)
    new = factory.agent(engine, project, owner, "coder", instance="bbbb", picture=False)
    import sqlalchemy as sa

    meta = sa.MetaData()
    credential = sa.Table("credential", meta, autoload_with=engine)
    session = sa.Table("agent_session", meta, autoload_with=engine)
    with engine.begin() as conn:
        # bbbb replaced aaaa in the same membership; aaaa's session read up to 30.
        conn.execute(
            update(credential)
            .where(credential.c.id == new.credential_id)
            .values(
                membership_id=old.membership_id,
                replaces="aaaa",
                exchange_seq=12,
                first_after=40,
                first_cursor=10_000,
                paused_reason="owner's hold",
                paused_since=then,
                paused_by=owner,
                dormant_since=then,
                dormant_by=owner,
                ktw_acknowledge_by=then + timedelta(days=400),
                ktw_session_id=new.session_id,
            )
        )
        conn.execute(
            update(credential)
            .where(credential.c.id == old.credential_id)
            .values(revoked_at=then, revoked_reason="replaced")
        )
        conn.execute(
            update(session)
            .where(session.c.id == old.session_id)
            .values(acknowledged_seq=30, live=None, ended_at=then)
        )
        conn.execute(
            update(session)
            .where(session.c.id == new.session_id)
            .values(membership_id=old.membership_id, acknowledged_seq=55)
        )
    migrate(engine)
    client = TestClient(
        create_app(settings, engine), base_url="https://hub.example", client=("203.0.113.7", 50000)
    )
    with client:
        agent = flow.Agent(client, new.value, new.credential_id, old.agent_id, "bbbb")
        me = agent.get("/me")
        assert me.status_code == 200, me.text
        assert me.json()["member"]["id"] == old.agent_id
        assert [p["id"] for p in me.json()["projects"]] == [project]
        resumed = agent.resume()
        assert resumed.status_code == 200, resumed.text
        packet = resumed.json()
        since = clock.rfc3339(aware)
        paused = {"reason": "owner's hold", "since": since, "by": owner}
        assert packet["membership"]["paused"] == paused
        assert packet["me"]["dormant"] == {"since": since, "by": owner}
        assert packet["events"]["after"] == 55  # where its session left off
        assert packet["handover"]["from"] == ["aaaa"]
        assert packet["handover"]["after"] == 30  # where aaaa's session left off
        block = packet["keep_the_why"]
        assert block["commitment"] == "required" and block["acknowledged_at"] is None
        assert block["acknowledge_by"] == clock.rfc3339(aware + timedelta(days=400))
        logged_in = factory.login(client, owner, engine=engine)
        assert logged_in.status_code == 200, logged_in.text
        view = client.get(f"/api/v1/projects/maintainer/alpha/members/{old.agent_id}").json()
        [instance] = view["instances"]
        assert (instance["id"], instance["replaces"]) == ("bbbb", "aaaa")
        assert instance["paused"] == paused
        assert instance["dormant"] == {"since": since, "by": owner}
        assert instance["keep_the_why_acknowledge_by"] == block["acknowledge_by"]
