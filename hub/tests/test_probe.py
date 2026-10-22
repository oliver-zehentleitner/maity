"""docs/api.md §11: the probe — reads, the cache, reports, the open release, the worker."""

from __future__ import annotations

import threading
import time
import urllib.request
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import forge, probe
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

REPO = {"url": "https://github.com/acme/maity", "default_branch": "main"}
SHA = "d91e294c" + "0" * 32
OTHER = "e" * 40


class FakeGitHub:
    """The forge API by path; a value of `None` is a 404, an exception is raised."""

    def __init__(self) -> None:
        # The token sees the repository: a 404 below it is a missing ref.
        self.answers: dict[str, Any] = {"/repos/acme/maity": {"full_name": "acme/maity"}}
        self.calls: list[str] = []

    def __call__(self, path: str) -> Any:
        self.calls.append(path)
        # An answer for the exact path with its query wins over one for the path alone.
        answer = self.answers.get(path, self.answers.get(path.split("?")[0]))
        if isinstance(answer, Exception):
            raise answer
        return answer

    def pull(self, number: int, head: str = SHA, merged: bool = False, **extra: Any) -> None:
        self.answers[f"/repos/acme/maity/pulls/{number}"] = {
            "html_url": f"https://github.com/acme/maity/pull/{number}",
            "title": f"PR {number}",
            "state": "closed" if merged else "open",
            "draft": False,
            "head": {"sha": head},
            "base": {"ref": "main"},
            "mergeable": None if merged else True,
            "mergeable_state": "clean",
            "merged_at": "2026-10-21T12:00:00Z" if merged else None,
            "merge_commit_sha": "f" * 40,
            **extra,
        }
        self.runs(head, [("ci / sqlite", "success")])

    def runs(self, sha: str, runs: list[tuple[str, str | None]]) -> None:
        self.answers[f"/repos/acme/maity/commits/{sha}/check-runs"] = {
            "total_count": len(runs),
            "check_runs": [{"name": name, "conclusion": result} for name, result in runs],
        }
        self.answers.setdefault(f"/repos/acme/maity/commits/{sha}/status", {"statuses": []})

    def branch(self, name: str, head: str = SHA) -> None:
        quoted = name.replace("/", "%2F")
        self.answers[f"/repos/acme/maity/branches/{quoted}"] = {"commit": {"sha": head}}

    def tag(self, name: str, sha: str = SHA) -> None:
        self.answers[f"/repos/acme/maity/git/ref/tags/{name}"] = {
            "object": {"sha": sha, "type": "commit"}
        }


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(forge, "_get", fake)
    monkeypatch.setattr(forge, "_token", "test-token")
    monkeypatch.setattr(forge, "configure", lambda token: None)
    # The tests drive the probe themselves; the worker thread has its own test.
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    return fake


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", repository=REPO)
    return owner


def _project(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.project)).one()


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.event).where(t.event.c.kind == kind)).all())


def _report(**overrides: Any) -> dict[str, Any]:
    body = {
        "summary": "Adds the probe.",
        "head": SHA,
        "branch": "agent-b/probe",
        "upstream": "origin/agent-b/probe",
        "remote_head": SHA,
        "pr": {
            "number": 7,
            "url": "https://github.com/acme/maity/pull/7",
            "head": SHA,
            "state": "open",
        },
        "pr_status": "found",
        "pr_unknown_reason": None,
    }
    return {**body, **overrides}


# --- GET /probe ----------------------------------------------------------------------------


def test_without_a_token_the_probe_is_not_configured(owner: flow.Human) -> None:
    response = owner.get("/projects/maity/probe?pr=3")
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "probe_not_configured",
    )


def test_a_pull_request_read_has_the_contract_shape(owner: flow.Human, github: FakeGitHub) -> None:
    github.pull(3)
    body = owner.get("/projects/maity/probe?pr=3").json()
    assert (body["forge"], body["repository"], body["fresh"]) == ("github", "acme/maity", True)
    assert (body["branch"], body["tag"]) == (None, None)
    assert body["pr"] == {
        "number": 3,
        "found": True,
        "url": "https://github.com/acme/maity/pull/3",
        "title": "PR 3",
        "state": "open",
        "draft": False,
        "head_sha": SHA,
        "base": "main",
        "mergeable": "mergeable",
        "checks": "success",
        "checks_detail": [{"name": "ci / sqlite", "status": "success"}],
        "merged_at": None,
        "merge_sha": None,
    }
    assert [call.split("?")[0] for call in github.calls] == [
        "/repos/acme/maity/pulls/3",
        f"/repos/acme/maity/commits/{SHA}/check-runs",
        f"/repos/acme/maity/commits/{SHA}/status",
    ]


