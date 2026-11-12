"""docs/api.md §15.5 "The workspace after a stop", §15.6 and §15.8: the retention time, the
runner's workspace reports, a removal by hand, and what a runner reads of closed placements."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_auth_agent import signed
from tests.test_join_pickup import _allow_instances, exchange, pick_up
from tests.test_placements import (
    REPOSITORY,
    Setup,
    admin_agent,
    events_of,
    get,
    place,
    placed,
    report,
)
from tests.test_runner_stream import attach, hello, member, send
from tests.test_runners import Runner, error, paired

PATH = "/projects/maintainer/maity/placements"
LATER = "2026-12-01T00:00:00Z"


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    """As in test_placements, with room for the placement's instance next to the agent's."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    attach(owner, runner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    _allow_instances(migrated, agent.id, 3)
    return Setup(owner, runner, client, agent, migrated)


def workspace(s: Setup, placement_id: str, *, runner: Runner | None = None, **body: Any) -> Any:
    payload = {"epoch": 1, "state": "retained", "removes_at": LATER, **body}
    path = f"/api/v1/runner/placements/{placement_id}/workspace"
    return send(s.client, runner or s.runner, "POST", path, payload)


def runner_list(s: Setup, closed: bool = False, runner: Runner | None = None) -> list[Any]:
    path, query = "/api/v1/runner/placements", "closed=true" if closed else ""
    response = s.client.get(
        f"{path}?{query}" if query else path,
        headers=signed(runner or s.runner, "GET", path, query),
    )
    assert response.status_code == 200, response.text
    items: list[Any] = response.json()["items"]
    return items


def stopped(s: Setup, **body: Any) -> dict[str, Any]:
    placement = placed(s, **body)
    response = s.owner.patch(f"{PATH}/{placement['id']}", {"desired": "stopped"})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def with_credential(
    s: Setup, make_client: ClientFactory, **body: Any
) -> tuple[dict[str, Any], str]:
    placement = placed(s, **body)
    joined = exchange(make_client(), pick_up(s, placement).json())
    assert joined.status_code == 201, joined.text
    return get(s, placement["id"]), joined.headers["Maity-Credential-Id"]


def closed(s: Setup, placement: dict[str, Any]) -> None:
    """Closed the uniform way: deleted, then the runner's terminal report."""
    report(s, placement, 1)
    s.owner.delete(f"{PATH}/{placement['id']}")
    report(s, placement, 2, state="stopped", reason="stopped_by_hub")
    assert get(s, placement["id"])["active"] is False


def revoked_reason(s: Setup, credential_id: str) -> str | None:
    with s.engine.connect() as conn:
        found: str | None = conn.execute(
            select(t.credential.c.revoked_reason).where(t.credential.c.id == credential_id)
        ).scalar_one()
    return found


def remove(who: Any, placement_id: str) -> Any:
    return who.post(f"{PATH}/{placement_id}/workspace/remove", {})


# --- the retention time -------------------------------------------------------------------


def test_a_placement_has_its_retention_and_its_first_clone(setup: Setup) -> None:
    body = placed(setup)
    assert (body["workspace_retention"], body["workspace_epoch"]) == ("24h", 1)
    assert body["workspace_outcome"] is None
    (read,) = runner_list(setup)
    assert (read["workspace_retention"], read["workspace_epoch"]) == ("24h", 1)
    assert "workspace_outcome" not in read  # only under `desired: stopped` (§15.8)
    other = placed(setup, agent={"handle": "agent-x", "display_name": "X"},
                   workspace_retention="immediate")  # fmt: skip
    assert other["workspace_retention"] == "immediate"
    bad = place(setup, workspace_retention="1h")
    assert (bad.status_code, error(bad)) == (400, "invalid")


def test_the_retention_changes_without_a_new_generation(setup: Setup) -> None:
    body = placed(setup)
    changed = setup.owner.patch(f"{PATH}/{body['id']}", {"workspace_retention": "7d"})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["workspace_retention"], changed.json()["generation"]) == ("7d", 1)
    assert len(events_of(setup, "placement_updated")) == 1
    for value, why in (("1h", None), (None, "not_nullable")):
        bad = setup.owner.patch(f"{PATH}/{body['id']}", {"workspace_retention": value})
        assert (bad.status_code, error(bad)) == (400, "invalid"), bad.text
        if why:
            assert bad.json()["error"]["details"]["fields"] == {"workspace_retention": why}
    assert get(setup, body["id"])["workspace_retention"] == "7d"


