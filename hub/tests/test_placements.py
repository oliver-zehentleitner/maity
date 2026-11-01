"""docs/api.md §15.5–15.7: placements, proposals and consent, reports, closing."""

from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from maity_hub import placements as pl
from maity_hub import tables as t
from maity_hub.routes import runner as runner_routes
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_runner_stream import attach, hello, send
from tests.test_runners import Runner, call, error, paired

REPOSITORY = "https://github.com/oliver-zehentleitner/maity"


@dataclass
class Setup:
    owner: flow.Human
    runner: Runner
    client: TestClient  # the runner's
    agent: flow.Agent
    engine: Engine


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    attach(owner, runner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    return Setup(owner, runner, client, agent, migrated)


def place(s: Setup, who: Any = None, **body: Any) -> Any:
    payload = {
        "agent": {"id": s.agent.id},
        "runner": s.runner.id,
        "harness": "claude-code",
        **body,
    }
    return (who or s.owner).post("/projects/maintainer/maity/placements", payload)


def placed(s: Setup, **body: Any) -> dict[str, Any]:
    response = place(s, **body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def report(s: Setup, placement: dict[str, Any], seq: int, **body: Any) -> Any:
    payload = {
        "seq": seq,
        "observed_generation": placement["generation"],
        "state": "running",
        "restarts": 0,
        "target": "local",
        "since": "2026-10-22T13:00:00Z",
        **body,
    }
    path = f"/api/v1/runner/placements/{placement['id']}/status"
    return send(s.client, s.runner, "POST", path, payload)


def runner_reads(s: Setup) -> list[str]:
    response = call(s.client, s.runner, "GET", "/api/v1/runner/placements")
    assert response.status_code == 200, response.text
    return [p["id"] for p in response.json()["items"]]


def events_of(s: Setup, kind: str) -> list[dict[str, Any]]:
    items = s.owner.get("/projects/maintainer/maity/events?after=0&limit=200").json()["items"]
    return [e for e in items if e["kind"] == kind]


def admin_agent(make_client: ClientFactory, s: Setup) -> flow.Agent:
    return flow.agent(make_client, s.owner, role="admin")


def get(s: Setup, placement_id: str) -> dict[str, Any]:
    found: dict[str, Any] = s.owner.get(
        f"/projects/maintainer/maity/placements/{placement_id}"
    ).json()
    return found


# --- creating --------------------------------------------------------------------------


def test_a_placement_has_the_contract_shape(setup: Setup) -> None:
    body = placed(setup)
    assert set(body) == {
        "id",
        "project",
        "project_id",
        "agent",
        "runner",
        "target",
        "harness",
        "mode",
        "model",
        "workspace",
        "desired",
        "generation",
        "rejoin",
        "stop_grace_seconds",
        "approval",
        "credential_id",
        "reported_current",
        "active",
        "closed_at",
        "closed_reason",
        "created_by",
        "proposed_by",
        "created_at",
        "updated_by",
        "updated_at",
        "reported",
        "session_hint",
        "logs_hint",
    }
    assert body["id"].startswith("plc-") and body["project"] == "maintainer/maity"
    assert body["agent"]["id"] == setup.agent.id
    assert body["runner"] == {"id": setup.runner.id, "name": "home-laptop"}
    assert (body["mode"], body["desired"], body["generation"]) == ("interactive", "running", 1)
    assert body["workspace"]["clone"] == body["agent"]["handle"]
    assert body["approval"] == {"status": "approved", "request_id": None, "pending_change": None}
    assert (body["reported"], body["reported_current"], body["active"]) == (None, False, True)
    assert body["logs_hint"] == f"maity runner logs {body['id']}"
    [created] = events_of(setup, "placement_created")
    assert created["audience"][0] == f"runner:{setup.runner.id}"
    assert "briefing" not in created["payload"] and "session_hint" not in created["payload"]
    assert runner_reads(setup) == [body["id"]]


def test_the_runner_reads_the_placement_with_its_repository(setup: Setup) -> None:
    body = placed(setup, workspace={"branch": "main"})
    [seen] = call(setup.client, setup.runner, "GET", "/api/v1/runner/placements").json()["items"]
    assert seen == {
        "id": body["id"],
        "project": "maintainer/maity",
        "project_id": body["project_id"],
        "project_aliases": [],
        "generation": 1,
        "desired": "running",
        "agent": {
            "id": setup.agent.id,
            "handle": body["agent"]["handle"],
            "member": True,
            "credential_expected": False,
        },
        "harness": "claude-code",
        "mode": "interactive",
        "model": None,
        "target": None,
        "workspace": {"clone": body["agent"]["handle"], "branch": "main", "repository": REPOSITORY},
        "rejoin": False,
        "stop_grace_seconds": 120,
        "seq": 0,
    }
    packet = hello(setup.client, setup.runner).json()
    assert [p["id"] for p in packet["placements"]] == [body["id"]]


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"model": "gpt-9"}, "harness_not_offered"),
        ({"mode": "supervised", "harness": "codex"}, "harness_not_offered"),
        ({"target": "build-1"}, "harness_not_offered"),
        ({"runner": "rnr-nope"}, "runner_not_attached"),
    ],
)
def test_what_the_runner_does_not_offer_is_refused(
    setup: Setup, body: dict[str, Any], code: str
) -> None:
    response = place(setup, **body)
    assert (response.status_code, error(response)) == (409, code)
    if code == "harness_not_offered":
        assert response.json()["error"]["details"]["offered"][0]["id"] == "claude-code"


