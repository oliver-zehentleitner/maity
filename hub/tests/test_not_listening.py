"""docs/api.md §5.3 "Not listening": an episode starts 10 minutes after an event waits
and the session neither called for events nor resumed; it ends when the cursor reaches
the waiting event, with `member_not_listening` at both ends and one notice to the
profile's owner, withdrawn at the end. Paused, unavailable and ended sessions are never
not listening."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, events, not_listening
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"


class Setup:
    def __init__(self, owner: flow.Human, agent: flow.Agent, engine: Engine) -> None:
        self.owner, self.agent, self.engine = owner, agent, engine
        self.now = clock.now()

    def at(self, minutes: float) -> None:
        moment = self.now + timedelta(minutes=minutes)
        clock.set_source(lambda: moment)

    def sweep(self) -> None:
        not_listening.sweep(self.engine)

    def session(self) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(
                select(t.agent_session).where(
                    t.agent_session.c.credential_id == self.agent.credential_id,
                    t.agent_session.c.live.is_(True),
                )
            ).one()

    def events(self) -> list[Any]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    select(t.event)
                    .where(t.event.c.kind == "member_not_listening")
                    .order_by(t.event.c.seq)
                )
            )

    def notices(self, status: str = "all") -> list[dict[str, Any]]:
        items = self.owner.get("/requests", params={"status": status}).json()["items"]
        return [r for r in items if r["filed_by"] == "hub"]

    def message(self) -> None:
        response = self.owner.post(
            f"{BASE}/conversations/{self.agent.id}/messages", {"body": "are you there?"}
        )
        assert response.status_code == 201, response.text


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, role="member")
    s = Setup(owner, agent, migrated)
    clock.set_source(lambda: s.now)
    assert agent.resume().status_code == 200
    return s


def _cursor(s: Setup) -> int:
    return int(s.agent.get(f"{BASE}/events", params={"after": 0, "wait": 0}).json()["cursor"])


def test_an_event_unread_for_ten_minutes_starts_an_episode(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(9)
    s.sweep()
    assert s.session().not_listening_since is None and s.events() == []
    s.at(11)
    s.sweep()
    session = s.session()
    assert session.not_listening_since is not None
    [started] = s.events()
    payload = started.payload
    assert (payload["member_id"], payload["session_id"], payload["ended"]) == (
        s.agent.id,
        session.id,
        False,
    )
    assert payload["instance"] == s.agent.instance
    assert s.notices() == []  # no request per episode: the owner hears through the digest
    # The instance view says since when.
    view = s.owner.get(f"{BASE}/members/{s.agent.id}").json()
    assert view["instances"][0]["session"]["not_listening_since"] is not None
    # The member view's session does not carry it (§6.2).
    assert "not_listening_since" not in (view.get("session") or {})
    # Checked again, nothing new: one episode.
    s.at(13)
    s.sweep()
    assert len(s.events()) == 1


def test_reading_the_waiting_event_ends_the_episode(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(11)
    s.sweep()
    # A call that acknowledges nothing does not end it.
    s.agent.get(f"{BASE}/events", params={"after": "latest", "wait": 0})
    s.sweep()
    assert s.session().not_listening_since is not None
    cursor = _cursor(s)
    s.agent.get(f"{BASE}/events", params={"after": cursor, "wait": 0})
    s.sweep()
    assert s.session().not_listening_since is None
    started, ended = s.events()
    assert ended.payload["ended"] is True and ended.payload["since"] == started.payload["since"]


def test_a_session_that_called_for_events_lately_is_listening(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(8)
    s.agent.get(f"{BASE}/events", params={"after": "latest", "wait": 0})
    s.at(11)
    s.sweep()  # the event is 11 minutes old, but the last call is 3 minutes ago
    assert s.session().not_listening_since is None and s.events() == []


def test_a_resume_starts_the_ten_minutes_again(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(8)
    assert s.agent.resume().status_code == 200
    s.at(11)
    s.sweep()  # the event is 11 minutes old, but the resume is 3 minutes ago
    assert s.session().not_listening_since is None and s.events() == []
    s.at(19)
    s.sweep()  # 11 minutes after the resume
    assert s.session().not_listening_since == s.now + timedelta(minutes=18)


def test_the_cursor_a_resume_sends_counts_as_acknowledged(setup: Setup) -> None:
    s = setup
    s.message()
    cursor = _cursor(s)
    s.at(1)
    assert s.agent.resume(cursor=cursor).status_code == 200
    assert s.session().acknowledged_seq == cursor
    s.at(30)
    s.sweep()
    assert s.session().not_listening_since is None and s.events() == []


def test_a_resume_without_a_cursor_leaves_the_events_above_the_old_one_waiting(
    setup: Setup,
) -> None:
    """The new session starts at the old one's acknowledged cursor, and the events its
    packet delivers are acknowledged only by a later call for events. A session that
    works from the packet and never calls again is not listening ten minutes after its
    resume, which §5.3 accepts: the hub cannot tell "received and busy" from "never saw
    it"."""
    s = setup
    s.message()
    s.at(1)
    assert s.agent.resume().status_code == 200
    s.at(12)
    s.sweep()
    assert s.session().not_listening_since == s.now + timedelta(minutes=11)
    [started] = s.events()
    assert started.payload["ended"] is False