def test_an_observation_is_cached_for_max_age(owner: flow.Human, github: FakeGitHub) -> None:
    github.pull(3)
    first = owner.get("/projects/maity/probe?pr=3").json()
    cached = owner.get("/projects/maity/probe?pr=3").json()
    assert cached["fresh"] is False and cached["observed_at"] == first["observed_at"]
    assert len(github.calls) == 3  # the pull request, its check runs, its statuses
    forced = owner.get("/projects/maity/probe?pr=3&max_age=0").json()
    assert forced["fresh"] is True and len(github.calls) == 6


def test_merged_conflicting_branch_and_tag(owner: flow.Human, github: FakeGitHub) -> None:
    github.pull(4, merged=True)
    github.pull(5, head=OTHER, mergeable=False, mergeable_state="dirty")
    github.runs(OTHER, [])
    github.branch("agent-b/probe", OTHER)
    github.answers["/repos/acme/maity/git/ref/tags/v0.1.0"] = {
        "object": {"sha": "a" * 40, "type": "tag"}
    }
    github.answers[f"/repos/acme/maity/git/tags/{'a' * 40}"] = {"object": {"sha": SHA}}
    merged = owner.get("/projects/maity/probe?pr=4").json()["pr"]
    assert (merged["state"], merged["mergeable"], merged["merge_sha"]) == ("merged", None, "f" * 40)
    conflicting = owner.get("/projects/maity/probe?pr=5").json()["pr"]
    assert (conflicting["mergeable"], conflicting["checks"]) == ("conflicting", "none")
    body = owner.get("/projects/maity/probe?branch=agent-b/probe&tag=v0.1.0").json()
    assert body["branch"] == {"name": "agent-b/probe", "head_sha": OTHER, "found": True}
    assert body["tag"]["sha"] == SHA and body["tag"]["found"] is True
    assert body["tag"]["observed_at"] == body["observed_at"]
    missing = owner.get("/projects/maity/probe?branch=gone").json()["branch"]
    assert missing == {"name": "gone", "head_sha": None, "found": False}


def test_an_unanswering_forge_is_probe_unavailable_with_the_last_observation(
    owner: flow.Human, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/pulls/9"] = forge.ForgeUnavailableError("503")
    first = owner.get("/projects/maity/probe?pr=9")
    assert (first.status_code, first.json()["error"]["code"]) == (503, "probe_unavailable")
    assert first.json()["error"]["details"] == {}
    github.pull(9)
    owner.get("/projects/maity/probe?pr=9")
    github.answers["/repos/acme/maity/pulls/9"] = forge.ForgeUnavailableError("503")
    again = owner.get("/projects/maity/probe?pr=9&max_age=0").json()["error"]
    assert again["details"]["last"]["head_sha"] == SHA
    assert again["details"]["last"]["observed_at"] is not None


def test_a_probe_read_needs_a_ref(owner: flow.Human, github: FakeGitHub) -> None:
    response = owner.get("/projects/maity/probe")
    assert response.json()["error"]["details"]["fields"] == {"pr": "one_of_pr_branch_tag"}
    assert owner.get("/projects/maity/probe?branch=a%20b").json()["error"]["code"] == "invalid"


def test_an_agent_reads_the_probe_with_project_read(
    owner: flow.Human, make_client: ClientFactory, github: FakeGitHub
) -> None:
    agent = flow.agent(make_client, owner)
    github.pull(3)
    assert agent.get("/projects/maity/probe?pr=3").json()["pr"]["number"] == 3


# --- the forge client ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("runs", "summary"),
    [
        ([], "none"),
        ([("a", "success"), ("b", "skipped")], "success"),
        ([("a", "success"), ("b", None)], "pending"),
        ([("a", None), ("b", "timed_out")], "failure"),
    ],
)
def test_checks_are_summed_up(
    github: FakeGitHub, runs: list[tuple[str, str | None]], summary: str
) -> None:
    github.runs(SHA, runs)
    assert forge.checks("acme/maity", SHA)[0] == summary


def test_the_token_never_follows_a_redirect_to_another_host() -> None:
    handler = forge._SameHostOnly()
    request = urllib.request.Request("https://api.github.com/repos/a/b")
    with pytest.raises(forge.ForgeUnavailableError):
        handler.redirect_request(request, None, 301, "Moved", {}, "https://evil.example/x")
    moved = handler.redirect_request(
        request, None, 301, "Moved", {}, "https://api.github.com/repositories/1"
    )
    assert moved.full_url == "https://api.github.com/repositories/1"


# --- reports (§6.6) ------------------------------------------------------------------------


def _reported_card(owner: flow.Human, make_client: ClientFactory, **report: Any) -> tuple[Any, str]:
    agent = flow.agent(make_client, owner)
    card = owner.post("/projects/maity/tasks", {"title": "A card"}).json()
    assert agent.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200
    stored = agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(**report))
    assert stored.status_code == 200, stored.text
    assert stored.json()["report"]["observed"] is None  # never awaited inside the write
    return agent, card["id"]


