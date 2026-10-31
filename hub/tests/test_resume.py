"""docs/api.md §5.2: the resume packet and sessions."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, func, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PACKET = {
    "onboarding",
    "server_time",
    "api_version",
    "hub_version",
    "memory",
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
    "ticker",
    "events",
    "conversations",  # §5.2, §9.2
    "peers",
    "preferences",  # §19.4
    "operations",
    "team",
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", memory={"provider": "keep-the-why"})
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
    assert packet["hints"] == {"duty": "self", "wait_timeout": 540}  # Claude Code
    assert packet["me"]["owner"] == {"id": owner.id, "handle": "maintainer", "meat_proxy": False}
    assert packet["membership"] == {
        "trust": "member",
        "role": "coder",
        "reports_to": owner.id,
        "areas": ["hub/"],
        "capabilities": [],
        "scopes": ["project:read", "tasks:write", "requests:ask", "events:post"],
        "paused": None,
        "isolated": None,  # §6.2
        "briefing": None,
        "briefing_source": None,
        "chat_url": f"https://hub.example/maintainer/maity/chat/{agent.id}",  # §5.2
        "takes_over": None,  # §3.1: the join named none
        "handover": None,
        "team": {
            "max_instances": 1,
            "distribution": "free",
            "lead_instance": None,
            "wake": "all",
            "review_within_team": False,
            "updated_by": None,
            "updated_at": None,
        },
        "owner_preferences": None,  # §19.4: not given
        "availability_policy": {"on_unavailable": "wait", "substitutes": [], "grace_minutes": 15},
        "covering": [],
        "placement": None,
    }
    assert packet["me"]["instance"] == agent.instance
    assert packet["me"]["address"] == f"{agent.id}#{agent.instance}"
    assert packet["team"] == []
    assert packet["project"]["slug"] == "maity" and packet["project"]["memory"] == {
        "provider": "keep-the-why"
    }
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
    availability = packet["peers"][0].pop("availability")
    assert availability["state"] == "available" and set(availability) == {"state", "since"}
    assert packet["peers"] == [
        {
            "member_id": owner.id,
            "kind": "human",
            "handle": "maintainer",
            "trust": "owner",
            "role": "coder",
            "areas": ["/"],
            "presence": "online",
            "paused": None,
            "covered_by": None,
            "language": "en",
            "meat_proxy": False,
        }
    ]
    assert "GET /projects/maintainer/maity/members" in packet["operations"]
    assert not any("joins" in op for op in packet["operations"])


def test_the_packet_carries_the_released_mark(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§6.1: `released_at` in the packet's project, `null` until the probe sets it."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    agent = flow.agent(make_client, owner)
    assert agent.resume().json()["project"]["released_at"] is None
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(released_at=datetime(2026, 9, 14, 10, tzinfo=UTC)))
    assert agent.resume().json()["project"]["released_at"] == "2026-09-14T10:00:00Z"


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
    packet = agent.resume(cursor=0).json()
    events = packet["events"]
    assert events["after"] == 0
    kinds = [e["kind"] for e in events["items"]]
    assert "member_joined" in kinds  # broadcast to everyone
    with migrated.connect() as conn:
        started = conn.execute(
            select(t.event.c.seq).where(t.event.c.kind == "session_started")
        ).scalar_one()
    assert events["cursor"] >= started
    owner.patch("/projects/maintainer/maity", {"state": "review", "reason": "release"})
    later = agent.resume(cursor=events["cursor"]).json()["events"]
    assert later["after"] == events["cursor"]
    assert [e["kind"] for e in later["items"]] == ["state_changed"]


def test_a_new_instance_starts_at_the_head_of_the_project(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        head = conn.execute(select(func.max(t.event.c.seq))).scalar_one()
    events = agent.resume().json()["events"]
    assert events["after"] == head and events["items"] == []
    assert events["cursor"] >= head
    # The history stays available on request.
    assert agent.resume(cursor=0).json()["events"]["items"]


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
    owner.patch("/projects/maintainer/maity", {"rules_markdown": "Write tests first."})
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
        migrated,
        project_id,
        membership_id,
        status="in_progress",
        claim_holder=membership_id,
        claim_instance=agent.instance,
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


def test_the_packet_carries_the_agents_own_pause(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    paused = owner.patch(
        f"/projects/maintainer/maity/members/{agent.id}", {"paused": {"reason": "quota"}}
    )
    assert paused.status_code == 200, paused.text
    shown = agent.resume().json()["membership"]["paused"]
    assert (shown["reason"], shown["by"]) == ("quota", owner.id)
    assert shown["since"] is not None
    owner.patch(f"/projects/maintainer/maity/members/{agent.id}", {"paused": None})
    assert agent.resume().json()["membership"]["paused"] is None


def test_the_packet_names_the_chat_with_the_owner_on_the_public_url(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§5.2: `membership.chat_url` is `<public URL>/<owner>/<slug>/chat/<member id>` (the direct
    conversation's id is the agent's member id, §9.1), on every resume and never the join host;
    the member views carry none."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    join = "https://join.example"
    agent = flow.agent(make_client, owner)
    url = f"https://hub.example/maintainer/maity/chat/{agent.id}"
    assert agent.resume().json()["membership"]["chat_url"] == url
    assert agent.resume().json()["membership"]["chat_url"] == url  # on every resume
    hosted = make_client(join_url=join)  # a join host does not change the address
    created = flow.join(owner, "maity")
    response = flow.exchange(hosted, created)
    assert response.status_code == 201, response.text
    second = flow.Agent(
        hosted,
        response.text,
        response.headers["Maity-Credential-Id"],
        response.headers["Maity-Member-Id"],
        response.headers["Maity-Instance"],
    )
    open_join = flow.join(owner, "maity", via="public")  # one not yet used: its page reads
    page = make_client().get(f"/join/{open_join['join_url'].rsplit('/', 1)[1]}").text
    line = "Talk to me in Maity: <chat_url>"  # §5.2: the same line on every path
    assert line in page and line in make_client().get("/api/v1/help").text
    assert second.resume().json()["membership"]["chat_url"].startswith("https://hub.example/")
    assert join not in second.resume().json()["membership"]["chat_url"]
    for view in (
        owner.get(f"/projects/maintainer/maity/members/{agent.id}").json(),
        owner.get("/me").json()["member"],
    ):
        assert "chat_url" not in view