def test_a_repository_the_runner_does_not_offer_is_refused(
    setup: Setup, make_client: ClientFactory
) -> None:
    flow.project(setup.owner, "other", repository={"url": "https://github.com/someone/else"})
    attach(setup.owner, setup.runner, "other")
    agent = flow.agent(make_client, setup.owner, "other")
    response = setup.owner.post(
        "/projects/maintainer/other/placements",
        {"agent": {"id": agent.id}, "runner": setup.runner.id, "harness": "claude-code"},
    )
    assert (response.status_code, error(response)) == (409, "repository_not_offered")


def test_one_placement_per_membership_and_per_clone(
    setup: Setup, make_client: ClientFactory
) -> None:
    first = placed(setup)
    again = place(setup, workspace={"clone": "elsewhere"})
    assert (again.status_code, error(again)) == (409, "placement_exists")
    assert again.json()["error"]["details"] == {"placement": first["id"]}
    other = flow.agent(make_client, setup.owner)
    same_clone = place(
        setup, agent={"id": other.id}, workspace={"clone": first["workspace"]["clone"]}
    )
    assert (same_clone.status_code, error(same_clone)) == (409, "placement_exists")


def test_a_new_profile_is_held_by_its_handle(setup: Setup) -> None:
    body = placed(
        setup,
        agent={"handle": "agent-f", "display_name": "Agent F"},
        trust="member",
        role="coder",
        briefing="You own the Runners view.",
    )
    assert body["agent"] == {
        "id": None,
        "handle": "agent-f",
        "name": "maintainer/agent-f",  # the global name, the runner view's (§6.3)
        "display_name": "Agent F",
        "avatar_url": None,  # no profile yet (§6.10)
    }
    assert body["briefing"] == "You own the Runners view."
    assert body["workspace"]["clone"] == "agent-f"
    twice = place(
        setup, agent={"handle": "agent-f", "display_name": "F"}, workspace={"clone": "f2"}
    )
    assert (twice.status_code, error(twice)) == (409, "placement_exists")
    handle = setup.owner.get(f"/projects/maintainer/maity/members/{setup.agent.id}").json()[
        "handle"
    ]
    taken = place(setup, agent={"handle": handle, "display_name": "x"})
    assert taken.json()["error"]["details"]["fields"] == {"handle": "taken"}
    with_fields = place(setup, trust="admin", role="coder")
    assert with_fields.json()["error"]["details"]["fields"] == {
        "trust": "not_with_agent_id",
        "role": "not_with_agent_id",
    }