def test_the_probe_fills_a_report(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, card_id) is True
    report = owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]
    assert report["mismatch"] is False
    observed = report["observed"]
    assert (observed["pr_state"], observed["pr_head_sha"], observed["checks"]) == (
        "open",
        SHA,
        "success",
    )
    assert observed["branch_head_sha"] == SHA and observed["observed_at"] is not None
    [event] = _events(migrated, "probe_observed")
    assert event.audience == [f"member:{agent.id}", "role:admin"]
    assert event.payload == {"task": card_id, "observed": observed, "mismatch": False}
    assert probe.observe_report(migrated, card_id, max_age=60) is False  # nothing new


def test_a_head_the_forge_does_not_show_is_a_mismatch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, head=OTHER)
    github.branch("agent-b/probe")
    _, card_id = _reported_card(owner, make_client)
    probe.observe_report(migrated, card_id)
    assert owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]["mismatch"] is True


def test_a_pull_request_the_forge_does_not_have_is_a_mismatch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/pulls/7"] = None
    github.branch("agent-b/probe")
    _, card_id = _reported_card(owner, make_client)
    probe.observe_report(migrated, card_id)
    report = owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]
    assert (report["mismatch"], report["observed"]["pr_state"]) == (True, None)
    assert report["observed"]["branch_head_sha"] == SHA


def test_a_deleted_branch_is_no_mismatch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported_card(owner, make_client)
    probe.observe_report(migrated, card_id)
    report = owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]
    assert (report["mismatch"], report["observed"]["branch_head_sha"]) == (False, None)
    assert report["observed"]["pr_state"] == "merged"


def test_a_failing_probe_leaves_the_report_for_the_next_round(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/branches/agent-b%2Fprobe"] = forge.ForgeUnavailableError("x")
    _, card_id = _reported_card(owner, make_client)
    probe.sweep(migrated)  # logged, not raised
    assert owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]["observed"] is None
    github.branch("agent-b/probe")
    github.pull(7)
    probe.sweep(migrated)
    assert owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]["observed"] is not None


