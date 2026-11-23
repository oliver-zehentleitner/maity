"""docs/api.md §15.7, §15.8: the placement's `session` as its runner reads it, and the runner's
`finding` on a status report, with its log lines and who reads them (tsk-n50ez67he2pz)."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, instances
from maity_hub import placements as pl
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth import credentials
from maity_hub.errors import ApiError
from maity_hub.ids import new_id
from maity_hub.routes import placements as placement_routes
from maity_hub.routes.runner import Status, _check_codes
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import count_statements, listening
from tests.test_auth_agent import signed
from tests.test_placements import REPOSITORY, allow_instances
from tests.test_runner_stream import attach, hello, member, send
from tests.test_runners import Runner, call, error, paired

PROJECT = "/projects/maintainer/maity"
AT = "2026-11-20T20:01:12Z"
FINDING: dict[str, Any] = {
    "cause": "wait_deaf",
    "seen_at": "2026-11-20T20:26:00Z",
    "signals": {
        "process": "alive",
        "exit_code": None,
        "below": "waiting",
        "pane_match": [],
        "login": "ok",
        "pickup_code": None,
    },
}
LOG = [
    {"at": AT, "line": "plc-0003: started claude-code (interactive), generation 4"},
    {
        "at": "2026-11-20T20:26:00Z",
        "line": "plc-0003: not listening since 20:09Z, a maity wait runs: restart, resuming",
    },
]
NO_SESSION = {"started_at": None, "not_listening_since": None, "paused": False, "dormant": False}
EARLIER = datetime(2026, 11, 20, 18, 0, 0, tzinfo=UTC)
STARTED = datetime(2026, 11, 20, 19, 9, 41, tzinfo=UTC)
DEAF = datetime(2026, 11, 20, 20, 9, 0, tzinfo=UTC)


@dataclass
class Watch:
    owner: flow.Human  # owns the project, the runner and the agent
    runner: Runner
    client: TestClient  # the runner's
    agent: flow.Agent
    engine: Engine


@pytest.fixture
def watch(make_client: ClientFactory, migrated: Engine) -> Watch:
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    attach(owner, runner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    allow_instances(migrated, agent.id, 2)  # the joined clone plus the placement's (§15.5)
    return Watch(owner, runner, client, agent, migrated)


def placed(w: Watch) -> dict[str, Any]:
    response = w.owner.post(
        f"{PROJECT}/placements",
        {"agent": {"id": w.agent.id}, "runner": w.runner.id, "harness": "claude-code"},
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def report(w: Watch, placement: dict[str, Any], seq: int, **body: Any) -> Any:
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
    return send(w.client, w.runner, "POST", path, payload)


def runner_items(w: Watch) -> dict[str, dict[str, Any]]:
    response = call(w.client, w.runner, "GET", "/api/v1/runner/placements")
    assert response.status_code == 200, response.text
    return {p["id"]: p for p in response.json()["items"]}


def session_of(w: Watch, placement_id: str) -> Any:
    item = runner_items(w)[placement_id]
    assert "session" in item  # the key is there, `null` included: the hub takes `finding`
    return item["session"]


def reported_for(who: Any, placement_id: str) -> dict[str, Any]:
    response = who.get(f"{PROJECT}/placements/{placement_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["reported"]
    return found


def events_of(w: Watch, kind: str) -> list[dict[str, Any]]:
    items = w.owner.get(f"{PROJECT}/events?after=0&limit=200").json()["items"]
    return [e for e in items if e["kind"] == kind]


def membership_id(w: Watch, agent_id: str | None = None) -> int:
    with w.engine.begin() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == (agent_id or w.agent.id))
        ).scalar_one()
    return found


def credential(w: Watch, instance: str) -> str:
    """Another instance credential of the agent, attached to its membership (§6.17), with no
    session yet."""
    member_id = membership_id(w)
    credential_id = new_id("credential")
    _value, verifier = credentials.issue(credential_id)
    with w.engine.begin() as conn:
        conn.execute(
            insert(t.credential).values(
                id=credential_id,
                agent_id=w.agent.id,
                instance=instance,
                verifier=verifier,
                created_at=clock.now(),
            )
        )
        conn.execute(
            insert(t.instance_attachment).values(
                credential_id=credential_id,
                membership_id=member_id,
                instance=instance,
                attached_at=clock.now(),
            )
        )
    return credential_id


def name_credential(w: Watch, placement_id: str, credential_id: str | None) -> None:
    """As the pickup's exchange sets it (§15.9)."""
    with w.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == placement_id)
            .values(credential_id=credential_id)
        )


