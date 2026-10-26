"""docs/api.md §15.7: the owner is asked when an agent stops — one hub notice per outage."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_placements import REPOSITORY, Setup, events_of, placed, report
from tests.test_runner_stream import attach, hello
from tests.test_runners import paired


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    """As in test_placements: a project with a repository, an attached runner, an agent."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    attach(owner, runner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    return Setup(owner, runner, client, agent, migrated)


def notices(s: Setup, status: str = "all") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = s.owner.get("/requests", params={"status": status}).json()[
        "items"
    ]
    return [r for r in found if r["filed_by"] == "hub"]


def test_a_failure_files_one_notice_to_the_profiles_owner(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    report(setup, body, 2, state="failed", reason="harness_missing", detail="binary_not_found")
    [notice] = notices(setup)
    handle, runner = body["agent"]["handle"], body["runner"]["name"]
    assert notice["title"] == f"{handle} on {runner} stopped: harness_missing"
    assert notice["summary"].startswith(
        f"Placement {body['id']} on runner {runner} reported failed"
        " (harness_missing, binary_not_found) at "
    )
    assert notice["summary"].endswith("(UTC); restarts 0.")
    assert (notice["class"], notice["status"], notice["personal"]) == ("info", "open", True)
    assert [o["id"] for o in notice["options"]] == ["seen"]
    assert notice["asked_by"]["member_id"] == setup.agent.id
    # The same outage again, or another failing reason, files nothing.
    report(setup, body, 3, state="failed", reason="crash_loop")
    assert len(notices(setup)) == 1


def test_its_events_reach_the_owner_only_and_no_project_route_shows_it(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    [notice] = notices(setup)
    [created] = [
        e for e in events_of(setup, "request_created") if e["subject"]["id"] == notice["id"]
    ]
    assert created["audience"] == [f"member:{setup.owner.id}"]
    for who in (setup.owner, setup.agent):
        assert who.get(f"/projects/maity/requests/{notice['id']}").status_code == 404
        answered = who.post(f"/projects/maity/requests/{notice['id']}/answer", {"reply_id": "seen"})
        assert answered.status_code == 404


def test_quota_exits_open_an_outage_and_a_rate_limit_does_not(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="rate_limited", reason="quota", retry_at="2026-10-22T15:00:00Z")
    assert notices(setup) == []
    report(setup, body, 2, state="exited", reason="quota")
    [notice] = notices(setup)
    assert notice["title"].endswith("stopped: quota")


def test_running_again_ends_the_outage_and_withdraws_the_notice(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    report(setup, body, 2, state="running")
    [notice] = notices(setup)
    assert notice["status"] == "withdrawn"
    report(setup, body, 3, state="failed", reason="crash_loop")  # a new outage
    assert sorted(n["status"] for n in notices(setup)) == ["open", "withdrawn"]


def test_seen_closes_the_notice_not_the_outage(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    [notice] = notices(setup)
    seen = setup.owner.post(f"/requests/{notice['id']}/answer", {"reply_id": "seen"})
    assert seen.status_code == 200, seen.text
    report(setup, body, 2, state="failed", reason="harness_missing")
    assert [n["status"] for n in notices(setup)] == ["answered"]
    report(setup, body, 3, state="running")
    assert [n["status"] for n in notices(setup)] == ["answered"]  # stays as answered


def test_a_stop_ends_the_outage(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    setup.owner.patch(f"/projects/maity/placements/{body['id']}", {"desired": "stopped"})
    assert [n["status"] for n in notices(setup)] == ["withdrawn"]


def test_a_delete_ends_the_outage(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    setup.owner.delete(f"/projects/maity/placements/{body['id']}")
    assert [n["status"] for n in notices(setup)] == ["withdrawn"]


def test_a_report_the_stop_asked_for_opens_nothing(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    setup.owner.patch(f"/projects/maity/placements/{body['id']}", {"desired": "stopped"})
    stopping = {**body, "generation": body["generation"] + 1}
    report(setup, stopping, 2, state="failed", reason="crash_loop")
    assert notices(setup) == []


def test_an_older_generation_opens_nothing(setup: Setup) -> None:
    body = placed(setup)
    setup.owner.post(f"/projects/maity/placements/{body['id']}/restart", {})
    report(setup, body, 1, state="failed", reason="crash_loop")  # generation 1 of 2
    assert notices(setup) == []


def test_archiving_the_project_ends_the_outage(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    setup.owner.patch("/projects/maity", {"state": "archived", "reason": "done"})
    assert [n["status"] for n in notices(setup)] == ["withdrawn"]


def test_the_agent_never_reads_its_own_notice(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    [notice] = notices(setup)
    assert notice["id"] not in setup.agent.resume().text
    setup.owner.post(f"/requests/{notice['id']}/answer", {"reply_id": "seen"})
    assert notice["id"] not in setup.agent.resume().text  # nor the owner's answer
    listed = setup.agent.get("/projects/maity/requests", params={"status": "all"}).json()
    assert notice["id"] not in [r["id"] for r in listed["items"]]


def test_the_project_route_withdraws_nothing(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    [notice] = notices(setup)
    for who in (setup.owner, setup.agent):
        refused = who.post(f"/projects/maity/requests/{notice['id']}/withdraw", {})
        assert refused.status_code == 404
    assert [n["status"] for n in notices(setup)] == ["open"]


def test_the_owners_withdraw_closes_the_notice_not_the_outage(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    [notice] = notices(setup)
    assert setup.owner.post(f"/requests/{notice['id']}/withdraw", {}).status_code == 200
    report(setup, body, 2, state="failed", reason="crash_loop")
    assert [n["status"] for n in notices(setup)] == ["withdrawn"]  # the same outage


def test_after_a_stop_a_run_and_a_failure_open_a_new_outage(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1, state="failed", reason="crash_loop")
    stopped = setup.owner.patch(f"/projects/maity/placements/{body['id']}", {"desired": "stopped"})
    assert [n["status"] for n in notices(setup)] == ["withdrawn"]
    started = setup.owner.patch(
        f"/projects/maity/placements/{body['id']}", {"desired": "running"}
    ).json()
    assert started["generation"] >= stopped.json()["generation"]
    report(setup, started, 2, state="running")
    report(setup, started, 3, state="failed", reason="crash_loop")
    assert sorted(n["status"] for n in notices(setup)) == ["open", "withdrawn"]