def test_the_quota_the_closed_project_and_the_revoked_runner(
    setup: Setup, make_client: ClientFactory
) -> None:
    setup.owner.patch(
        "/projects/maintainer/maity", {"policy": {"max_placements": 1}, "reason": "one"}
    )
    placed(setup)
    other = flow.agent(make_client, setup.owner)
    over = place(setup, agent={"id": other.id})
    assert (over.status_code, over.json()["error"]["details"]) == (409, {"max": 1})
    setup.owner.patch(
        "/projects/maintainer/maity", {"policy": {"max_placements": 8}, "reason": "more"}
    )
    setup.owner.patch("/projects/maintainer/maity", {"state": "review", "reason": "release"})
    reasonless = place(setup, agent={"id": other.id})
    assert reasonless.json()["error"]["details"]["fields"] == {"reason": "required"}
    setup.owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "done"})
    closed = place(setup, agent={"id": other.id}, reason="late")
    assert (closed.status_code, error(closed)) == (409, "project_closed")
    setup.owner.patch("/projects/maintainer/maity", {"state": "build", "reason": "again"})
    setup.owner.post(f"/runners/{setup.runner.id}/revoke")
    revoked = place(setup, agent={"id": other.id})
    assert (revoked.status_code, error(revoked)) == (409, "runner_revoked")


# --- proposals and consent ---------------------------------------------------------------


def test_an_agents_proposal_waits_for_consent(setup: Setup, make_client: ClientFactory) -> None:
    admin = admin_agent(make_client, setup)
    reasonless = place(setup, admin)
    assert reasonless.json()["error"]["details"]["fields"] == {"reason": "required"}
    proposed = place(setup, admin, reason="a second pair of hands")
    assert proposed.status_code == 201, proposed.text
    body = proposed.json()
    assert body["approval"]["status"] == "pending" and body["proposed_by"] == admin.id
    assert body["created_by"] == setup.owner.id  # the profile's owner, a human
    request_id = body["approval"]["request_id"]
    assert runner_reads(setup) == []  # the runner never sees a pending placement
    request = setup.owner.get(f"/projects/maintainer/maity/requests/{request_id}").json()
    assert request["class"] == "consent" and request["title"].startswith("Start ")
    assert request["placement"]["id"] == body["id"]
    assert request["placement"]["isolation"]["kind"] == "shared_user"
    assert "reason: a second pair of hands" in request["summary"]
    # Under the default `spawn_consent_by: human` no agent answers it, the proposer neither.
    own = admin.post(f"/projects/maintainer/maity/requests/{request_id}/answer", {"reply_id": "go"})
    assert own.json()["error"]["details"] == {"reason": "humans_only"}
    go = setup.owner.post(
        f"/projects/maintainer/maity/requests/{request_id}/answer", {"reply_id": "go"}
    )
    assert go.status_code == 200, go.text
    assert get(setup, body["id"])["approval"]["status"] == "approved"
    assert runner_reads(setup) == [body["id"]]


def test_only_a_human_answers_a_placements_consent_by_default(
    setup: Setup, make_client: ClientFactory
) -> None:
    proposer, other = admin_agent(make_client, setup), admin_agent(make_client, setup)
    body = place(setup, proposer, reason="more hands").json()
    request_id = body["approval"]["request_id"]
    path = f"/projects/maintainer/maity/requests/{request_id}/answer"
    refused = other.post(path, {"reply_id": "go"})
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    assert other.post(path, {"reply_id": "no"}).status_code == 403  # nor a refusal
    assert get(setup, body["id"])["approval"]["status"] == "pending"
    packet = other.resume().json()["requests"]
    assert request_id not in [r["id"] for r in packet["to_answer"]]
    # An agent cannot change who answers: setting the policy is a human's.
    change = {"policy": {"spawn_consent_by": "role"}, "reason": "let us"}
    assert other.patch("/projects/maintainer/maity", change).status_code == 403
    assert setup.owner.post(path, {"reply_id": "go"}).status_code == 200


def test_under_role_an_admin_agent_answers_a_placements_consent(
    setup: Setup, make_client: ClientFactory
) -> None:
    setup.owner.patch(
        "/projects/maintainer/maity", {"policy": {"spawn_consent_by": "role"}, "reason": "agreed"}
    )
    proposer, other = admin_agent(make_client, setup), admin_agent(make_client, setup)
    body = place(setup, proposer, reason="more hands").json()
    request_id = body["approval"]["request_id"]
    packet = other.resume().json()["requests"]
    assert request_id in [r["id"] for r in packet["to_answer"]]
    go = other.post(f"/projects/maintainer/maity/requests/{request_id}/answer", {"reply_id": "go"})
    assert go.status_code == 200, go.text
    assert get(setup, body["id"])["approval"]["status"] == "approved"
    # Never the proposer itself, whatever the policy.
    again = place(setup, proposer, agent={"id": other.id}, reason="you too").json()
    self_answer = proposer.post(
        f"/projects/maintainer/maity/requests/{again['approval']['request_id']}/answer",
        {"reply_id": "go"},
    )
    assert (self_answer.status_code, error(self_answer)) == (409, "self_answer")