def open_session(
    w: Watch,
    credential_id: str,
    started_at: datetime,
    *,
    ended: bool = False,
    not_listening_since: datetime | None = None,
    supervisor: str | None = None,
) -> str:
    """A session of the credential with its position row in the agent's membership, which
    holds the not-listening episode (§5.3)."""
    member_id = membership_id(w)
    session_id = new_id("session")
    with w.engine.begin() as conn:
        conn.execute(
            insert(t.agent_session).values(
                id=session_id,
                credential_id=credential_id,
                harness="Claude Code",
                model="claude-opus-5-5",
                started_at=started_at,
                last_seen_at=started_at,
                live=None if ended else True,
                ended_at=started_at if ended else None,
                supervisor=supervisor,
            )
        )
        conn.execute(
            insert(t.agent_session_project).values(
                session_id=session_id,
                membership_id=member_id,
                acknowledged_seq=0,
                not_listening_since=not_listening_since,
            )
        )
    return session_id


def set_row(w: Watch, table: Any, key: Any, **values: Any) -> None:
    with w.engine.begin() as conn:
        conn.execute(update(table).where(table.c.id == key).values(**values))


def set_episode(w: Watch, session_id: str, since: datetime | None) -> None:
    """The session's not-listening episode in the agent's membership (§5.3)."""
    p = t.agent_session_project
    member_id = membership_id(w)
    with w.engine.begin() as conn:
        conn.execute(
            update(p)
            .where(p.c.session_id == session_id, p.c.membership_id == member_id)
            .values(not_listening_since=since)
        )


def set_attachment(w: Watch, credential_id: str, **values: Any) -> None:
    """The instance's pause or dormancy in the agent's membership (§6.17)."""
    member_id = membership_id(w)
    with w.engine.begin() as conn:
        conn.execute(
            update(t.instance_attachment)
            .where(instances.attachment_of(credential_id, member_id))
            .values(**values)
        )


def available(w: Watch) -> None:
    """The member's announced state `available` (§6.12), so that only the rule under test
    decides whether the episode shows."""
    set_row(w, t.membership, membership_id(w), availability_state="available")


def hand_profile_to(w: Watch, human_id: str) -> None:
    with w.engine.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == w.agent.id)
            .values(owner_id=human_id)
        )


# --- session (§15.8) --------------------------------------------------------------------------


def test_every_runner_read_carries_the_session(watch: Watch) -> None:
    body = placed(watch)
    assert session_of(watch, body["id"]) == NO_SESSION
    [packet] = hello(watch.client, watch.runner).json()["placements"]
    assert packet["session"] == NO_SESSION
    answered = report(watch, body, 1)
    assert answered.status_code == 200, answered.text
    assert answered.json()["session"] == NO_SESSION


def test_a_foreign_placement_reads_session_null(watch: Watch) -> None:
    """The runner's owner sees the session state of their own agents only (req-1kk6pwdxdmg6)."""
    body = placed(watch)
    hand_profile_to(watch, factory.human(watch.engine, "someone-else"))
    assert session_of(watch, body["id"]) is None
    [packet] = hello(watch.client, watch.runner).json()["placements"]
    assert "session" in packet and packet["session"] is None


