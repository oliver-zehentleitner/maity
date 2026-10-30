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
    [notice] = s.notices()
    assert notice["title"].endswith(f" ({s.agent.instance}) is not listening")
    assert (notice["class"], notice["status"], notice["personal"]) == ("info", "open", True)
    assert [o["id"] for o in notice["options"]] == ["seen"]
    assert notice["summary"].startswith(f"Session {session.id} has not called the events")
    # The instance view says since when.
    view = s.owner.get(f"{BASE}/members/{s.agent.id}").json()
    assert view["instances"][0]["session"]["not_listening_since"] is not None
    # The member view's session does not carry it (§6.2).
    assert "not_listening_since" not in (view.get("session") or {})
    # Checked again, nothing new: one episode, one notice.
    s.at(13)
    s.sweep()
    assert len(s.events()) == 1 and len(s.notices()) == 1


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
    [notice] = s.notices()
    assert notice["status"] == "withdrawn"


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
    [notice] = s.notices()
    assert notice["status"] == "withdrawn"


def test_at_most_one_open_notice_per_instance(setup: Setup) -> None:
    s = setup
    s.message()
    s.at(11)
    s.sweep()
    s.agent.get(f"{BASE}/events", params={"after": _cursor(s), "wait": 0})
    s.sweep()  # the first episode ends
    s.message()
    s.at(30)
    s.sweep()  # a later episode files again
    statuses = sorted(n["status"] for n in s.notices())
    assert statuses == ["open", "withdrawn"]
    assert len([e for e in s.events() if not e.payload["ended"]]) == 2


def test_the_start_wakes_the_member_it_reports_to_and_the_end_nobody(setup: Setup) -> None:
    from maity_hub import events

    s = setup
    s.message()
    s.at(11)
    s.sweep()
    s.agent.get(f"{BASE}/events", params={"after": _cursor(s), "wait": 0})
    s.sweep()
    started, ended = s.events()
    assert started.audience[-1].startswith("member:") or "trust:admin" in started.audience
    with s.engine.connect() as conn:
        reader = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == s.agent.id)
        ).one()
    # The agent itself is not in the audience as reports-to: not woken by its own episode.
    assert not events.wakes(ended, reader, s.agent.id)


def test_a_supervised_session_is_never_not_listening(setup: Setup) -> None:
    s = setup
    with s.engine.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == s.agent.credential_id)
            .values(supervisor="maity-runner/0.1.0")
        )
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is None and s.notices() == []


def test_a_new_owner_gets_the_notice_instead(setup: Setup) -> None:
    """§5.3, as for the Keep the Why commitment (§6.23): the notice to the old owner is
    withdrawn and one is filed to the new owner."""
    from tests import factory

    s = setup
    s.message()
    s.at(11)
    s.sweep()
    heir = factory.human(s.engine, "heir")
    with s.engine.begin() as conn:
        conn.execute(
            update(t.agent_profile).where(t.agent_profile.c.id == s.agent.id).values(owner_id=heir)
        )
    s.sweep()
    with s.engine.connect() as conn:
        rows = conn.execute(
            select(t.request.c.status, t.request.c.to_human)
            .where(t.request.c.filed_by == "hub")
            .order_by(t.request.c.created_at, t.request.c.id)
        ).all()
    assert sorted((r.status, r.to_human == heir) for r in rows) == [
        ("open", True),
        ("withdrawn", False),
    ]
    assert s.session().not_listening_request_id is not None


def test_the_start_wakes_only_the_instances_the_bosss_team_rule_chose() -> None:
    """A reports-to agent whose team wakes its lead only: the start wakes the lead,
    not a sibling; the end wakes neither (§5.3, §8.2 "Team wake")."""
    from types import SimpleNamespace

    from maity_hub import events

    boss = SimpleNamespace(id=7, agent_id="agt-boss", role="member", lead_instance="lead")
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
    admin = SimpleNamespace(id=8, agent_id="agt-admin", role="admin", lead_instance=None)
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


@pytest.mark.parametrize(("mode", "requests"), [("inbox", 1), ("bell", 0), ("off", 0)])
def test_only_an_owner_under_inbox_gets_a_request_per_episode(
    setup: Setup, mode: str, requests: int
) -> None:
    """§5.3, §18.4: `bell` hears of it through the digest's bell item, `off` not at all;
    until the digest request comes, `inbox` keeps one request per episode."""
    s = setup
    changed = s.owner.patch("/me/notification-settings", {"not_listening": {"mode": mode}})
    assert changed.status_code == 200, changed.text
    s.message()
    s.at(11)
    s.sweep()
    assert s.session().not_listening_since is not None  # the episode starts in every mode
    assert len(s.events()) == 1  # and the member it reports to is told, whatever the mode
    assert len(s.notices()) == requests