def test_a_paused_agent_is_never_not_listening(setup: Setup) -> None:
    s = setup
    s.message()
    response = s.owner.patch(f"{BASE}/members/{s.agent.id}", {"paused": {"reason": "later"}})
    assert response.status_code == 200, response.text
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is None and s.notices() == []


def test_an_unavailable_agent_is_never_not_listening(setup: Setup) -> None:
    s = setup
    s.message()
    with s.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == s.agent.id)
            .values(availability_state="rate_limited")
        )
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is None and s.notices() == []


def test_a_pause_during_an_episode_ends_it(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(11)
    s.sweep()
    s.owner.patch(f"{BASE}/members/{s.agent.id}", {"paused": {"reason": "later"}})
    s.sweep()
    assert s.session().not_listening_since is None
    assert [e.payload["ended"] for e in s.events()] == [False, True]


def test_an_ended_session_ends_its_episode_and_a_new_one_starts_clean(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(11)
    s.sweep()
    first = s.session().id
    assert s.agent.resume().status_code == 200  # a new session; the old one ends
    s.sweep()
    with s.engine.connect() as conn:
        old = conn.execute(select(t.agent_session).where(t.agent_session.c.id == first)).one()
    assert old.not_listening_since is None
    assert [e.payload["ended"] for e in s.events()] == [False, True]


def test_a_later_episode_of_the_same_session_counts_again(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(11)
    s.sweep()
    s.agent.get(f"{BASE}/events", params={"after": _cursor(s), "wait": 0})
    s.sweep()  # the first episode ends
    s.message()
    s.at(30)
    s.sweep()
    assert len([e for e in s.events() if not e.payload["ended"]]) == 2


def test_the_start_wakes_the_member_it_reports_to_and_the_end_nobody(setup: Setup) -> None:
    from maity_hub import events

    s = setup
    with s.engine.begin() as conn:  # the agent reports to its owner: a boss to route to
        boss = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == s.owner.id)
        ).scalar_one()
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == s.agent.id)
            .values(reports_to=boss)
        )
    s.message()
    s.at(11)
    s.sweep()
    s.agent.get(f"{BASE}/events", params={"after": _cursor(s), "wait": 0})
    s.sweep()
    started, ended = s.events()
    # With a boss the admins still read it (`admins_always`, unlike `holder_stalled`).
    assert started.audience == [f"member:{s.owner.id}", "trust:admin"]
    with s.engine.connect() as conn:
        reader = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == s.agent.id)
        ).one()
    # The agent itself is not in the audience as reports-to: not woken by its own episode.
    assert not events.wakes(ended, reader, s.agent.id)


def _supervise(s: Setup) -> None:
    with s.engine.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == s.agent.credential_id)
            .values(supervisor="maity-runner/0.1.0")
        )


def _place(s: Setup, make_client: ClientFactory) -> str:
    """An active placement on a paired runner that names the agent's credential, as the
    pickup sets it (§15.9)."""
    from tests.test_runner_stream import attach, hello
    from tests.test_runners import paired

    repository = {"url": "https://github.com/oliver-zehentleitner/maity"}
    patched = s.owner.patch(BASE, {"repository": repository})
    assert patched.status_code == 200, patched.text
    runner = paired(make_client, s.owner)
    attach(s.owner, runner)
    assert hello(make_client(), runner).status_code == 200
    response = s.owner.post(
        f"{BASE}/placements",
        {"agent": {"id": s.agent.id}, "runner": runner.id, "harness": "claude-code"},
    )
    assert response.status_code == 201, response.text
    placement_id: str = response.json()["id"]
    with s.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == placement_id)
            .values(credential_id=s.agent.credential_id)
        )
    return placement_id


def test_a_supervised_session_an_active_placement_names_is_never_not_listening(
    setup: Setup, make_client: ClientFactory
) -> None:
    s = setup
    _place(s, make_client)
    _supervise(s)
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is None and s.events() == []


def test_a_supervised_session_no_placement_names_is_not_listening(setup: Setup) -> None:
    """Local mode (§15.13): a runner supervises the session, no placement names its
    credential, and nobody reports its stop but this check (§5.3)."""
    s = setup
    _supervise(s)
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is not None
    [started] = s.events()
    assert started.payload["ended"] is False


def test_a_closed_placement_no_longer_leaves_a_supervised_session_out(
    setup: Setup, make_client: ClientFactory
) -> None:
    s = setup
    placement_id = _place(s, make_client)
    _supervise(s)
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is None
    # Closed at once: the runner never acted on it (§15.5).
    closed = s.owner.delete(f"{BASE}/placements/{placement_id}")
    assert closed.status_code == 200 and closed.json()["active"] is False, closed.text
    s.at(12)
    s.sweep()
    assert s.session().not_listening_since is not None