def test_started_at_is_the_newest_session_of_the_named_credential(watch: Watch) -> None:
    body = placed(watch)
    credential_id = credential(watch, "tst1")
    name_credential(watch, body["id"], credential_id)
    assert session_of(watch, body["id"]) == NO_SESSION  # a credential without a session
    open_session(watch, credential_id, EARLIER, ended=True)
    assert session_of(watch, body["id"])["started_at"] == "2026-11-20T18:00:00Z"  # ended counts
    open_session(watch, credential_id, STARTED)
    assert session_of(watch, body["id"]) == {**NO_SESSION, "started_at": "2026-11-20T19:09:41Z"}


def test_not_listening_since_is_the_episode_that_runs_now(watch: Watch) -> None:
    body = placed(watch)
    credential_id = credential(watch, "tst1")
    name_credential(watch, body["id"], credential_id)
    available(watch)
    session_id = open_session(watch, credential_id, STARTED, not_listening_since=DEAF)
    assert session_of(watch, body["id"])["not_listening_since"] == "2026-11-20T20:09:00Z"
    set_episode(watch, session_id, None)
    assert session_of(watch, body["id"])["not_listening_since"] is None
    set_episode(watch, session_id, DEAF)
    set_row(watch, t.agent_session, session_id, live=None, ended_at=clock.now())
    ended = session_of(watch, body["id"])  # only while the session is open
    assert ended == {**NO_SESSION, "started_at": "2026-11-20T19:09:41Z"}


def test_a_pause_of_the_membership_or_the_instance_hides_the_episode(watch: Watch) -> None:
    body = placed(watch)
    credential_id = credential(watch, "tst1")
    name_credential(watch, body["id"], credential_id)
    available(watch)
    open_session(watch, credential_id, STARTED, not_listening_since=DEAF)
    member_id = membership_id(watch)
    set_row(watch, t.membership, member_id, paused_since=clock.now())
    paused = session_of(watch, body["id"])
    assert (paused["paused"], paused["not_listening_since"]) == (True, None)
    set_row(watch, t.membership, member_id, paused_since=None)
    set_attachment(watch, credential_id, paused_since=clock.now())
    paused = session_of(watch, body["id"])
    assert (paused["paused"], paused["not_listening_since"]) == (True, None)
    set_attachment(watch, credential_id, paused_since=None)
    again = session_of(watch, body["id"])
    assert (again["paused"], again["not_listening_since"]) == (False, "2026-11-20T20:09:00Z")


def test_a_dormant_instance_reads_dormant(watch: Watch) -> None:
    body = placed(watch)
    credential_id = credential(watch, "tst1")
    name_credential(watch, body["id"], credential_id)
    set_attachment(watch, credential_id, dormant_since=clock.now())
    assert session_of(watch, body["id"])["dormant"] is True
    set_attachment(watch, credential_id, dormant_since=None)
    assert session_of(watch, body["id"])["dormant"] is False


def closed_session_of(w: Watch, placement_id: str) -> Any:
    """`session` of a closed placement, as `closed=true` lists it (§15.8)."""
    path = "/api/v1/runner/placements"
    headers = signed(w.runner, "GET", path, "closed=true")
    response = w.client.get(f"{path}?closed=true", headers=headers)
    assert response.status_code == 200, response.text
    [item] = [p for p in response.json()["items"] if p["id"] == placement_id]
    return item["session"]


def test_a_supervised_session_is_left_out_while_any_active_placement_names_it(
    watch: Watch,
) -> None:
    """§5.3: a session opened with `supervisor` whose credential *an* active placement names is
    never not listening; the closed placement the credential came from reads it the same way.
    Once no active placement names it, it is checked like any other, also on the closed one."""
    closed = placed(watch)
    credential_id = credential(watch, "tst1")
    name_credential(watch, closed["id"], credential_id)
    deleted = watch.owner.delete(f"{PROJECT}/placements/{closed['id']}")
    assert deleted.json()["active"] is False, deleted.text  # the runner never acted: at once
    allow_instances(watch.engine, watch.agent.id, 5)
    active = placed(watch)
    name_credential(watch, active["id"], credential_id)  # carried over (`carried_credential`)
    available(watch)
    open_session(
        watch, credential_id, STARTED, not_listening_since=DEAF, supervisor="maity-runner/0.9.0"
    )
    assert closed_session_of(watch, closed["id"])["not_listening_since"] is None
    assert session_of(watch, active["id"])["not_listening_since"] is None
    name_credential(watch, active["id"], None)  # no active placement names it any more
    assert closed_session_of(watch, closed["id"])["not_listening_since"] == "2026-11-20T20:09:00Z"
    assert session_of(watch, active["id"]) == NO_SESSION