def test_no_refuses_and_a_withdrawal_closes(setup: Setup, make_client: ClientFactory) -> None:
    admin = admin_agent(make_client, setup)
    first = place(setup, admin, reason="try").json()
    setup.owner.post(
        f"/projects/maintainer/maity/requests/{first['approval']['request_id']}/answer",
        {"reply_id": "no"},
    )
    refused = get(setup, first["id"])
    assert (refused["approval"]["status"], refused["closed_reason"]) == ("refused", "refused")
    second = place(setup, admin, reason="again").json()  # a refused one blocks nothing
    admin.post(
        f"/projects/maintainer/maity/requests/{second['approval']['request_id']}/withdraw",
        {"reason": "no"},
    )
    assert get(setup, second["id"])["closed_reason"] == "withdrawn"


def test_spawn_requests_off_and_direct(setup: Setup, make_client: ClientFactory) -> None:
    admin = admin_agent(make_client, setup)
    setup.owner.patch(
        "/projects/maintainer/maity", {"policy": {"spawn_requests": "off"}, "reason": "no"}
    )
    off = place(setup, admin, reason="please")
    assert (off.status_code, error(off)) == (403, "forbidden")
    setup.owner.patch(
        "/projects/maintainer/maity", {"policy": {"spawn_requests": "direct"}, "reason": "go"}
    )
    direct = place(setup, admin, reason="urgent")
    assert direct.json()["approval"]["status"] == "approved"
    [created] = events_of(setup, "placement_created")
    assert created["payload"]["reason"] == "urgent"


def test_who_may_propose(setup: Setup, make_client: ClientFactory) -> None:
    member = place(setup, setup.agent, reason="me")
    assert (member.status_code, member.json()["error"]["details"]) == (
        403,
        {"scope": "agents:propose"},
    )
    admin = admin_agent(make_client, setup)
    new_profile = place(setup, admin, agent={"handle": "x-y", "display_name": "X"}, reason="r")
    assert new_profile.json()["error"]["details"]["fields"] == {"agent": "id_required"}


def test_a_proposed_change_waits_and_the_owner_settles_it(
    setup: Setup, make_client: ClientFactory
) -> None:
    body = placed(setup)
    admin = admin_agent(make_client, setup)
    proposed = admin.patch(
        f"/projects/maintainer/maity/placements/{body['id']}",
        {"model": "opus", "reason": "smarter"},
    )
    assert proposed.status_code == 200, proposed.text
    changed = proposed.json()
    assert changed["approval"]["pending_change"] == {"model": "opus"}
    assert (changed["model"], changed["generation"]) == (None, 1)
    restart = admin.post(f"/projects/maintainer/maity/placements/{body['id']}/restart")
    assert (restart.status_code, error(restart)) == (409, "approval_pending")
    request_id = changed["approval"]["request_id"]
    setup.owner.post(f"/projects/maintainer/maity/requests/{request_id}/answer", {"reply_id": "go"})
    after = get(setup, body["id"])
    assert (after["model"], after["generation"], after["approval"]["pending_change"]) == (
        "opus",
        2,
        None,
    )


def test_the_runners_owner_settles_by_acting(setup: Setup, make_client: ClientFactory) -> None:
    admin = admin_agent(make_client, setup)
    pending = place(setup, admin, reason="r").json()
    started = setup.owner.patch(
        f"/projects/maintainer/maity/placements/{pending['id']}", {"desired": "running"}
    )
    assert started.json()["approval"]["status"] == "approved"
    answered = setup.owner.get(
        f"/projects/maintainer/maity/requests/{pending['approval']['request_id']}"
    ).json()
    assert answered["status"] == "answered" and answered["answer"]["reply_id"] == "go"
    proposal = admin.patch(
        f"/projects/maintainer/maity/placements/{pending['id']}", {"model": "opus", "reason": "r"}
    ).json()
    own = setup.owner.patch(
        f"/projects/maintainer/maity/placements/{pending['id']}", {"stop_grace_seconds": 30}
    )
    assert own.json()["approval"]["pending_change"] is None
    assert own.json()["stop_grace_seconds"] == 30 and own.json()["model"] is None
    withdrawn = setup.owner.get(
        f"/projects/maintainer/maity/requests/{proposal['approval']['request_id']}"
    ).json()
    assert withdrawn["status"] == "withdrawn"


