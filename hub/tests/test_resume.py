"""docs/api.md §5.2: the resume packet and sessions."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PACKET = {
    "server_time",
    "api_version",
    "hub_version",
    "session",
    "hints",
    "me",
    "membership",
    "project",
    "rules",
    "areas",
    "keep_the_why",
    "claims",
    "assigned",
    "requests",
    "events",
    "peers",
    "operations",
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", keep_the_why=True)
    return owner


def test_the_packet_has_every_part_of_the_contract(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(
        make_client,
        owner,
        agent={"handle": "agent-b", "display_name": "Agent B"},
        role="member",
        areas=["hub/"],
        reports_to=owner.id,
    )
    response = agent.resume(harness="Claude Code", harness_version="2.1", model="claude-opus-5-5")
    assert response.status_code == 200
    packet = response.json()
    assert set(packet) == PACKET
    assert packet["api_version"] == "v1"
    assert set(packet["session"]) == {"id", "started_at", "harness", "model", "client"}
    assert packet["hints"] == {"wait_timeout": 540}  # Claude Code
    assert packet["me"]["owner"] == {"id": owner.id, "handle": "maintainer"}
    assert packet["membership"] == {
        "role": "member",
        "reports_to": owner.id,
        "areas": ["hub/"],
        "capabilities": [],
        "scopes": ["project:read", "tasks:write", "requests:ask", "events:post"],
    }
    assert packet["project"]["slug"] == "maity" and packet["project"]["keep_the_why"] is True
    assert packet["keep_the_why"]["enabled"] is True
    assert "keep-the-why" in packet["keep_the_why"]["instruction"]
    assert packet["areas"] == [
        {"path": "/", "owner": owner.id},
        {"path": "hub/", "owner": agent.id},
    ]
    assert packet["requests"] == {
        "mine_open": [],
        "answered_since_cursor": [],
        "to_answer": [],
        "truncated": False,
    }
    assert packet["peers"] == [
        {
            "member_id": owner.id,
            "kind": "human",
            "handle": "maintainer",
            "role": "owner",
            "areas": ["/"],
            "presence": "online",
            "paused": None,
        }
    ]
    assert "GET /projects/maity/members" in packet["operations"]
    assert not any("joins" in op for op in packet["operations"])


def test_the_harness_fields_are_optional_and_client_is_not(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    response = agent.resume()
    assert response.status_code == 200
    assert response.json()["session"]["harness"] is None
    missing = agent.client.post("/api/v1/me/resume", json={}, headers=agent.auth)
    assert missing.json()["error"]["details"]["fields"] == {"client": "missing"}


@pytest.mark.parametrize(
    ("harness", "seconds"),
    [
        ("Cline", 25),
        ("Cline CLI", 25),
        ("opencode", 110),
        ("Hermes Agent", 170),
        ("Kimi Code", 280),
        ("oh-my-pi", 290),
        ("OMP", 290),
        ("Claude Code", 540),
        ("claude", 540),
        ("claude-code", 540),
        ("Codex CLI", 600),
        ("pi", 600),
        ("a harness nobody listed", 600),
        (None, 600),
    ],
)
def test_the_wait_hint_follows_the_declared_harness(
    owner: flow.Human, make_client: ClientFactory, harness: str | None, seconds: int
) -> None:
    agent = flow.agent(make_client, owner)
    body = {"harness": harness} if harness is not None else {}
    assert agent.resume(**body).json()["hints"]["wait_timeout"] == seconds


def test_a_human_cannot_resume(owner: flow.Human) -> None:
    response = owner.post("/me/resume", {"client": "browser"})
    assert response.status_code == 403 and response.headers["Maity-Error"] == "forbidden"


def test_a_resume_closes_the_previous_session_of_the_credential(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    first = agent.resume().json()["session"]["id"]
    second = agent.resume().json()["session"]["id"]
    with migrated.connect() as conn:
        sessions = dict(conn.execute(select(t.agent_session.c.id, t.agent_session.c.live)).all())
        resumed = conn.execute(
            select(t.credential.c.resumed_at).where(t.credential.c.id == agent.credential_id)
        ).scalar()
    assert sessions == {first: None, second: True}
    assert resumed is not None


def test_the_cursor_is_mirrored_and_the_own_start_is_skipped(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    packet = agent.resume().json()
    events = packet["events"]
    assert events["after"] == 0
    kinds = [e["kind"] for e in events["items"]]
    assert "member_joined" in kinds  # broadcast to everyone
    with migrated.connect() as conn:
        started = conn.execute(
            select(t.event.c.seq).where(t.event.c.kind == "session_started")
        ).scalar_one()
    assert events["cursor"] >= started
    owner.patch("/projects/maity", {"state": "freeze", "reason": "release"})
    later = agent.resume(cursor=events["cursor"]).json()["events"]
    assert later["after"] == events["cursor"]
    assert [e["kind"] for e in later["items"]] == ["state_changed"]


def test_without_a_cursor_the_last_acknowledged_one_is_used(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume(cursor=5)
    assert agent.resume().json()["events"]["after"] == 5


def test_the_events_are_capped_at_a_hundred(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import events as ev

    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    with ev.transaction(migrated) as conn:
        for i in range(120):
            ev.emit(conn, project_id, "rules_changed", ["all"], {"version": i})
    block = agent.resume(cursor=0).json()["events"]
    assert len(block["items"]) == 100 and block["truncated"] is True
    assert block["cursor"] == block["items"][-1]["seq"]


def test_rules_markdown_comes_only_when_the_rules_moved(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    first = agent.resume().json()
    assert first["rules"]["changed"] is True and first["rules"]["markdown"].startswith("# Rules")
    cursor = first["events"]["cursor"]
    quiet = agent.resume(cursor=cursor).json()["rules"]
    assert quiet == {"version": 1, "changed": False}
    owner.patch("/projects/maity", {"rules_markdown": "Write tests first."})
    moved = agent.resume(cursor=cursor).json()["rules"]
    assert moved["changed"] is True and moved["version"] == 2
    assert "Write tests first." in moved["markdown"]


def test_events_another_member_may_not_read_stay_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import events as ev

    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    with ev.transaction(migrated) as conn:
        ev.emit(conn, project_id, "task_checkpoint", ["member:agt-someone-else"], {})
        ev.emit(conn, project_id, "task_assigned", [f"member:{agent.id}"], {})
        ev.emit(conn, project_id, "task_reported", ["role:reviewer"], {})
    kinds = [e["kind"] for e in agent.resume(cursor=0).json()["events"]["items"]]
    assert "task_assigned" in kinds
    assert "task_checkpoint" not in kinds and "task_reported" not in kinds


def test_claims_and_assignments_come_with_the_packet(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        membership_id = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent.id)
        ).scalar_one()
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    held = factory.card(
        migrated, project_id, membership_id, status="in_progress", claim_holder=membership_id
    )
    assigned = factory.card(migrated, project_id, membership_id, assigned_to=membership_id)
    packet = agent.resume().json()
    assert [c["id"] for c in packet["claims"]] == [held]
    assert packet["claims"][0]["claim"]["session_id"] == packet["session"]["id"]  # inherited
    assert [c["id"] for c in packet["assigned"]] == [assigned]


def test_concurrent_resumes_of_one_credential_leave_one_live_session(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    agent = flow.agent(make_client, owner)
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(lambda _: agent.resume().status_code, range(6)))
    assert statuses == [200] * 6
    with migrated.connect() as conn:
        live = conn.execute(
            select(t.agent_session.c.id).where(t.agent_session.c.live.is_(True))
        ).all()
    assert len(live) == 1