def test_the_session_costs_the_same_statements_for_3_and_30_placements(watch: Watch) -> None:
    """Computed for the whole page at once (§15.8): `runner_sessions` sends a fixed number of
    statements whatever the rows. The route itself is still in `list_rows.GROWING` for the
    rest of the runner's view of a placement."""
    body = placed(watch)
    with watch.engine.begin() as conn:
        real = pl.row(conn, body["id"])
    named = [credential(watch, f"t{i:03d}") for i in range(30)]
    for i, credential_id in enumerate(named):
        open_session(watch, credential_id, STARTED, not_listening_since=DEAF if i % 2 else None)

    def page(n: int) -> list[Any]:
        return [
            SimpleNamespace(
                id=f"{real.id}-{i}",
                runner_id=real.runner_id,
                membership_id=real.membership_id,
                credential_id=named[i],
                created_by=real.created_by,
                active=True,
            )
            for i in range(n)
        ]

    def measured(n: int) -> int:
        found: dict[str, Any] = {}

        def run() -> None:
            with watch.engine.begin() as conn:
                found.update(pl.runner_sessions(conn, page(n)))

        count = count_statements(watch.engine, run, async_engines=False)
        assert len(found) == n and all(s is not None for s in found.values())
        assert {s["started_at"] for s in found.values()} == {"2026-11-20T19:09:41Z"}
        return count

    small, large = measured(3), measured(30)
    assert small > 0 and small == large, f"{small} statements for 3 rows, {large} for 30"


def test_the_runners_view_reads_the_agents_id_and_handle_and_no_name_or_picture(
    watch: Watch,
) -> None:
    """The runner gets the agent's id and handle alone (§15.8), so its view of a placement,
    read on a route every runner polls, reads neither the owner's handle for the global name
    nor the agent's picture (audit R5 batch 2, finding 4)."""
    body = placed(watch)
    with watch.engine.begin() as conn:
        row = pl.row(conn, body["id"])
    sent: list[str] = []

    def heard(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        sent.append(statement)

    with watch.engine.begin() as conn, listening(watch.engine, heard, async_engines=False):
        found = pl.for_runner(conn, row, {})
    with watch.engine.connect() as conn:
        handle = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == watch.agent.id)
        ).scalar_one()
    agent = found["agent"]
    assert (agent["id"], agent["handle"]) == (watch.agent.id, handle)
    assert not [s for s in sent if re.search(r"\bFROM (human|avatar_image)\b", s)], sent


# --- finding (§15.7) --------------------------------------------------------------------------