# --- visibility --------------------------------------------------------------------------


def test_who_sees_which_placement(setup: Setup, make_client: ClientFactory) -> None:
    mine = placed(setup)
    other_agent = flow.agent(make_client, setup.owner)
    theirs = placed(setup, agent={"id": other_agent.id})
    own = setup.agent.get("/projects/maintainer/maity/placements").json()["items"]
    assert [p["id"] for p in own] == [mine["id"]]
    assert "session_hint" not in own[0] and "logs_hint" not in own[0]
    assert (
        setup.agent.get(f"/projects/maintainer/maity/placements/{theirs['id']}").status_code == 404
    )
    admin = admin_agent(make_client, setup)
    seen = {p["id"] for p in admin.get("/projects/maintainer/maity/placements").json()["items"]}
    assert seen == {mine["id"], theirs["id"]}
    assert admin.get("/projects/maintainer/maity/runners").status_code == 200
    assert setup.agent.get("/projects/maintainer/maity/runners").status_code == 403


# --- reports -----------------------------------------------------------------------------


def test_a_report_is_stored_once_per_seq(setup: Setup) -> None:
    body = placed(setup)
    first = report(setup, body, 1, session_hint="tmux -L maity attach -t x")
    assert first.status_code == 200, first.text
    assert first.json()["reported"]["state"] == "running"
    view = get(setup, body["id"])
    assert view["reported_current"] is True and view["session_hint"] == "tmux -L maity attach -t x"
    again = report(setup, body, 1, state="failed", reason="crash_loop")
    assert again.json()["reported"]["state"] == "running"  # not above the stored seq
    assert len(events_of(setup, "placement_reported")) == 1
    stale = report(setup, {**body, "generation": 2}, 2)
    assert (stale.status_code, error(stale)) == (409, "stale_generation")
    reports = setup.agent.get(f"/projects/maintainer/maity/placements/{body['id']}/reports").json()[
        "items"
    ]
    assert [e["actor"]["kind"] for e in reports] == ["runner"]


def test_an_older_generation_becomes_an_event_only(setup: Setup) -> None:
    body = placed(setup)
    setup.owner.post(f"/projects/maintainer/maity/placements/{body['id']}/restart")
    old = report(setup, body, 1)  # about generation 1, the placement is at 2
    assert old.status_code == 200 and old.json()["reported"] is None
    assert get(setup, body["id"])["reported_current"] is False
    assert len(events_of(setup, "placement_reported")) == 1


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"state": "pending"}, {"reason": "required_with_pending"}),
        ({"state": "running", "reason": "crash_loop"}, {"reason": "not_with_state"}),
        ({"state": "failed", "reason": "made_up"}, {"reason": "unknown"}),
        (
            {"state": "failed", "reason": "clone_failed", "detail": "binary_not_found"},
            {"detail": "not_with_reason"},
        ),
        ({"state": "running", "detail": "nonsense"}, {"detail": "unknown"}),
    ],
)
def test_reported_codes_are_closed_lists(
    setup: Setup, body: dict[str, Any], fields: dict[str, str]
) -> None:
    response = report(setup, placed(setup), 1, **body)
    assert (response.status_code, response.json()["error"]["details"]["fields"]) == (400, fields)


def test_since_is_clamped_to_hub_time(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, since="2999-01-01T00:00:00Z")
    since = get(setup, body["id"])["reported"]["since"]
    assert since < "2999"


# --- closing -----------------------------------------------------------------------------


def test_delete_closes_at_once_when_the_runner_never_acted(setup: Setup) -> None:
    body = placed(setup)
    deleted = setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}").json()
    assert (deleted["active"], deleted["closed_reason"]) == (False, "removed")
    assert (
        setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}").status_code == 200
    )


def test_delete_closes_on_the_runners_terminal_report(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    deleted = setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}").json()
    assert (deleted["active"], deleted["desired"], deleted["closed_reason"]) == (
        True,
        "stopped",
        None,
    )
    [stop] = events_of(setup, "agent_stop_requested")
    assert stop["audience"] == [f"member:{setup.agent.id}"]
    assert stop["payload"]["grace_seconds"] == 120
    assert runner_reads(setup) == [body["id"]]  # it still reads what it must stop
    still = report(setup, body, 2, state="stopping")
    assert still.json()["active"] is True
    done = report(setup, body, 3, state="stopped", reason="stopped_by_hub")
    assert done.json()["active"] is False
    assert get(setup, body["id"])["closed_reason"] == "removed"
    late = report(setup, body, 4, state="running")
    assert late.status_code == 200 and late.json()["reported"]["state"] == "stopped"