def test_a_placement_naming_the_credential_ends_the_episode(
    setup: Setup, make_client: ClientFactory
) -> None:
    """An exclusion that begins ends the episode (§5.3)."""
    s = setup
    _supervise(s)
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is not None
    _place(s, make_client)
    s.at(12)
    s.sweep()
    assert s.session().not_listening_since is None
    started, ended = s.events()
    assert (started.payload["ended"], ended.payload["ended"]) == (False, True)


def test_a_runner_revoke_under_stop_leaves_a_due_revocation_out(
    setup: Setup, make_client: ClientFactory
) -> None:
    """Under `stop` the placement closes and the credential's revocation is only due; the
    agent may never call again to have it written (§15.3), so it counts as revoked."""
    s = setup
    placement_id = _place(s, make_client)
    _supervise(s)
    policy = {"policy": {"on_runner_revoke": "stop"}, "reason": "the runner's agents"}
    assert s.owner.patch(BASE, policy).status_code == 200
    with s.engine.connect() as conn:
        runner_id = conn.execute(
            select(t.placement.c.runner_id).where(t.placement.c.id == placement_id)
        ).scalar_one()
    revoked = s.owner.post(f"/runners/{runner_id}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["on_runner_revoke"][0]["stopped"] == [placement_id]
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is None and s.events() == []
    with s.engine.connect() as conn:
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == s.agent.credential_id)
        ).one()
    assert credential.revoked_at is None and credential.revoke_due_at is not None


def test_the_start_wakes_only_the_instances_the_bosss_team_rule_chose() -> None:
    """A reports-to agent whose team wakes its lead only: the start wakes the lead,
    not a sibling; the end wakes neither (§5.3, §8.2 "Team wake")."""
    from types import SimpleNamespace

    from maity_hub import events

    boss = SimpleNamespace(
        id=7, agent_id="agt-boss", role="member", lead_instance="lead", isolated_since=None
    )
    start = SimpleNamespace(
        kind="member_not_listening",
        payload={"ended": False},
        audience=["member:agt-boss", "trust:admin"],
        wakes={"agt-boss": ["lead"]},
        actor_membership=None,
        actor_credential_id=None,
        conversation_id=None,
    )
    assert events.wakes(start, boss, "agt-boss", instance="lead")
    assert not events.wakes(start, boss, "agt-boss", instance="other")
    end = SimpleNamespace(**{**vars(start), "payload": {"ended": True}})
    assert not events.wakes(end, boss, "agt-boss", instance="lead")
    admin = SimpleNamespace(
        id=8, agent_id="agt-admin", role="admin", lead_instance=None, isolated_since=None
    )
    assert not events.wakes(start, admin, "agt-admin", instance="x")  # trust:admin only reads


def test_the_membership_is_read_again_under_the_projects_lock(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whoever held the lock may have paused the agent meanwhile: the check sees that
    and starts no episode."""
    s = setup
    s.message()
    s.at(11)
    real = events.lock_project

    def paused_while_waiting(conn: Any, project_id: str) -> Any:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == s.agent.id)
            .values(paused_since=clock.now(), paused_reason="meanwhile")
        )
        return real(conn, project_id)

    monkeypatch.setattr(not_listening, "lock_project", paused_while_waiting)
    s.sweep()
    assert s.session().not_listening_since is None and s.events() == [] and s.notices() == []


@pytest.mark.parametrize("mode", ["inbox", "bell", "off"])
def test_an_episode_files_no_request_in_any_mode(setup: Setup, mode: str) -> None:
    """§5.3: the episode feeds the owner's digest and files no request of its own; the
    member it reports to hears of it whatever the owner's mode."""
    s = setup
    changed = s.owner.patch("/me/notification-settings", {"not_listening": {"mode": mode}})
    assert changed.status_code == 200, changed.text
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is not None
    assert len(s.events()) == 1
    assert s.notices() == []


def test_a_request_per_episode_from_before_is_withdrawn_at_the_first_digest_hour(
    setup: Setup,
) -> None:
    """§5.3: when the digest replaces the requests per episode, the hub withdraws every one
    still open at the first digest hour; the episode itself goes on."""
    from maity_hub import not_listening_digest
    from maity_hub.events import transaction
    from maity_hub.routes.requests import file_hub_notice

    s = setup
    s.message()
    s.at(11)
    s.sweep()
    session = s.session()
    with transaction(s.engine) as conn:  # as the hub filed it before the digest
        member = conn.execute(
            select(t.membership).where(t.membership.c.id == session.membership_id)
        ).one()
        old = file_hub_notice(
            conn, member.project_id, member.id, s.agent.id, "agent (x) is not listening", "-"
        )
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.id == session.id)
            .values(not_listening_request_id=old)
        )
    assert [n["status"] for n in s.notices()] == ["open"]
    s.at(200)
    not_listening_digest.run(s.engine)
    statuses = {n["id"]: n["status"] for n in s.notices()}
    assert statuses[old] == "withdrawn"
    assert s.session().not_listening_since is not None
    assert s.session().not_listening_request_id is None