def test_the_worker_probes_right_after_a_report(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    monkeypatch.setattr(forge, "_get", fake)
    monkeypatch.setattr(forge, "_token", None)  # restored after the test
    fake.pull(7)
    fake.branch("agent-b/probe")

    def with_token(**overrides: Any) -> Any:  # every app starts its worker
        return make_client(forge_github_token="test-token", **overrides)

    human = flow.human(with_token, migrated)
    flow.project(human, "maity", repository=REPO)
    agent = flow.agent(with_token, human)
    card = human.post("/projects/maity/tasks", {"title": "A card"}).json()
    agent.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    agent.post(f"/projects/maity/tasks/{card['id']}/report", _report())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        report = human.get(f"/projects/maity/tasks/{card['id']}").json()["report"]
        if report["observed"] is not None:
            break
        time.sleep(0.05)
    assert report["observed"] is not None and report["mismatch"] is False


# --- the open release (§6.7) ---------------------------------------------------------------


def test_the_release_is_refreshed_and_turns_ready(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    release = owner.post(
        "/projects/maity/tasks",
        {"title": "0.1.0", "kind": "release", "release": {"version": "0.1.0"}},
    ).json()
    owner.patch(
        f"/projects/maity/tasks/{release['id']}",
        {"release": {"pull_requests_typed": [{"number": 1}]}},
    )
    github.pull(1)
    github.answers["/repos/acme/maity/git/ref/tags/v0.1.0"] = None
    project_id = _project(migrated).id
    assert len(_events(migrated, "release_ready")) == 1  # empty at creation, so ready
    assert probe.observe_release(migrated, project_id) is True
    view = owner.get(f"/projects/maity/tasks/{release['id']}").json()["release"]
    assert view["readiness"]["blocking"] == [{"reason": "pr_open", "pr": 1}]
    assert view["tag"]["found"] is False and view["tag"]["observed_at"] is not None
    events = _events(migrated, "probe_observed")  # one per changed ref
    assert [set(e.payload["observations"]) for e in events] == [{"pr:1"}, {"tag:v0.1.0"}]
    github.pull(1, merged=True)
    assert probe.observe_release(migrated, project_id, max_age=0) is True
    assert owner.get(f"/projects/maity/tasks/{release['id']}").json()["release"]["readiness"] == {
        "ready": True,
        "blocking": [],
    }
    assert len(_events(migrated, "release_ready")) == 2  # announced again on this turn
    assert probe.observe_release(migrated, project_id, max_age=0) is False  # nothing changed
    assert len(_events(migrated, "probe_observed")) == 3


def test_whoever_sees_the_merge_first_announces_it(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    """GET /probe reads the merge before the worker does: the release card still
    gets its probe_observed, and release_ready comes at once, not a sweep later."""
    release = owner.post(
        "/projects/maity/tasks",
        {"title": "0.1.0", "kind": "release", "release": {"version": "0.1.0"}},
    ).json()
    owner.patch(
        f"/projects/maity/tasks/{release['id']}",
        {"release": {"pull_requests_typed": [{"number": 1}]}},
    )
    github.pull(1)
    github.answers["/repos/acme/maity/git/ref/tags/v0.1.0"] = None
    project_id = _project(migrated).id
    probe.observe_release(migrated, project_id)
    before = len(_events(migrated, "probe_observed"))
    ready_before = len(_events(migrated, "release_ready"))
    github.pull(1, merged=True)
    seen = owner.get("/projects/maity/probe?pr=1&max_age=0").json()["pr"]
    assert seen["state"] == "merged"
    events = _events(migrated, "probe_observed")
    assert len(events) == before + 1
    assert events[-1].payload["task"] == release["id"]
    assert events[-1].payload["observations"]["pr:1"]["state"] == "merged"
    assert len(_events(migrated, "release_ready")) == ready_before + 1
    assert probe.observe_release(migrated, project_id, max_age=0) is False  # already known


# --- the review round on the probe -----------------------------------------------------------


def test_a_repository_the_token_cannot_see_leaves_the_report_unverified(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity"] = None  # private, and the token has no access
    github.answers["/repos/acme/maity/pulls/7"] = None
    github.answers["/repos/acme/maity/branches/agent-b%2Fprobe"] = None
    _, card_id = _reported_card(owner, make_client)
    with pytest.raises(forge.ForgeUnavailableError):
        probe.observe_report(migrated, card_id)
    report = owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]
    assert (report["observed"], report["mismatch"]) == (None, None)  # never a false mismatch
    answer = owner.get("/projects/maity/probe?pr=7")
    assert (answer.status_code, answer.headers["Maity-Error"]) == (503, "probe_unavailable")


def test_an_answer_of_another_shape_is_unavailable_not_a_crash(
    owner: flow.Human, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/pulls/3"] = {"state": "open"}  # no head, no base
    answer = owner.get("/projects/maity/probe?pr=3")
    assert (answer.status_code, answer.headers["Maity-Error"]) == (503, "probe_unavailable")


def test_a_report_replaced_within_the_same_second_keeps_its_own_verdict(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github.pull(7)
    github.branch("agent-b/probe")
    _, card_id = _reported_card(owner, make_client)
    real_observe = probe.observe

    def a_second_report_arrives(*args: Any, **kwargs: Any) -> probe.Observation:
        observation = real_observe(*args, **kwargs)
        with migrated.begin() as conn:  # same reported_at, another head
            report = conn.execute(
                select(t.card.c.report).where(t.card.c.id == card_id)
            ).scalar_one()
            replaced = {**report, "head": OTHER, "remote_head": OTHER}
            conn.execute(t.card.update().where(t.card.c.id == card_id).values(report=replaced))
        return observation

    monkeypatch.setattr(probe, "observe", a_second_report_arrives)
    assert probe.observe_report(migrated, card_id) is False
    report = owner.get(f"/projects/maity/tasks/{card_id}").json()["report"]
    assert (report["head"], report["observed"]) == (OTHER, None)


def test_only_a_changed_verdict_is_announced_again(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7)
    github.branch("agent-b/probe")
    _, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, card_id) is True
    time.sleep(1.1)  # observed_at moves on; nothing else does
    probe.observe_report(migrated, card_id, max_age=0)
    reported = [e for e in _events(migrated, "probe_observed") if e.payload.get("task") == card_id]
    assert len(reported) == 1


def test_a_round_ends_at_the_first_read_the_forge_does_not_answer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    for _ in range(3):
        _reported_card(owner, make_client)
    github.answers["/repos/acme/maity/branches/agent-b%2Fprobe"] = forge.ForgeUnavailableError(
        "rate limited"
    )
    probe.sweep(migrated)
    assert len(github.calls) == 1  # not one timeout per card


def test_a_set_stop_ends_the_round_before_the_next_read(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _reported_card(owner, make_client)
    stop = threading.Event()
    stop.set()
    probe.sweep(migrated, stop)
    assert github.calls == []


def test_a_new_repository_starts_without_the_old_observations(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(3)
    owner.get("/projects/maity/probe?pr=3")
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_observation)).all()
    moved = owner.patch(
        "/projects/maity", {"repository": {"url": "https://github.com/acme/maity-next"}}
    )
    assert moved.status_code == 200, moved.text
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_observation)).all() == []