def test_a_failure_closes_too_and_a_second_delete_is_the_escape(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}")
    failed = report(setup, body, 2, state="failed", reason="harness_missing")
    assert failed.json()["active"] is False
    other = placed(setup)
    report(setup, other, 1)
    setup.owner.delete(f"/projects/maintainer/maity/placements/{other['id']}")
    assert get(setup, other["id"])["active"] is True
    escape = setup.owner.delete(f"/projects/maintainer/maity/placements/{other['id']}").json()
    assert escape["active"] is False and escape["closed_reason"] == "removed"


def test_revoking_the_agents_credential_stops_without_closing(setup: Setup) -> None:
    body = placed(setup)
    with setup.engine.begin() as conn:  # as the pickup will set it (§15.9)
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == body["id"])
            .values(credential_id=setup.agent.credential_id)
        )
    leaked = setup.agent.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": setup.agent.credential},
    )
    assert error(leaked) == "credential_in_payload"
    after = get(setup, body["id"])
    assert (after["desired"], after["active"]) == ("stopped", True)
    assert events_of(setup, "agent_stop_requested") == []


def test_removing_the_member_closes_at_once(setup: Setup) -> None:
    body = placed(setup)
    setup.owner.delete(f"/projects/maintainer/maity/members/{setup.agent.id}")
    assert get(setup, body["id"])["closed_reason"] == "membership_removed"


def test_removing_the_runner_closes_and_names_what_still_runs(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    removed = setup.owner.delete(f"/runners/{setup.runner.id}").json()
    assert removed["still_running"] == [body["id"]]
    assert get(setup, body["id"])["closed_reason"] == "runner_removed"


def test_detaching_and_archiving_close_the_uniform_way(
    setup: Setup, make_client: ClientFactory
) -> None:
    body = placed(setup)
    report(setup, body, 1)
    setup.owner.delete(f"/projects/maintainer/maity/runners/{setup.runner.id}")
    detached = get(setup, body["id"])
    assert (detached["active"], detached["desired"]) == (True, "stopped")
    report(setup, body, 2, state="stopped", reason="stopped_by_hub")
    assert get(setup, body["id"])["closed_reason"] == "detached"
    attach(setup.owner, setup.runner)
    other = placed(setup)
    setup.owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "over"})
    assert get(setup, other["id"])["closed_reason"] == "project_archived"  # never reported


def test_a_revoked_runner_closes_what_is_closing(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}")
    setup.owner.post(f"/runners/{setup.runner.id}/revoke")
    assert get(setup, body["id"])["closed_reason"] == "removed"


# --- restart, carry-over, views -------------------------------------------------------------


def test_restart_bumps_the_generation_and_rejoin_needs_a_revoked_credential(
    setup: Setup,
) -> None:
    body = placed(setup, desired="stopped")
    restarted = setup.owner.post(
        f"/projects/maintainer/maity/placements/{body['id']}/restart"
    ).json()
    assert (restarted["generation"], restarted["desired"]) == (2, "running")
    rejoin = setup.owner.post(
        f"/projects/maintainer/maity/placements/{body['id']}/restart", {"rejoin": True}
    )
    assert rejoin.json()["error"]["details"]["fields"] == {"rejoin": "credential_not_revoked"}


def test_a_credential_carries_over_to_the_same_clone(setup: Setup) -> None:
    body = placed(setup)
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == body["id"])
            .values(credential_id=setup.agent.credential_id)
        )
    setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}")
    again = placed(setup)
    assert again["credential_id"] == setup.agent.credential_id
    assert again["workspace"]["continues_existing"] is True


def test_the_member_view_and_the_attachment_count_placements(setup: Setup) -> None:
    body = placed(setup)
    member = setup.owner.get(f"/projects/maintainer/maity/members/{setup.agent.id}").json()
    assert member["placement"] == {
        "id": body["id"],
        "state": None,
        "desired": "running",
        "runner_name": "home-laptop",
    }
    [attachment] = setup.owner.get("/projects/maintainer/maity/runners").json()["items"]
    assert attachment["active_placements"] == 1