def test_a_finding_is_stored_as_sent_and_its_history_kept(watch: Watch) -> None:
    body = placed(watch)
    sent = {**FINDING, "log": LOG}
    answered = report(
        watch, body, 1, state="exited", reason="hung", detail="not_listening", finding=sent
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["reported"]["finding"] == sent  # the runner gets its lines back
    assert reported_for(watch.owner, body["id"])["finding"] == sent
    [event] = events_of(watch, "placement_reported")
    assert event["payload"]["finding"] == FINDING  # never with `log` (§15.10)
    assert report(watch, body, 2).status_code == 200
    assert reported_for(watch.owner, body["id"])["finding"] is None  # a report without one
    first, later = events_of(watch, "placement_reported")  # oldest first (`after=0`)
    assert (first["payload"]["finding"], later["payload"]["finding"]) == (FINDING, None)


def test_a_seen_at_after_hub_time_is_set_to_hub_time(watch: Watch) -> None:
    body = placed(watch)
    late = {**FINDING, "seen_at": "2999-01-01T00:00:00Z"}
    assert report(watch, body, 1, finding=late).status_code == 200
    seen_at = reported_for(watch.owner, body["id"])["finding"]["seen_at"]
    assert seen_at < "2999" and seen_at.endswith("Z")


@pytest.mark.parametrize("state", ["exited", "failed"])
@pytest.mark.parametrize("detail", ["not_listening", "never_joined"])
def test_hung_takes_the_watchs_details(watch: Watch, state: str, detail: str) -> None:
    body = placed(watch)
    taken = report(watch, body, 1, state=state, reason="hung", detail=detail)
    assert taken.status_code == 200, taken.text
    reported = reported_for(watch.owner, body["id"])
    assert (reported["state"], reported["reason"], reported["detail"]) == (state, "hung", detail)
    other = report(watch, body, 2, state="failed", reason="crash_loop", detail=detail)
    assert other.json()["error"]["details"]["fields"] == {"detail": "not_with_reason"}


DROP = object()


def _changed(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    found = copy.deepcopy(base)
    for key, value in changes.items():
        if value is DROP:
            del found[key]
        else:
            found[key] = value
    return found


def finding(**changes: Any) -> dict[str, Any]:
    return _changed(FINDING, changes)


def signals(**changes: Any) -> dict[str, Any]:
    return finding(signals=_changed(FINDING["signals"], changes))


def lines(*texts: str) -> dict[str, Any]:
    return finding(log=[{"at": AT, "line": text} for text in texts])


def _status(**body: Any) -> Status:
    return Status.model_validate(
        {
            "seq": 1,
            "observed_generation": 1,
            "state": "running",
            "restarts": 0,
            "target": "local",
            "since": "2026-10-22T13:00:00Z",
            **body,
        }
    )


@pytest.mark.parametrize(
    ("sent", "fields"),
    [
        (finding(cause="made_up"), {"finding.cause": "unknown"}),
        (finding(cause=DROP), {"finding.cause": "required"}),
        (finding(seen_at=DROP), {"finding.seen_at": "required"}),
        (finding(seen_at="yesterday"), {"finding.seen_at": "invalid"}),
        (finding(signals=DROP), {"finding.signals": "required"}),
        (finding(note="free text"), {"finding.note": "extra_forbidden"}),
        (signals(process="zombie"), {"finding.signals.process": "unknown"}),
        (signals(below="asleep"), {"finding.signals.below": "unknown"}),
        (signals(login="maybe"), {"finding.signals.login": "unknown"}),
        (signals(login=DROP), {"finding.signals.login": "required"}),
        (signals(pane_match=DROP), {"finding.signals.pane_match": "required"}),
        (signals(pane="usage_limit"), {"finding.signals.pane": "extra_forbidden"}),
        (signals(pane_match=["sign_in"]), {"finding.signals.pane_match": "unknown"}),
        (signals(pane_match=["login_prompt"] * 2), {"finding.signals.pane_match": "duplicate"}),
        (signals(pane_match=["usage_limit"] * 9), {"finding.signals.pane_match": "too_many"}),
        (signals(pickup_code="Not A Code"), {"finding.signals.pickup_code": "format"}),
        (signals(pickup_code="instance_quota\n"), {"finding.signals.pickup_code": "format"}),
        (signals(pickup_code="a" * 65), {"finding.signals.pickup_code": "format"}),
        (signals(exit_code="1"), {"finding.signals.exit_code": "invalid"}),
        (signals(exit_code=1.5), {"finding.signals.exit_code": "invalid"}),
        (signals(exit_code=True), {"finding.signals.exit_code": "invalid"}),
        (lines(""), {"finding.log.0.line": "empty"}),
        (lines("plc-0003: ok", ""), {"finding.log.1.line": "empty"}),
        (lines("x" * 1025), {"finding.log.0.line": "too_long"}),
        (lines("plc-0003:\tstarted"), {"finding.log.0.line": "format"}),
        (lines("plc-0003: gestartet, grün"), {"finding.log.0.line": "format"}),
        (lines("plc-0003: started\n"), {"finding.log.0.line": "format"}),
        (finding(log=[{"line": "x"}]), {"finding.log.0.at": "required"}),
        (finding(log=[{"at": "soon", "line": "x"}]), {"finding.log.0.at": "invalid"}),
        (
            finding(log=[{"at": AT, "line": "x", "level": "info"}]),
            {"finding.log.0.level": "extra_forbidden"},
        ),
        (lines(*["plc-0003: ok"] * 201), {"finding.log": "too_many"}),
        (lines(*["x" * 1024] * 25), {"finding.log": "too_large"}),
    ],
)
def test_a_finding_outside_its_lists_and_bounds_is_invalid(
    sent: dict[str, Any], fields: dict[str, str]
) -> None:
    with pytest.raises(ApiError) as refused:
        _check_codes(_status(finding=sent))
    assert (refused.value.code, refused.value.details) == ("invalid", {"fields": fields})


@pytest.mark.parametrize(
    "moment",
    [
        "1763712000",  # an epoch as a string, which the parse alone takes
        1763712000,
        "2026-11-20T20:26:00",  # no zone
        "2026-11-20T21:26:00+01:00",  # an offset
        "2026-11-20T20:26:00+00:00",
        "2026-11-20T20:26:00.5Z",  # finer than a second
        "2026-11-20 20:26:00Z",
        "2026-11-20t20:26:00z",
        "2026-13-40T20:26:00Z",  # the form, but no date
    ],
)
@pytest.mark.parametrize("where", ["finding.seen_at", "finding.log.0.at"])
def test_a_finding_time_outside_the_wire_form_is_invalid(moment: Any, where: str) -> None:
    """§1.1: RFC 3339 in UTC with `Z` and second precision, for `seen_at` and each `at`."""
    sent = (
        finding(seen_at=moment)
        if where == "finding.seen_at"
        else finding(log=[{"at": moment, "line": "plc-0003: started"}])
    )
    with pytest.raises(ApiError) as refused:
        _check_codes(_status(finding=sent))
    assert refused.value.details == {"fields": {where: "invalid"}}
    _check_codes(_status(finding=finding(log=[{"at": AT, "line": "plc-0003: started"}])))


@pytest.mark.parametrize(
    "sent",
    [
        FINDING,
        signals(pane_match=["usage_limit", "login_prompt"], login="needed"),
        signals(process="gone", exit_code=-(2**31), below="unknown"),
        signals(pickup_code="a" * 64),
        lines("x" * 1024),
        lines(*["plc-0003: ok"] * 200),
        lines(*["x" * 1024] * 24),  # 24 KiB exactly
        finding(log=[]),
    ],
)
def test_a_finding_within_its_lists_and_bounds_is_taken(sent: dict[str, Any]) -> None:
    _check_codes(_status(finding=sent))


def test_a_refused_finding_stores_nothing(watch: Watch) -> None:
    body = placed(watch)
    for sent, fields in (
        (lines(*["plc-0003: ok"] * 201), {"finding.log": "too_many"}),
        (lines(*["x" * 1024] * 25), {"finding.log": "too_large"}),
        (signals(below="asleep"), {"finding.signals.below": "unknown"}),
    ):
        refused = report(watch, body, 1, finding=sent)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["details"]["fields"] == fields
    assert reported_for(watch.owner, body["id"]) is None
    assert events_of(watch, "placement_reported") == []
    assert runner_items(watch)[body["id"]]["seq"] == 0


# --- who reads the log lines (§15.7) ------------------------------------------------------------


def test_the_log_lines_reach_their_readers_only(
    watch: Watch, make_client: ClientFactory, migrated: Engine
) -> None:
    body = placed(watch)
    sent = {**FINDING, "log": LOG}
    assert report(watch, body, 1, finding=sent).status_code == 200
    admin_agent = flow.agent(make_client, watch.owner, role="admin")
    admin = member(make_client, migrated, "admin")
    coder = member(make_client, migrated, "member")
    for reader in (watch.owner, admin_agent, admin):  # the project's owner and its admins
        assert reported_for(reader, body["id"])["finding"] == sent
    listed = watch.owner.get(f"{PROJECT}/placements").json()["items"]
    assert [p["reported"]["finding"] for p in listed] == [sent]
    for other in (coder, watch.agent):  # another member; the agent of its own placement
        assert reported_for(other, body["id"])["finding"] == FINDING
    coders = coder.get(f"{PROJECT}/placements").json()["items"]
    assert [p["reported"]["finding"] for p in coders] == [FINDING]
    # The history holds no lines yet, for any reader (§15.7, "The runner's log lines").
    reports = watch.owner.get(f"{PROJECT}/placements/{body['id']}/reports").json()["items"]
    assert [r["payload"]["finding"] for r in reports] == [FINDING]
    # The agent profile's owner reads them, a member of trust `member` though they are.
    hand_profile_to(watch, coder.id)
    assert reported_for(coder, body["id"])["finding"] == sent


def test_reads_logs_names_the_three_readers_and_never_a_bridge(
    watch: Watch, migrated: Engine
) -> None:
    body = placed(watch)
    profile_owner = factory.human(migrated, "profile-owner")
    hand_profile_to(watch, profile_owner)
    with migrated.begin() as conn:
        placement = pl.row(conn, body["id"])

        def reads(principal_id: str, trust: str, bridged: bool = False) -> bool:
            return pl.reads_logs(
                conn, placement, principal_id=principal_id, trust=trust, bridged=bridged
            )

        assert reads(watch.owner.id, "member")  # the runner's owner, whatever its trust
        assert reads(profile_owner, "member")  # the agent profile's owner
        assert reads("agt-anyone", "admin") and reads("hmn-anyone", "owner")
        assert not reads("hmn-anyone", "member") and not reads("agt-anyone", "guest")
        assert not reads(watch.owner.id, "owner", bridged=True)  # never through a bridge
        assert not reads(profile_owner, "admin", bridged=True)


def test_a_bridges_call_reads_the_finding_without_its_log(
    watch: Watch, make_client: ClientFactory, migrated: Engine
) -> None:
    """`Maity-For` (§2.3): an admin agent served through a bridge acts in its role, never as part
    of the admin team, and gets the finding without `log`. The route's own wiring (`_logs`) on
    the membership `access.membership` builds for such a call."""
    body = placed(watch)
    assert report(watch, body, 1, finding={**FINDING, "log": LOG}).status_code == 200
    admin_agent = flow.agent(make_client, watch.owner, role="admin")
    admin_membership = membership_id(watch, admin_agent.id)
    with migrated.begin() as conn:
        placement = pl.row(conn, body["id"])
        project = conn.execute(select(t.project).where(t.project.c.id == body["project_id"])).one()
        row = conn.execute(select(t.membership).where(t.membership.c.id == admin_membership)).one()
        direct = Membership(project, row, "agent")
        bridged = Membership(project, row, "agent", bridged=True)
        assert placement_routes._logs(conn, direct, placement) is True
        assert placement_routes._logs(conn, bridged, placement) is False
        shown = placement_routes._view(conn, bridged, placement)
    assert shown["reported"]["finding"] == FINDING


# --- §2.2: no credential in a log line ---------------------------------------------------------


def test_a_credential_in_a_log_line_refuses_the_report_and_stores_nothing(watch: Watch) -> None:
    body = placed(watch)
    assert report(watch, body, 1).status_code == 200
    leaked = {**FINDING, "log": [{"at": AT, "line": f"plc-0003: {watch.agent.credential}"}]}
    refused = report(watch, body, 2, state="failed", reason="auth", finding=leaked)
    assert (refused.status_code, error(refused)) == (400, "credential_in_payload")
    reported = reported_for(watch.owner, body["id"])
    assert (reported["state"], reported["finding"]) == ("running", None)
    assert len(events_of(watch, "placement_reported")) == 1
    assert runner_items(watch)[body["id"]]["seq"] == 1
