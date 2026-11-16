"""docs/api.md §15.16: the tools a runner reports, the owner's `Update now`, and the runner
reading and settling the requests (`GET /runner`, `PATCH /runner`)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, update

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_runner_stream import CAPABILITIES, hello, owner, send
from tests.test_runners import Runner, error, paired

__all__ = ["owner"]  # the fixture, shared with test_runner_stream


def tool(id: str = "claude-code", **fields: Any) -> dict[str, Any]:
    return {
        "id": id,
        "install": id != "maity",
        "update": "daily",
        "version": "2.1.320",
        "previous_version": "2.1.308",
        "latest": "2.1.320",
        "state": "current",
        "reason": None,
        "checked_at": "2026-11-12T06:00:00Z",
        "updated_at": "2026-11-12T06:01:10Z",
        "sessions_on_older": 0,
        "update_requested_at": None,
        **fields,
    }


def with_tools(*tools: dict[str, Any]) -> dict[str, Any]:
    return {**CAPABILITIES, "tools": list(tools)}


KEYS = iter(range(1, 10_000))


def advertise(client: Any, runner: Runner, capabilities: dict[str, Any]) -> Any:
    return send(
        client,
        runner,
        "PATCH",
        "/api/v1/runner",
        {"capabilities": capabilities},
        {"Idempotency-Key": f"runner-tools-{next(KEYS):05d}"},
    )


def requests_of(client: Any, runner: Runner) -> list[dict[str, Any]]:
    answer = send(client, runner, "GET", "/api/v1/runner", None)
    assert answer.status_code == 200, answer.text
    found: list[dict[str, Any]] = answer.json()["update_requests"]
    return found


def update_now(owner: flow.Human, runner: Runner, name: str) -> Any:
    return owner.post(f"/runners/{runner.id}/updates", {"tool": name})


def test_a_runner_that_reports_no_tools_shows_neither_field(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    view = owner.get(f"/runners/{runner.id}").json()
    assert "tools" not in view["capabilities"] and "update_requests" not in view
    assert requests_of(client, runner) == []


def test_the_tools_are_stored_as_reported_with_the_requests_beside_them(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    reported = [tool(), tool("maity", version="0.1.0a10", previous_version="0.1.0a9")]
    assert hello(client, runner, capabilities=with_tools(*reported)).status_code == 200
    view = owner.get(f"/runners/{runner.id}").json()
    assert view["capabilities"]["tools"] == reported
    assert view["update_requests"] == []


def test_a_tools_report_outside_the_closed_lists_is_invalid(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner)
    for bad in (
        [tool(state="failed")],  # failed needs its reason
        [tool(reason="network")],  # a reason only with failed
        [tool(state="broken")],
        [tool("maity", install=True)],  # maity is never installed by the runner
        [tool(), tool()],  # each tool once
        [tool(version="2.1.320é")],  # printable ASCII only
        [tool("vim")],
    ):
        answer = advertise(client, runner, with_tools(*bad))
        assert (answer.status_code, error(answer)) == (400, "invalid"), bad
    good = advertise(client, runner, with_tools(tool(state="failed", reason="version_failed")))
    assert good.status_code == 200, good.text


def test_update_now_is_the_owners_for_a_tool_the_runner_updates(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner, capabilities=with_tools(tool(), tool("codex", update="never")))
    for name in ("codex", "opencode"):  # updates off, or not listed: the runner decides
        refused = update_now(owner, runner, name)
        assert (refused.status_code, error(refused)) == (409, "conflict"), name
        assert refused.json()["error"]["details"]["reason"] == "updates_off"
    other = flow.human(make_client, migrated, "someone")
    assert update_now(other, runner, "claude-code").status_code == 404
    asked = update_now(owner, runner, "claude-code")
    assert asked.status_code == 202, asked.text
    [request] = asked.json()["update_requests"]
    assert request["tool"] == "claude-code"
    assert requests_of(client, runner) == [request]
    again = update_now(owner, runner, "claude-code")  # replaces the first
    [newer] = again.json()["update_requests"]
    assert requests_of(client, runner) == [newer]


def test_a_removed_runner_takes_no_request(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    hello(make_client(), runner, capabilities=with_tools(tool()))
    with migrated.begin() as conn:
        conn.execute(update(t.runner).where(t.runner.c.id == runner.id).values(active=None))
        conn.execute(
            update(t.runner)
            .where(t.runner.c.id == runner.id)
            .values(removed_at=t.runner.c.created_at)
        )
    refused = update_now(owner, runner, "claude-code")
    assert (refused.status_code, error(refused)) == (409, "invalid_transition")


def test_a_report_naming_the_request_settles_it_once_the_attempt_ended(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner, capabilities=with_tools(tool(), tool("maity", install=False)))
    update_now(owner, runner, "claude-code")
    update_now(owner, runner, "maity")
    asked = {r["tool"]: r["requested_at"] for r in requests_of(client, runner)}
    # Under way: the request stays until the attempt has ended.
    running = tool(state="updating", update_requested_at=asked["claude-code"])
    advertise(client, runner, with_tools(running, tool("maity", install=False)))
    assert {r["tool"] for r in requests_of(client, runner)} == {"claude-code", "maity"}
    # Ended (whatever the outcome), naming the request exactly: dropped, the other stays.
    ended = tool(state="failed", reason="network", update_requested_at=asked["claude-code"])
    answer = advertise(client, runner, with_tools(ended, tool("maity", install=False)))
    assert [r["tool"] for r in answer.json()["update_requests"]] == ["maity"]


def test_a_report_naming_an_older_request_leaves_the_newer_standing(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """Equality of the strings decides, never an order of times (§15.16)."""
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner, capabilities=with_tools(tool()))
    update_now(owner, runner, "claude-code")
    [second] = requests_of(client, runner)
    # The runner had read an earlier request, and decided before it read this one.
    late = tool(update_requested_at="2026-11-12T06:00:00Z")
    assert late["update_requested_at"] != second["requested_at"]
    advertise(client, runner, with_tools(late))
    assert requests_of(client, runner) == [second]
    # A hello carries the same report and settles the same way.
    hello(client, runner, capabilities=with_tools(tool(update_requested_at=second["requested_at"])))
    assert requests_of(client, runner) == []


def test_the_runner_reads_its_requests_and_a_human_cannot(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner, capabilities=with_tools(tool()))
    assert requests_of(client, runner) == []
    assert owner.get("/runner").status_code == 403


def test_two_requests_in_one_clock_reading_are_distinct(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """A report naming the first never settles the second, even when the hub's clock gave
    both the same reading (§15.16); nor does a request after the first one was settled."""
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner, capabilities=with_tools(tool()))
    # Now, so the runner's signed calls stay inside the timestamp window.
    frozen = datetime.now(UTC).replace(microsecond=123456)
    stamp = frozen.strftime("%Y-%m-%dT%H:%M:%S")
    clock.set_source(lambda: frozen)
    try:
        update_now(owner, runner, "claude-code")
        [first] = requests_of(client, runner)
        update_now(owner, runner, "claude-code")
        [second] = requests_of(client, runner)
        assert first["requested_at"] == f"{stamp}.123Z"
        assert second["requested_at"] == f"{stamp}.124Z"
        # The runner decided on the first before it read the second: the second stands.
        advertise(client, runner, with_tools(tool(update_requested_at=first["requested_at"])))
        assert requests_of(client, runner) == [second]
        # Settled: a new request in the same reading is still not the settled one.
        advertise(client, runner, with_tools(tool(update_requested_at=second["requested_at"])))
        assert requests_of(client, runner) == []
        update_now(owner, runner, "claude-code")
        [third] = requests_of(client, runner)
        assert third["requested_at"] == f"{stamp}.125Z"
    finally:
        clock.reset()


def test_a_late_report_never_gives_a_new_request_an_old_time(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """The floor is the hub's own (A353): A and B issued in one clock reading, B carried
    out, then a late report naming A. A new request C must not take B's time, or B's
    report would settle C before the runner ever read it. Also after an update-never drop,
    and whatever far-future time a runner reports."""
    runner = paired(make_client, owner)
    client = make_client()
    hello(client, runner, capabilities=with_tools(tool()))
    frozen = datetime.now(UTC).replace(microsecond=500000)
    stamp = frozen.strftime("%Y-%m-%dT%H:%M:%S")
    clock.set_source(lambda: frozen)
    try:
        update_now(owner, runner, "claude-code")
        [a] = requests_of(client, runner)
        update_now(owner, runner, "claude-code")
        [b] = requests_of(client, runner)
        advertise(client, runner, with_tools(tool(update_requested_at=b["requested_at"])))
        advertise(client, runner, with_tools(tool(update_requested_at=a["requested_at"])))
        update_now(owner, runner, "claude-code")
        [c] = requests_of(client, runner)
        assert c["requested_at"] == f"{stamp}.502Z"
        assert c["requested_at"] not in (a["requested_at"], b["requested_at"])
        advertise(client, runner, with_tools(tool(update_requested_at=b["requested_at"])))
        assert requests_of(client, runner) == [c]
        # Dropped because the tool stopped updating: the floor stays.
        advertise(client, runner, with_tools(tool(update="never")))
        assert requests_of(client, runner) == []
        advertise(client, runner, with_tools(tool(update_requested_at="9999-12-31T23:59:59.999Z")))
        answer = update_now(owner, runner, "claude-code")
        assert answer.status_code == 202, answer.text
        [d] = requests_of(client, runner)
        assert d["requested_at"] == f"{stamp}.503Z"  # the runner's value moved nothing
        # The standing view never shows the marks the hub keeps.
        view = owner.get(f"/runners/{runner.id}").json()
        assert view["update_requests"] == [d]
    finally:
        clock.reset()


def test_a_request_for_a_tool_no_longer_updated_is_dropped(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """`update: "never"`, the tool gone, or no `tools` at all: it would never be carried
    out, so the owner does not see it standing (§15.16)."""
    runner = paired(make_client, owner)
    client = make_client()
    both = with_tools(tool(), tool("codex"))
    for later in (
        with_tools(tool(update="never"), tool("codex")),
        with_tools(tool("codex")),
        CAPABILITIES,
    ):
        advertise(client, runner, both)
        update_now(owner, runner, "claude-code")
        update_now(owner, runner, "codex")
        assert {r["tool"] for r in requests_of(client, runner)} == {"claude-code", "codex"}
        advertise(client, runner, later)
        left = {r["tool"] for r in requests_of(client, runner)}
        assert left == (set() if later is CAPABILITIES else {"codex"})