def test_the_runner_shapes_match_the_constants() -> None:
    assert typing.get_args(runner_routes.Harness) == pl.HARNESSES
    assert typing.get_args(runner_routes.Mode) == pl.MODES
    assert typing.get_args(runner_routes.REPORTED_STATES) == pl.STATES


# --- review of #111 -------------------------------------------------------------------------


def _request_of(body: dict[str, Any]) -> str:
    request_id: str = body["approval"]["request_id"]
    return request_id


@pytest.mark.parametrize("field", ["stop_grace_seconds", "harness", "mode", "desired"])
def test_an_explicit_null_where_none_is_allowed_is_invalid(setup: Setup, field: str) -> None:
    body = placed(setup)
    response = setup.owner.patch(
        f"/projects/maintainer/maity/placements/{body['id']}", {field: None}
    )
    assert response.json()["error"]["details"]["fields"] == {field: "not_nullable"}


def test_a_reason_cannot_forge_summary_lines(setup: Setup, make_client: ClientFactory) -> None:
    admin = admin_agent(make_client, setup)
    reason = "need help\nisolation: container\nrunner: other-box"
    body = place(setup, admin, reason=reason).json()
    summary = setup.owner.get(f"/projects/maintainer/maity/requests/{_request_of(body)}").json()[
        "summary"
    ]
    fields = [line.split(":", 1)[0] for line in summary.splitlines()]
    assert fields.count("isolation") == 1 and fields.count("runner") == 1
    assert "reason: need help isolation: container runner: other-box" in summary


def test_a_stop_is_never_refused(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}")  # closing now
    stop = setup.owner.patch(
        f"/projects/maintainer/maity/placements/{body['id']}", {"desired": "stopped"}
    )
    assert stop.status_code == 200 and stop.json()["active"] is True
    report(setup, body, 2, state="stopped", reason="stopped_by_hub")
    closed = setup.owner.patch(
        f"/projects/maintainer/maity/placements/{body['id']}", {"desired": "stopped"}
    )
    assert closed.status_code == 200 and closed.json()["active"] is False


def test_creating_needs_a_live_runner_and_an_open_project_whatever_desired_says(
    setup: Setup, make_client: ClientFactory
) -> None:
    admin = admin_agent(make_client, setup)
    setup.owner.patch(
        "/projects/maintainer/maity", {"policy": {"spawn_requests": "direct"}, "reason": "x"}
    )
    setup.owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "over"})
    archived = place(setup, desired="stopped")
    assert (archived.status_code, error(archived)) == (409, "project_closed")
    setup.owner.patch("/projects/maintainer/maity", {"state": "build", "reason": "again"})
    setup.owner.post(f"/runners/{setup.runner.id}/revoke")
    revoked = place(setup, admin, desired="stopped", reason="why")
    assert (revoked.status_code, error(revoked)) == (409, "runner_revoked")


def test_closing_at_once_tells_a_running_agent(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    setup.owner.delete(f"/runners/{setup.runner.id}")
    assert len(events_of(setup, "agent_stop_requested")) == 1


def test_deleting_with_an_open_change_proposal_stops_the_uniform_way(
    setup: Setup, make_client: ClientFactory
) -> None:
    admin = admin_agent(make_client, setup)
    body = placed(setup)
    report(setup, body, 1)
    proposed = admin.patch(
        f"/projects/maintainer/maity/placements/{body['id']}",
        {"stop_grace_seconds": 30, "reason": "r"},
    ).json()
    deleted = setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}").json()
    assert (deleted["active"], deleted["desired"]) == (True, "stopped")
    assert len(events_of(setup, "agent_stop_requested")) == 1
    request = setup.owner.get(f"/projects/maintainer/maity/requests/{_request_of(proposed)}").json()
    assert request["status"] == "withdrawn"