def test_the_retention_changes_on_a_closed_placement_too(setup: Setup) -> None:
    """Its clock runs on after the close, until the runner removes the clone (§15.5)."""
    body = placed(setup)
    closed(setup, body)
    changed = setup.owner.patch(f"{PATH}/{body['id']}", {"workspace_retention": "3h"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["workspace_retention"] == "3h"
    mixed = setup.owner.patch(f"{PATH}/{body['id']}", {"workspace_retention": "7d", "model": "x"})
    assert (mixed.status_code, error(mixed)) == (409, "invalid_transition")


def test_who_changes_the_retention(
    setup: Setup, make_client: ClientFactory, migrated: Engine
) -> None:
    body = placed(setup)
    plain = member(make_client, migrated, "member")
    refused = plain.patch(f"{PATH}/{body['id']}", {"workspace_retention": "3h"})
    assert (refused.status_code, error(refused)) == (403, "forbidden")
    agent = admin_agent(make_client, setup)  # `agents:propose`: as for `desired`
    changed = agent.patch(f"{PATH}/{body['id']}", {"workspace_retention": "3h"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["generation"] == 1


# --- the runner's reports ----------------------------------------------------------------


def test_a_report_on_a_stopped_placement_shows_as_its_outcome(setup: Setup) -> None:
    body = stopped(setup)
    before = len(events_of(setup, "placement_updated"))
    answer = workspace(setup, body["id"], size_bytes=1234)
    assert answer.status_code == 200, answer.text
    outcome = answer.json()["workspace_outcome"]
    assert outcome == {
        "state": "retained",
        "reason": None,
        "unsaved": 0,
        "size_bytes": 1234,
        "removes_at": LATER,
        "epoch": 1,
        "remove_requested": False,
        "remove_requested_at": None,
        "reported_at": outcome["reported_at"],
    }
    assert get(setup, body["id"])["workspace_outcome"] == outcome
    (read,) = runner_list(setup)
    assert read["workspace_outcome"] == outcome  # under `desired: stopped` (§15.8)
    assert len(events_of(setup, "placement_updated")) == before + 1
    kept = workspace(setup, body["id"], state="kept", reason="unsaved_work", unsaved=3,
                     removes_at=None, size_bytes=99)  # fmt: skip
    assert kept.status_code == 200, kept.text
    shown = get(setup, body["id"])["workspace_outcome"]
    assert (shown["state"], shown["reason"], shown["unsaved"], shown["removes_at"]) == (
        "kept",
        "unsaved_work",
        3,
        None,
    )


@pytest.mark.parametrize(
    "body,field,why",
    [
        ({"removes_at": None}, "removes_at", "required_with_retained"),
        ({"state": "kept"}, "reason", "required_with_kept"),
        ({"state": "kept", "reason": "tired"}, "reason", "unknown"),
        ({"reason": "in_use"}, "reason", "not_with_state"),
        ({"state": "removed", "reason": "in_use"}, "reason", "not_with_state"),
        ({"state": "kept", "reason": "in_use", "unsaved": 2}, "unsaved", "not_with_reason"),
    ],
)
def test_what_a_workspace_report_needs(
    setup: Setup, body: dict[str, Any], field: str, why: str
) -> None:
    placement = stopped(setup)
    answer = workspace(setup, placement["id"], **body)
    assert (answer.status_code, error(answer)) == (400, "invalid"), answer.text
    assert answer.json()["error"]["details"]["fields"][field] == why


def test_retained_and_kept_are_not_for_a_running_placement(setup: Setup) -> None:
    body = placed(setup)
    reports: list[dict[str, Any]] = [{}, {"state": "kept", "reason": "in_use"}]
    for extra in reports:
        answer = workspace(setup, body["id"], **extra)
        assert (answer.status_code, error(answer)) == (409, "conflict"), answer.text
    assert get(setup, body["id"])["workspace_outcome"] is None


def test_an_epoch_the_hub_never_issued_is_invalid(setup: Setup) -> None:
    body = stopped(setup)
    answer = workspace(setup, body["id"], epoch=2)
    assert (answer.status_code, error(answer)) == (400, "invalid")
    assert answer.json()["error"]["details"]["fields"] == {"epoch": "ahead"}


def test_removed_revokes_the_credential_and_starts_the_next_clone(
    setup: Setup, make_client: ClientFactory
) -> None:
    body, credential_id = with_credential(setup, make_client)
    setup.owner.patch(f"{PATH}/{body['id']}", {"desired": "stopped"})
    workspace(setup, body["id"])
    assert remove(setup.owner, body["id"]).status_code == 202
    answer = workspace(setup, body["id"], state="removed", removes_at=None, size_bytes=5)
    assert answer.status_code == 200, answer.text
    read = answer.json()
    assert (read["workspace_epoch"], read["rejoin"]) == (2, True)
    assert read["workspace_outcome"] == {
        "state": "removed",
        "reason": None,
        "unsaved": 0,
        "size_bytes": None,
        "removes_at": None,
        "epoch": 1,
        "remove_requested": False,  # cleared whatever the report named: nothing is left
        "remove_requested_at": None,
        "reported_at": read["workspace_outcome"]["reported_at"],
    }
    assert revoked_reason(setup, credential_id) == "workspace_removed"
    (told,) = events_of(setup, "credential_revoked")
    assert told["payload"] == {"credential_id": credential_id, "reason": "workspace_removed"}
    assert get(setup, body["id"])["desired"] == "stopped"
    # A repeat, and a late retry of an earlier report about the removed clone: nothing.
    lates: list[dict[str, Any]] = [{"state": "removed", "removes_at": None}, {}]
    for late in lates:
        again = workspace(setup, body["id"], **late)
        assert again.status_code == 200, again.text
        assert again.json()["workspace_outcome"]["state"] == "removed"
        assert again.json()["workspace_epoch"] == 2
    assert len(events_of(setup, "credential_revoked")) == 1
    # The next clone reports under the new epoch.
    assert workspace(setup, body["id"], epoch=2).json()["workspace_outcome"]["epoch"] == 2


def test_removed_is_taken_while_a_start_came_in(setup: Setup, make_client: ClientFactory) -> None:
    """The start joins anew instead of looking for a credential that is gone (§15.5)."""
    body, credential_id = with_credential(setup, make_client)
    setup.owner.patch(f"{PATH}/{body['id']}", {"desired": "stopped"})
    workspace(setup, body["id"])
    started = setup.owner.patch(f"{PATH}/{body['id']}", {"desired": "running"})
    assert started.json()["workspace_outcome"] is None  # the start cleared it
    answer = workspace(setup, body["id"], state="removed", removes_at=None)
    assert answer.status_code == 200, answer.text
    after = get(setup, body["id"])
    assert (after["desired"], after["rejoin"], after["workspace_epoch"]) == ("running", True, 2)
    assert after["workspace_outcome"] is None  # it runs: no outcome shown (§15.5)
    assert revoked_reason(setup, credential_id) == "workspace_removed"
    again = pick_up(setup, after)
    assert again.status_code == 201, again.text  # the rejoin's pickup


def test_another_running_placement_keeps_the_credential(
    setup: Setup, make_client: ClientFactory
) -> None:
    first, credential_id = with_credential(setup, make_client)
    closed(setup, first)
    second = placed(setup)  # same member, runner and clone: the credential carries over
    assert second["credential_id"] == credential_id
    answer = workspace(setup, first["id"], state="removed", removes_at=None)
    assert answer.status_code == 200, answer.text
    assert answer.json()["rejoin"] is False  # closed: nothing to rejoin
    assert revoked_reason(setup, credential_id) is None
    assert get(setup, second["id"])["desired"] == "running"


def test_a_stopped_placement_naming_it_does_not_keep_it_and_rejoins(
    setup: Setup, make_client: ClientFactory
) -> None:
    first, credential_id = with_credential(setup, make_client)
    closed(setup, first)
    second = placed(setup)
    assert second["credential_id"] == credential_id
    setup.owner.patch(f"{PATH}/{second['id']}", {"desired": "stopped"})
    workspace(setup, first["id"], state="removed", removes_at=None)
    assert revoked_reason(setup, credential_id) == "workspace_removed"
    # The successor took the credential over; it joins anew at its next start instead of
    # being refused for a credential that is gone. Its own clone and epoch stay.
    after = get(setup, second["id"])
    assert (after["rejoin"], after["workspace_epoch"]) == (True, 1)
    started = setup.owner.patch(f"{PATH}/{second['id']}", {"desired": "running"})
    assert started.status_code == 200, started.text
    again = pick_up(setup, started.json())
    assert again.status_code == 201, again.text


def test_a_start_clears_the_outcome_and_a_removed_clone_continues_nothing(
    setup: Setup, make_client: ClientFactory
) -> None:
    body = stopped(setup)
    workspace(setup, body["id"])
    remove(setup.owner, body["id"])
    restarted = setup.owner.post(f"{PATH}/{body['id']}/restart", {})
    assert restarted.json()["workspace_outcome"] is None
    with setup.engine.connect() as conn:
        requested = conn.execute(
            select(t.placement.c.remove_requested_at).where(t.placement.c.id == body["id"])
        ).scalar()
    assert requested is None
    closed(setup, get(setup, body["id"]))
    assert placed(setup)["workspace"]["continues_existing"] is True


def test_a_removed_clone_is_not_continued(setup: Setup) -> None:
    first = placed(setup)
    closed(setup, first)
    workspace(setup, first["id"], state="removed", removes_at=None)
    assert placed(setup)["workspace"]["continues_existing"] is False


# --- a removal by hand -------------------------------------------------------------------


def test_a_removal_by_hand_stays_asked_until_a_report_names_it(setup: Setup) -> None:
    body = stopped(setup)
    workspace(setup, body["id"], state="kept", reason="unsaved_work", unsaved=1, removes_at=None)
    asked = remove(setup.owner, body["id"])
    assert asked.status_code == 202, asked.text
    outcome = asked.json()["workspace_outcome"]
    assert outcome["remove_requested"] is True and outcome["remove_requested_at"]
    at = outcome["remove_requested_at"]
    (read,) = runner_list(setup)
    assert read["workspace_outcome"]["remove_requested_at"] == at
    # Decided before the runner saw the request: it stays asked.
    names: list[dict[str, Any]] = [{}, {"remove_requested_at": "2026-01-01T00:00:00Z"}]
    for named in names:
        workspace(setup, body["id"], state="kept", reason="in_use", removes_at=None, **named)
        assert get(setup, body["id"])["workspace_outcome"]["remove_requested_at"] == at
    # A second request during the removal is a new request: the old name no longer clears it.
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == body["id"])
            .values(remove_requested_at=clock.now() - timedelta(minutes=5))
        )
    first = get(setup, body["id"])["workspace_outcome"]["remove_requested_at"]
    second = remove(setup.owner, body["id"]).json()["workspace_outcome"]["remove_requested_at"]
    assert second != first
    workspace(setup, body["id"], state="kept", reason="remove_failed", removes_at=None,
              remove_requested_at=first)  # fmt: skip
    assert get(setup, body["id"])["workspace_outcome"]["remove_requested"] is True
    workspace(setup, body["id"], state="kept", reason="remove_failed", removes_at=None,
              remove_requested_at=second)  # fmt: skip
    cleared = get(setup, body["id"])["workspace_outcome"]
    assert (cleared["remove_requested"], cleared["remove_requested_at"]) == (False, None)


def test_only_a_held_clone_is_removed_by_hand(setup: Setup) -> None:
    running = placed(setup)
    refused = remove(setup.owner, running["id"])
    assert (refused.status_code, error(refused)) == (409, "conflict")
    assert refused.json()["error"]["details"] == {"reason": "workspace_not_held"}
    setup.owner.patch(f"{PATH}/{running['id']}", {"desired": "stopped"})
    refused = remove(setup.owner, running["id"])  # stopped, nothing reported yet
    assert refused.json()["error"]["details"] == {"reason": "workspace_not_held"}
    workspace(setup, running["id"], state="removed", removes_at=None)
    refused = remove(setup.owner, running["id"])  # removed already
    assert refused.json()["error"]["details"] == {"reason": "workspace_not_held"}


def test_who_has_a_clone_removed(
    setup: Setup, make_client: ClientFactory, migrated: Engine
) -> None:
    body = stopped(setup)
    workspace(setup, body["id"])
    agent = admin_agent(make_client, setup)
    refused = agent.post(f"{PATH}/{body['id']}/workspace/remove", {})
    assert (refused.status_code, error(refused)) == (403, "forbidden")
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    plain = member(make_client, migrated, "member")
    refused = remove(plain, body["id"])
    assert (refused.status_code, error(refused)) == (403, "forbidden")
    admin = member(make_client, migrated, "admin")
    asked = remove(admin, body["id"])  # `members:admin` without owning the runner
    assert asked.status_code == 202, asked.text


def test_an_old_closed_placement_with_a_held_clone_stays_in_view(setup: Setup) -> None:
    held = placed(setup)
    closed(setup, held)
    workspace(setup, held["id"], state="kept", reason="unsaved_work", unsaved=2, removes_at=None)
    gone = placed(setup)
    closed(setup, gone)
    workspace(setup, gone["id"], state="removed", removes_at=None)
    silent = placed(setup)
    closed(setup, silent)
    with setup.engine.begin() as conn:
        conn.execute(update(t.placement).values(closed_at=clock.now() - timedelta(days=90)))
    listed = setup.owner.get(f"{PATH}?closed=true").json()["items"]
    assert [p["id"] for p in listed] == [held["id"]]
    asked = remove(setup.owner, held["id"])  # however long ago it closed
    assert asked.status_code == 202, asked.text


# --- what a runner reads of closed placements ---------------------------------------------


def test_the_runner_reads_its_closed_placements_until_their_clone_is_removed(
    setup: Setup, make_client: ClientFactory
) -> None:
    body = placed(setup)
    closed(setup, body)
    assert runner_list(setup) == []
    (read,) = runner_list(setup, closed=True)
    assert (read["id"], read["active"], read["closed_reason"]) == (body["id"], False, "removed")
    assert (read["workspace_retention"], read["workspace_epoch"]) == ("24h", 1)
    assert read["workspace_outcome"] is None
    with setup.engine.begin() as conn:  # closed at any time
        conn.execute(update(t.placement).values(closed_at=clock.now() - timedelta(days=400)))
    workspace(setup, body["id"])
    assert runner_list(setup, closed=True)[0]["workspace_outcome"]["state"] == "retained"
    other = paired(make_client, setup.owner, name="other")
    attach(setup.owner, other)
    assert runner_list(setup, closed=True, runner=other) == []
    refused = workspace(setup, body["id"], runner=other)
    assert (refused.status_code, error(refused)) == (404, "not_found")
    workspace(setup, body["id"], state="removed", removes_at=None)
    assert runner_list(setup, closed=True) == []


def test_a_detached_runner_still_reads_and_reports_its_held_clones(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    setup.owner.delete(f"/projects/maintainer/maity/runners/{setup.runner.id}")
    report(setup, body, 2, state="stopped", reason="stopped_by_hub")
    assert get(setup, body["id"])["closed_reason"] == "detached"
    packet = hello(setup.client, setup.runner).json()
    assert packet["projects"] == []  # outside its projects otherwise
    (read,) = runner_list(setup, closed=True)
    assert read["id"] == body["id"]
    retained = workspace(setup, body["id"])
    assert retained.status_code == 200, retained.text
    removed = workspace(setup, body["id"], state="removed", removes_at=None)
    assert removed.status_code == 200, removed.text
    assert runner_list(setup, closed=True) == []
    retry = workspace(setup, body["id"], state="removed", removes_at=None)
    assert retry.status_code == 200, retry.text  # a retry whose first answer was lost
    assert retry.json()["workspace_epoch"] == 2


def test_no_closed_placement_of_the_runners_own_end_is_offered(setup: Setup) -> None:
    body = placed(setup)
    report(setup, body, 1)
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == body["id"])
            .values(active=None, closed_at=clock.now(), closed_reason="runner_revoked")
        )
    assert runner_list(setup, closed=True) == []


def test_the_workspace_report_takes_no_idempotency_key(setup: Setup) -> None:
    body = stopped(setup)
    first = workspace(setup, body["id"])
    second = workspace(setup, body["id"])  # a repeat states the clone again
    assert (first.status_code, second.status_code) == (200, 200)