def test_after_a_final_failure_delete_closes_at_once(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    deleted = setup.owner.delete(f"/projects/maintainer/maity/placements/{body['id']}").json()
    assert (deleted["active"], deleted["closed_reason"]) == (False, "removed")


def test_a_go_checks_the_rules_as_they_are_now(setup: Setup, make_client: ClientFactory) -> None:
    admin = admin_agent(make_client, setup)
    body = place(setup, admin, reason="r").json()
    setup.owner.post(f"/runners/{setup.runner.id}/revoke")
    go = setup.owner.post(
        f"/projects/maintainer/maity/requests/{_request_of(body)}/answer", {"reply_id": "go"}
    )
    assert (go.status_code, error(go)) == (409, "runner_revoked")
    request = setup.owner.get(f"/projects/maintainer/maity/requests/{_request_of(body)}").json()
    assert request["status"] == "open" and get(setup, body["id"])["approval"]["status"] == "pending"


def test_a_removed_proposers_requests_are_withdrawn(
    setup: Setup, make_client: ClientFactory
) -> None:
    admin = admin_agent(make_client, setup)
    body = place(setup, admin, reason="r").json()
    setup.owner.delete(f"/projects/maintainer/maity/members/{admin.id}")
    request = setup.owner.get(f"/projects/maintainer/maity/requests/{_request_of(body)}").json()
    assert request["status"] == "withdrawn"
    assert get(setup, body["id"])["closed_reason"] == "withdrawn"


def test_the_owners_stop_on_a_pending_proposal_turns_it_down(
    setup: Setup, make_client: ClientFactory
) -> None:
    admin = admin_agent(make_client, setup)
    body = place(setup, admin, reason="r").json()
    stopped = setup.owner.patch(
        f"/projects/maintainer/maity/placements/{body['id']}", {"desired": "stopped"}
    )
    assert (stopped.json()["active"], stopped.json()["closed_reason"]) == (False, "withdrawn")
    request = setup.owner.get(f"/projects/maintainer/maity/requests/{_request_of(body)}").json()
    assert request["status"] == "withdrawn"


def test_removing_the_boss_clears_a_new_profiles_stored_reports_to(
    setup: Setup, make_client: ClientFactory
) -> None:
    boss = flow.agent(make_client, setup.owner)
    body = placed(
        setup,
        agent={"handle": "agent-n", "display_name": "Agent N"},
        reports_to=boss.id,
    )
    assert setup.owner.delete(f"/projects/maintainer/maity/members/{boss.id}").status_code == 200
    with setup.engine.connect() as conn:
        row = conn.execute(select(t.placement).where(t.placement.c.id == body["id"])).one()
    assert row.new_profile["reports_to"] is None
    assert get(setup, body["id"])["generation"] == body["generation"]  # nothing to re-read


def test_a_deleted_profile_s_placement_closes_and_none_follows(setup: Setup) -> None:
    """§6.3: a placement makes the profile in use; the cascade closes it with
    `membership_removed`; a deleted profile is never placed again."""
    first = placed(setup)
    headers = {"X-CSRF-Token": setup.owner.csrf}
    url = f"/api/v1/agents/{setup.agent.id}"
    refused = setup.owner.client.delete(url, headers=headers)
    assert refused.json()["error"]["details"]["placements"] == [first["id"]]
    assert setup.owner.client.delete(f"{url}?cascade=true", headers=headers).status_code == 200
    closed = setup.owner.get(f"/projects/maintainer/maity/placements/{first['id']}").json()
    assert closed["closed_reason"] == "membership_removed"
    assert place(setup).status_code == 404


def test_a_placement_its_proposer_leaves_behind_closes_when_they_leave(setup: Setup) -> None:
    """docs/api.md §6.2: the placements a leaving human created that made no membership yet
    are closed, so no runner outlives the person who set it going."""
    with setup.engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    pal = factory.human(setup.engine, "pal")
    factory.membership(setup.engine, project_id, "member", human_id=pal)
    pending = placed(setup, agent={"handle": "agent-pal", "display_name": "Agent Pal"})
    kept = placed(setup, agent={"id": setup.agent.id}, workspace={"clone": "kept"})
    with setup.engine.begin() as conn:  # the person who proposed the new profile is pal
        conn.execute(
            update(t.placement).where(t.placement.c.id == pending["id"]).values(created_by=pal)
        )
    left = setup.owner.delete(f"/projects/maintainer/maity/members/{pal}")
    assert left.status_code == 200, left.text
    with setup.engine.connect() as conn:
        rows = {r.id: r for r in conn.execute(select(t.placement))}
    assert rows[pending["id"]].active is None
    assert rows[pending["id"]].closed_reason == "withdrawn"
    assert rows[kept["id"]].active is True  # another person's, and it has its membership
