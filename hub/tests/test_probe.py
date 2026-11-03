"""docs/api.md §11: the probe — reads, the cache, reports, the open release, the worker."""

from __future__ import annotations

import threading
import time
import urllib.request
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, forge, probe
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory

REPO = {"url": "https://github.com/acme/maity", "default_branch": "main"}
SHA = "d91e294c" + "0" * 32
OTHER = "e" * 40
TOKEN = "test-token"
READER = forge.Forge(TOKEN)  # what the app builds from the settings
REAL_GET = forge.Forge._get


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
def settings(settings: Settings, request: pytest.FixtureRequest) -> Settings:
    """The operator's forge token, as the environment sets it, for the tests that
    ask for the probe; the others run without one."""
    if {"probe", "github"} & set(request.fixturenames):
        return replace(
            settings, forge_github_token=TOKEN, forge_instance_namespaces=frozenset({"maintainer"})
        )
    return settings


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(forge.Forge, "_get", lambda _self, path, **_: fake(path))
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
        "why": {"none": "a test report, nothing to keep"},  # §6.23
    }
    return {**body, **overrides}


# --- GET /probe ----------------------------------------------------------------------------


def test_without_a_token_the_probe_is_not_configured(owner: flow.Human) -> None:
    response = owner.get("/projects/maintainer/maity/probe?pr=3")
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "probe_not_configured",
    )


def test_a_pull_request_read_has_the_contract_shape(owner: flow.Human, github: FakeGitHub) -> None:
    github.pull(3)
    body = owner.get("/projects/maintainer/maity/probe?pr=3").json()
    assert (body["forge"], body["repository"], body["fresh"]) == ("github", "acme/maity", True)
    assert (body["branch"], body["tag"], body["commit"]) == (None, None, None)
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
        "required_check": None,
        "merged_at": None,
        "merge_sha": None,
    }
    assert [call.split("?")[0] for call in github.calls] == [
        "/repos/acme/maity/pulls/3",
        f"/repos/acme/maity/commits/{SHA}/check-runs",
        f"/repos/acme/maity/commits/{SHA}/status",
    ]


def test_an_observation_is_cached_for_max_age(
    owner: flow.Human, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "FORCED_FLOOR", 0)  # the floor has its own test
    github.pull(3)
    first = owner.get("/projects/maintainer/maity/probe?pr=3").json()
    cached = owner.get("/projects/maintainer/maity/probe?pr=3").json()
    assert cached["fresh"] is False and cached["observed_at"] == first["observed_at"]
    assert len(github.calls) == 3  # the pull request, its check runs, its statuses
    forced = owner.get("/projects/maintainer/maity/probe?pr=3&max_age=0").json()
    assert forced["fresh"] is True and len(github.calls) == 6


def test_a_forced_read_waits_the_floor(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    """§11.4: `max_age=0` asks the forge at most once per 30 seconds per project and
    target; within them the observation answers with `fresh: false`."""
    github.pull(3)
    first = owner.get("/projects/maintainer/maity/probe?pr=3&max_age=0").json()
    again = owner.get("/projects/maintainer/maity/probe?pr=3&max_age=0").json()
    assert (first["fresh"], again["fresh"]) == (True, False)
    assert len(github.calls) == 3
    with migrated.begin() as conn:
        conn.execute(
            update(t.forge_observation).values(
                observed_at=clock.now() - timedelta(seconds=probe.FORCED_FLOOR)
            )
        )
    assert owner.get("/projects/maintainer/maity/probe?pr=3&max_age=0").json()["fresh"] is True
    assert len(github.calls) == 6


def test_the_first_found_release_tag_marks_the_project_released_for_good(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.1: `released_at` is set once, by the probe finding a release's tag, whether
    the release card is done or not; a tag of no release does not count."""
    github.tag("v9.9.9")
    assert owner.get("/projects/maintainer/maity/probe?tag=v9.9.9").json()["tag"]["found"]
    assert _project(migrated).released_at is None
    release = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "0.1.0", "kind": "release", "release": {"version": "0.1.0"}},
    ).json()
    github.answers["/repos/acme/maity/git/ref/tags/v0.1.0"] = None
    project_id = _project(migrated).id
    probe.observe_release(migrated, READER, project_id)
    assert _project(migrated).released_at is None
    version = _project(migrated).rules_version
    github.tag("v0.1.0")
    probe.observe_release(migrated, READER, project_id, max_age=0)
    marked = _project(migrated)
    assert marked.released_at is not None and marked.rules_version == version + 1
    event = _events(migrated, "state_changed")[-1]
    assert event.payload == {
        "old": "build",
        "new": "build",
        "reason": None,
        "released_at": clock.rfc3339(marked.released_at),
        "rules_version": version + 1,
    }
    assert owner.get("/projects/maintainer/maity").json()["released_at"] == clock.rfc3339(
        marked.released_at
    )
    rules = owner.get("/projects/maintainer/maity/rules").text
    assert f"Released since {marked.released_at.date().isoformat()}." in rules
    assert "migrations stay backward compatible" in rules
    # Never cleared, never moved: another read of the tag and a state change keep it.
    probe.observe_release(migrated, READER, project_id, max_age=0)
    owner.patch(f"/projects/maintainer/maity/tasks/{release['id']}", {"status": "cancelled"})
    owner.patch("/projects/maintainer/maity", {"state": "review", "reason": "next"})
    assert _project(migrated).released_at == marked.released_at
    assert len([e for e in _events(migrated, "state_changed") if "released_at" in e.payload]) == 1


def test_merged_conflicting_branch_and_tag(owner: flow.Human, github: FakeGitHub) -> None:
    github.pull(4, merged=True)
    github.pull(5, head=OTHER, mergeable=False, mergeable_state="dirty")
    github.runs(OTHER, [])
    github.branch("agent-b/probe", OTHER)
    github.answers["/repos/acme/maity/git/ref/tags/v0.1.0"] = {
        "object": {"sha": "a" * 40, "type": "tag"}
    }
    github.answers[f"/repos/acme/maity/git/tags/{'a' * 40}"] = {"object": {"sha": SHA}}
    merged = owner.get("/projects/maintainer/maity/probe?pr=4").json()["pr"]
    assert (merged["state"], merged["mergeable"], merged["merge_sha"]) == ("merged", None, "f" * 40)
    conflicting = owner.get("/projects/maintainer/maity/probe?pr=5").json()["pr"]
    assert (conflicting["mergeable"], conflicting["checks"]) == ("conflicting", "none")
    body = owner.get("/projects/maintainer/maity/probe?branch=agent-b/probe&tag=v0.1.0").json()
    assert body["branch"] == {"name": "agent-b/probe", "head_sha": OTHER, "found": True}
    assert body["tag"]["sha"] == SHA and body["tag"]["found"] is True
    # The tag carries its own time (§11); the answer's is the oldest of its reads, and the
    # branch and the tag are read one after the other, maybe in different seconds.
    assert body["observed_at"] <= body["tag"]["observed_at"]
    missing = owner.get("/projects/maintainer/maity/probe?branch=gone").json()["branch"]
    assert missing == {"name": "gone", "head_sha": None, "found": False}


def test_a_spent_rate_limit_is_probe_unavailable_with_retry_at(
    owner: flow.Human, github: FakeGitHub
) -> None:
    """§11.4: while the source's budget is spent the probe says when it reads again."""
    from datetime import UTC, datetime, timedelta

    at = (datetime.now(UTC) + timedelta(minutes=10)).replace(microsecond=0)
    github.answers["/repos/acme/maity/pulls/9"] = forge.ForgeUnavailableError(
        "spent", rate_limited=True, retry_at=at
    )
    answer = owner.get("/projects/maintainer/maity/probe?pr=9")
    assert (answer.status_code, answer.json()["error"]["code"]) == (503, "probe_unavailable")
    assert answer.json()["error"]["details"]["retry_at"] == clock.rfc3339(at)


def test_an_unanswering_forge_is_probe_unavailable_with_the_last_observation(
    owner: flow.Human, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "FORCED_FLOOR", 0)
    github.answers["/repos/acme/maity/pulls/9"] = forge.ForgeUnavailableError("503")
    first = owner.get("/projects/maintainer/maity/probe?pr=9")
    assert (first.status_code, first.json()["error"]["code"]) == (503, "probe_unavailable")
    assert first.json()["error"]["details"] == {}
    github.pull(9)
    owner.get("/projects/maintainer/maity/probe?pr=9")
    github.answers["/repos/acme/maity/pulls/9"] = forge.ForgeUnavailableError("503")
    again = owner.get("/projects/maintainer/maity/probe?pr=9&max_age=0").json()["error"]
    assert again["details"]["last"]["head_sha"] == SHA
    assert again["details"]["last"]["observed_at"] is not None


def test_a_probe_read_needs_a_ref(owner: flow.Human, github: FakeGitHub) -> None:
    response = owner.get("/projects/maintainer/maity/probe")
    assert response.json()["error"]["details"]["fields"] == {"pr": "one_of_pr_branch_tag_commit"}
    assert (
        owner.get("/projects/maintainer/maity/probe?branch=a%20b").json()["error"]["code"]
        == "invalid"
    )


def test_an_agent_reads_the_probe_with_project_read(
    owner: flow.Human, make_client: ClientFactory, github: FakeGitHub
) -> None:
    agent = flow.agent(make_client, owner)
    github.pull(3)
    assert agent.get("/projects/maintainer/maity/probe?pr=3").json()["pr"]["number"] == 3


@pytest.mark.parametrize(
    ("answer", "reason"), [(True, "private_without_grant"), (None, "no_grant")]
)
def test_a_private_repository_is_not_configured_and_only_an_admin_sees_why(
    owner: flow.Human,
    make_client: ClientFactory,
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
    answer: bool | None,
    reason: str,
) -> None:
    """§11.4: the instance token reads public repositories only."""
    agent = flow.agent(make_client, owner)
    sent: list[str] = []

    def send(_self: forge.Forge, path: str, query: Any = None) -> Any:
        sent.append(path)
        return None if answer is None else {"private": answer}

    monkeypatch.setattr(forge.Forge, "_get", REAL_GET)
    monkeypatch.setattr(forge.Forge, "_send", send)
    monkeypatch.setattr(forge, "_public", {})
    refused = owner.get("/projects/maintainer/maity/probe?pr=3")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "probe_not_configured"
    assert refused.json()["error"]["details"] == {"reason": reason}
    hidden = agent.get("/projects/maintainer/maity/probe?pr=3").json()["error"]
    assert (hidden["code"], hidden["details"]) == ("probe_not_configured", {})
    assert sent == ["/repos/acme/maity"]


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
    assert READER.checks("acme/maity", SHA)[0] == summary


def test_the_token_never_follows_a_redirect_to_another_host() -> None:
    handler = forge._SameHostOnly()
    request = urllib.request.Request("https://api.github.com/repos/a/b")
    with pytest.raises(forge.ForgeUnavailableError):
        handler.redirect_request(request, None, 301, "Moved", {}, "https://evil.example/x")
    with pytest.raises(forge.NotCoveredError):  # nor within the API host (§11.4)
        handler.redirect_request(
            request, None, 301, "Moved", {}, "https://api.github.com/repositories/1"
        )


# --- reports (§6.6) ------------------------------------------------------------------------


def _reported_card(owner: flow.Human, make_client: ClientFactory, **report: Any) -> tuple[Any, str]:
    agent = flow.agent(make_client, owner)
    card = owner.post("/projects/maintainer/maity/tasks", {"title": "A card"}).json()
    assert agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {}).status_code == 200
    stored = agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", _report(**report))
    assert stored.status_code == 200, stored.text
    assert stored.json()["report"]["observed"] is None  # never awaited inside the write
    return agent, card["id"]


def test_the_probe_fills_a_report(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    report = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]
    assert report["mismatch"] is False
    observed = report["observed"]
    assert (observed["pr_state"], observed["pr_head_sha"], observed["checks"]) == (
        "open",
        SHA,
        "success",
    )
    assert observed["branch_head_sha"] == SHA and observed["observed_at"] is not None
    [event] = _events(migrated, "probe_observed")
    # The holder alone: an admin reads it without being named, and is not woken (§8.2).
    assert event.audience == [f"instance:{agent.id}#{agent.instance}"]
    read = owner.get("/projects/maintainer/maity/events").json()
    assert any(e["kind"] == "probe_observed" for e in read["items"])
    assert event.payload == {"task": card_id, "observed": observed, "mismatch": False}
    assert probe.observe_report(migrated, READER, card_id, max_age=60) is False  # nothing new


def test_a_head_the_forge_does_not_show_is_a_mismatch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, head=OTHER)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert (
        owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]["mismatch"]
        is True
    )
    [event] = _events(migrated, "probe_observed")
    assert event.audience == [f"instance:{agent.id}#{agent.instance}", "trust:admin"]


def test_an_observation_of_a_closed_card_wakes_nobody_without_a_mismatch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7)
    github.branch("agent-b/probe")
    _, card_id = _reported_card(owner, make_client)
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(status="done"))
    assert probe.observe_report(migrated, READER, card_id) is True
    [event] = _events(migrated, "probe_observed")
    assert event.audience == []
    assert event.payload["mismatch"] is False


def test_a_merged_head_other_than_the_reported_on_a_closed_card_wakes_nobody_and_stays_readable(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, head=OTHER, state="closed", merged=True)
    _, card_id = _reported_card(owner, make_client)
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(status="done"))
    probe.observe_report(migrated, READER, card_id)
    [event] = _events(migrated, "probe_observed")
    assert event.audience == []
    report = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]
    assert (report["mismatch"], report["observed"]["pr_state"]) == (True, "merged")
    assert report["observed"]["pr_head_sha"] == OTHER


def test_an_observation_of_a_closed_card_with_a_mismatch_still_reaches_who_must_act(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/pulls/7"] = None
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(status="done"))
    probe.observe_report(migrated, READER, card_id)
    [event] = _events(migrated, "probe_observed")
    assert event.audience == [f"instance:{agent.id}#{agent.instance}", "trust:admin"]


def test_a_pull_request_the_forge_does_not_have_is_a_mismatch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/pulls/7"] = None
    github.branch("agent-b/probe")
    _, card_id = _reported_card(owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    report = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]
    assert (report["mismatch"], report["observed"]["pr_state"]) == (True, None)
    assert report["observed"]["branch_head_sha"] == SHA


def test_a_deleted_branch_is_no_mismatch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported_card(owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    report = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]
    assert (report["mismatch"], report["observed"]["branch_head_sha"]) == (False, None)
    assert report["observed"]["pr_state"] == "merged"


def test_a_failing_probe_leaves_the_report_for_the_next_round(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/branches/agent-b%2Fprobe"] = forge.ForgeUnavailableError("x")
    _, card_id = _reported_card(owner, make_client)
    probe.sweep(migrated, READER)  # logged, not raised
    assert (
        owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]["observed"]
        is None
    )
    github.branch("agent-b/probe")
    github.pull(7)
    probe.sweep(migrated, READER)
    assert (
        owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]["observed"]
        is not None
    )


def test_the_worker_probes_right_after_a_report(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGitHub()
    monkeypatch.setattr(forge.Forge, "_get", lambda _self, path, **_: fake(path))
    fake.pull(7)
    fake.branch("agent-b/probe")

    def with_token(**overrides: Any) -> Any:  # every app starts its worker
        return make_client(
            forge_instance_namespaces=frozenset({"maintainer"}),
            forge_github_token=TOKEN,
            **overrides,
        )

    human = flow.human(with_token, migrated)
    flow.project(human, "maity", repository=REPO)
    agent = flow.agent(with_token, human)
    card = human.post("/projects/maintainer/maity/tasks", {"title": "A card"}).json()
    agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", _report())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        report = human.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["report"]
        if report["observed"] is not None:
            break
        time.sleep(0.05)
    assert report["observed"] is not None and report["mismatch"] is False


# --- the open release (§6.7) ---------------------------------------------------------------


def test_the_release_is_refreshed_and_turns_ready(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    release = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "0.1.0", "kind": "release", "release": {"version": "0.1.0"}},
    ).json()
    owner.patch(
        f"/projects/maintainer/maity/tasks/{release['id']}",
        {"release": {"pull_requests_typed": [{"number": 1}]}},
    )
    github.pull(1)
    github.answers["/repos/acme/maity/git/ref/tags/v0.1.0"] = None
    project_id = _project(migrated).id
    assert len(_events(migrated, "release_ready")) == 1  # empty at creation, so ready
    assert probe.observe_release(migrated, READER, project_id) is True
    view = owner.get(f"/projects/maintainer/maity/tasks/{release['id']}").json()["release"]
    assert view["readiness"]["blocking"] == [{"reason": "pr_open", "pr": 1}]
    assert view["tag"]["found"] is False and view["tag"]["observed_at"] is not None
    events = _events(migrated, "probe_observed")  # one per changed ref
    assert [set(e.payload["observations"]) for e in events] == [{"pr:1"}, {"tag:v0.1.0"}]
    github.pull(1, merged=True)
    assert probe.observe_release(migrated, READER, project_id, max_age=0) is True
    assert owner.get(f"/projects/maintainer/maity/tasks/{release['id']}").json()["release"][
        "readiness"
    ] == {
        "ready": True,
        "blocking": [],
    }
    assert len(_events(migrated, "release_ready")) == 2  # announced again on this turn
    assert (
        probe.observe_release(migrated, READER, project_id, max_age=0) is False
    )  # nothing changed
    assert len(_events(migrated, "probe_observed")) == 3


def test_whoever_sees_the_merge_first_announces_it(
    owner: flow.Human, migrated: Engine, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "FORCED_FLOOR", 0)
    """GET /probe reads the merge before the worker does: the release card still
    gets its probe_observed, and release_ready comes at once, not a sweep later."""
    release = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "0.1.0", "kind": "release", "release": {"version": "0.1.0"}},
    ).json()
    owner.patch(
        f"/projects/maintainer/maity/tasks/{release['id']}",
        {"release": {"pull_requests_typed": [{"number": 1}]}},
    )
    github.pull(1)
    github.answers["/repos/acme/maity/git/ref/tags/v0.1.0"] = None
    project_id = _project(migrated).id
    probe.observe_release(migrated, READER, project_id)
    before = len(_events(migrated, "probe_observed"))
    ready_before = len(_events(migrated, "release_ready"))
    github.pull(1, merged=True)
    seen = owner.get("/projects/maintainer/maity/probe?pr=1&max_age=0").json()["pr"]
    assert seen["state"] == "merged"
    events = _events(migrated, "probe_observed")
    assert len(events) == before + 1
    assert events[-1].payload["task"] == release["id"]
    assert events[-1].payload["observations"]["pr:1"]["state"] == "merged"
    assert len(_events(migrated, "release_ready")) == ready_before + 1
    assert probe.observe_release(migrated, READER, project_id, max_age=0) is False  # already known


# --- the review round on the probe -----------------------------------------------------------


def test_a_repository_the_token_cannot_see_leaves_the_report_unverified(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity"] = None  # private, and the token has no access
    github.answers["/repos/acme/maity/pulls/7"] = None
    github.answers["/repos/acme/maity/branches/agent-b%2Fprobe"] = None
    _, card_id = _reported_card(owner, make_client)
    with pytest.raises(forge.ForgeUnavailableError):
        probe.observe_report(migrated, READER, card_id)
    report = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]
    assert (report["observed"], report["mismatch"]) == (None, None)  # never a false mismatch
    answer = owner.get("/projects/maintainer/maity/probe?pr=7")
    assert (answer.status_code, answer.headers["Maity-Error"]) == (503, "probe_unavailable")


def test_an_answer_of_another_shape_is_unavailable_not_a_crash(
    owner: flow.Human, github: FakeGitHub
) -> None:
    github.answers["/repos/acme/maity/pulls/3"] = {"state": "open"}  # no head, no base
    answer = owner.get("/projects/maintainer/maity/probe?pr=3")
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
    assert probe.observe_report(migrated, READER, card_id) is False
    report = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]
    assert (report["head"], report["observed"]) == (OTHER, None)


def test_only_a_changed_verdict_is_announced_again(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7)
    github.branch("agent-b/probe")
    _, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    time.sleep(1.1)  # observed_at moves on; nothing else does
    probe.observe_report(migrated, READER, card_id, max_age=0)
    reported = [e for e in _events(migrated, "probe_observed") if e.payload.get("task") == card_id]
    assert len(reported) == 1


def _reported_events(engine: Engine, card_id: str) -> list[Any]:
    return [e for e in _events(engine, "probe_observed") if e.payload.get("task") == card_id]


def _report_again(agent: flow.Human, card_id: str) -> None:
    again = agent.post(f"/projects/maintainer/maity/tasks/{card_id}/report", _report())
    assert again.status_code == 200, again.text
    assert again.json()["report"]["observed"] is None


def test_a_new_report_on_an_unchanged_pull_request_wakes_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """The agent reports again; the forge says what it said for the last report: stored on
    the new report and emitted to nobody, so the views that read every event show it filled
    (req-658tp9mj77ny)."""
    github.pull(7)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    _report_again(agent, card_id)
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    report = owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["report"]
    assert report["observed"]["pr_head_sha"] == SHA and report["mismatch"] is False
    told, quiet = _reported_events(migrated, card_id)
    assert told.audience and quiet.audience == []
    assert quiet.payload == {"task": card_id, "observed": report["observed"], "mismatch": False}
    read = owner.get("/projects/maintainer/maity/events").json()["items"]
    assert [e["seq"] for e in read if e["kind"] == "probe_observed"][-1] == quiet.seq


def test_a_new_report_the_forge_contradicts_again_wakes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """A second wrong head is news to the holder, though the forge says what it said."""
    github.pull(7, head=OTHER)
    github.branch("agent-b/probe", head=OTHER)
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    third = "c" * 40
    pr = {**_report()["pr"], "head": third}
    again = agent.post(
        f"/projects/maintainer/maity/tasks/{card_id}/report",
        _report(head=third, remote_head=third, pr=pr),
    )
    assert again.status_code == 200, again.text
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    first, second = _reported_events(migrated, card_id)
    assert first.payload["mismatch"] is second.payload["mismatch"] is True
    assert second.audience == first.audience != []


def test_a_new_holder_is_told_what_the_last_one_was(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """The last observation told the earlier holder: the one now holding the card is told it."""
    github.pull(7)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    _report_again(agent, card_id)
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(claim_instance="zz99"))
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    _, second = _reported_events(migrated, card_id)
    assert second.audience == [f"instance:{agent.id}#zz99"]


def test_an_observation_that_woke_nobody_told_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Observed on a closed card (to nobody), then reopened: the holder's next report is told."""
    github.pull(7)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(status="done"))
    assert probe.observe_report(migrated, READER, card_id) is True
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(status="in_progress"))
    _report_again(agent, card_id)
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    quiet, told = _reported_events(migrated, card_id)
    assert quiet.audience == [] and told.audience == [f"instance:{agent.id}#{agent.instance}"]


@pytest.mark.parametrize(
    "change",
    ["checks", "pr_state", "pr_head_sha", "branch_head_sha"],
)
def test_a_new_report_wakes_when_the_pull_request_changed(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    change: str,
) -> None:
    """Each part of the observation, changed since the last report's, is announced."""
    github.pull(7)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    _report_again(agent, card_id)
    if change == "checks":
        github.runs(SHA, [("ci / sqlite", "failure")])
    elif change == "pr_state":
        github.pull(7, merged=True)
    elif change == "pr_head_sha":
        github.pull(7, head=OTHER)
    else:
        github.branch("agent-b/probe", head=OTHER)
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    first, second = _reported_events(migrated, card_id)
    assert first.payload["observed"][change] != second.payload["observed"][change]


def test_a_report_after_its_announced_one_was_redacted_is_announced(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """A redacted event says nothing: the next report's observation is told again."""
    github.pull(7)
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    with migrated.begin() as conn:
        conn.execute(
            update(t.event).where(t.event.c.kind == "probe_observed").values(redacted=True)
        )
    _report_again(agent, card_id)
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    _, again = _reported_events(migrated, card_id)
    assert again.audience != []


def _release_with_pull(owner: flow.Human, migrated: Engine, github: FakeGitHub) -> str:
    release = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "0.1.0", "kind": "release", "release": {"version": "0.1.0"}},
    ).json()
    owner.patch(
        f"/projects/maintainer/maity/tasks/{release['id']}",
        {"release": {"pull_requests_typed": [{"number": 1}]}},
    )
    github.pull(1)
    github.tag("v0.1.0")
    project_id = str(_project(migrated).id)
    assert probe.observe_release(migrated, READER, project_id) is True
    return project_id


def test_a_mergeable_state_settling_wakes_nobody(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    """The forge computes `mergeable` lazily: `unknown` and `mergeable` take turns on an
    unchanged pull request. Stored, but not announced."""
    project_id = _release_with_pull(owner, migrated, github)
    before = len(_events(migrated, "probe_observed"))
    for mergeable in (None, True, None):
        github.pull(
            1, mergeable=mergeable, mergeable_state="unknown" if mergeable is None else "clean"
        )
        assert probe.observe_release(migrated, READER, project_id, max_age=0) is True
    stored = probe.last(migrated, project_id, "pr", "1")
    assert stored is not None and stored.data["mergeable"] == "unknown"
    assert len(_events(migrated, "probe_observed")) == before


def test_a_pull_request_that_starts_or_stops_conflicting_wakes(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    project_id = _release_with_pull(owner, migrated, github)
    before = len(_events(migrated, "probe_observed"))
    github.pull(1, mergeable=False, mergeable_state="dirty")
    assert probe.observe_release(migrated, READER, project_id, max_age=0) is True
    github.pull(1, mergeable=None, mergeable_state="unknown")  # out of the conflict
    assert probe.observe_release(migrated, READER, project_id, max_age=0) is True
    events = _events(migrated, "probe_observed")[before:]
    assert [e.payload["observations"]["pr:1"]["mergeable"] for e in events] == [
        "conflicting",
        "unknown",
    ]


def test_a_round_ends_at_the_first_read_the_forge_does_not_answer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    for _ in range(3):
        _reported_card(owner, make_client)
    github.answers["/repos/acme/maity/branches/agent-b%2Fprobe"] = forge.ForgeUnavailableError(
        "rate limited"
    )
    probe.sweep(migrated, READER)
    assert len(github.calls) == 1  # not one timeout per card


def test_a_set_stop_ends_the_round_before_the_next_read(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _reported_card(owner, make_client)
    stop = threading.Event()
    stop.set()
    probe.sweep(migrated, READER, stop)
    assert github.calls == []


def test_a_new_repository_starts_without_the_old_observations(
    owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(3)
    owner.get("/projects/maintainer/maity/probe?pr=3")
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_observation)).all()
    moved = owner.patch(
        "/projects/maintainer/maity", {"repository": {"url": "https://github.com/acme/maity-next"}}
    )
    assert moved.status_code == 200, moved.text
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_observation)).all() == []


def test_a_slow_read_that_started_first_never_replaces_a_newer_one(
    owner: flow.Human, migrated: Engine, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow read of "open" starts; meanwhile a fast read sees "merged" and is
    stored. The slow one ends last but is the older observation, and stays out."""
    project = _project(migrated)
    github.pull(1)  # what the slow read will see
    real_read = probe._read
    calls = [0]

    def slow_then_fast(*args: Any) -> dict[str, Any]:
        calls[0] += 1
        if calls[0] == 1:
            seen = real_read(*args)  # "open", as the forge said when this read began
            github.pull(1, merged=True)
            probe.observe(migrated, READER, project, "pr", "1", 0)  # the fast read, nested
            return seen
        return real_read(*args)

    monkeypatch.setattr(probe, "_read", slow_then_fast)
    probe.observe(migrated, READER, project, "pr", "1", 0)
    stored = probe.last(migrated, project.id, "pr", "1")
    assert stored is not None and stored.data["state"] == "merged"


def test_the_worker_waits_for_a_spent_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """§11.4: the next round is not before the forge's reset, so a spent budget is not
    asked again every interval."""
    from datetime import UTC, datetime, timedelta

    held = datetime.now(UTC) + timedelta(hours=1)
    worker = probe.Worker(None, forge.Forge("ghp_x"), interval=300)  # type: ignore[arg-type]
    monkeypatch.setattr(forge.Forge, "retry_at", lambda _self: held)
    assert worker._after(probe.MERGE_INTERVAL) == held
    monkeypatch.setattr(forge.Forge, "retry_at", lambda _self: None)
    soon = worker._after(probe.MERGE_INTERVAL)
    assert soon < held and soon > datetime.now(UTC)


def test_each_round_starts_at_another_project() -> None:
    """A round ends at its first unanswered read; turning the order spreads the reads."""
    probe._turns.clear()
    firsts = {probe._rotated(["a", "b", "c"], "sweep")[0] for _ in range(3)}
    assert firsts == {"a", "b", "c"}
    assert probe._rotated([], "sweep") == []


def test_the_sweep_and_the_merge_round_turn_on_their_own() -> None:
    """Due together after a reset, the two kinds of round each still reach every
    project: a shared counter would start one of them at the same project each time."""
    probe._turns.clear()
    merges, sweeps = [], []
    for _ in range(4):
        merges.append(probe._rotated(["a", "b"], "merges")[0])
        sweeps.append(probe._rotated(["a", "b"], "sweep")[0])
    assert set(merges) == {"a", "b"} and set(sweeps) == {"a", "b"}


def _other_project_report(owner: flow.Human, make_client: ClientFactory, github: FakeGitHub) -> str:
    """A report in a second project, acme/other, seen open once."""
    flow.project(owner, "other", repository={**REPO, "url": "https://github.com/acme/other"})
    agent = flow.agent(make_client, owner, "other")
    base = "/projects/maintainer/other/tasks"
    card = owner.post(base, {"title": "Another card"}).json()
    assert agent.post(f"{base}/{card['id']}/claim", {}).status_code == 200
    url = "https://github.com/acme/other/pull/7"
    body = _report(pr={"number": 7, "url": url, "head": SHA, "state": "open"})
    assert agent.post(f"{base}/{card['id']}/report", body).status_code == 200
    github.answers["/repos/acme/other"] = {"full_name": "acme/other"}
    for path in ("pulls/7", "branches/agent-b%2Fprobe"):
        github.answers[f"/repos/acme/other/{path}"] = github.answers[f"/repos/acme/maity/{path}"]
    return str(card["id"])


def _observed(engine: Engine, card_id: str) -> Any:
    with engine.connect() as conn:
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == card_id)).scalar_one()
    return report["observed"]


@pytest.mark.parametrize("reason", ["no_grant", "private_without_grant"])
def test_a_project_no_source_covers_costs_the_others_nothing(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    reason: str,
) -> None:
    github.pull(7)
    github.branch("agent-b/probe")
    _, covered = _reported_card(owner, make_client)
    other = _other_project_report(owner, make_client, github)
    assert probe.observe_report(migrated, READER, other) is True
    assert probe.observe_report(migrated, READER, covered) is True
    with migrated.begin() as conn:  # the refused report comes first in the re-reads
        row = conn.execute(select(t.card).where(t.card.c.id == other)).one()
        other_project = row.project_id
        older = {**row.report["observed"], "observed_at": "2020-01-01T00:00:00Z"}
        conn.execute(
            update(t.card)
            .where(t.card.c.id == other)
            .values(report={**row.report, "observed": older})
        )
    for path in list(github.answers):
        if path.startswith("/repos/acme/other"):
            github.answers[path] = forge.NotCoveredError(reason)
    github.pull(7, head="b" * 40)  # what a new read of the covered project sees
    monkeypatch.setattr(probe, "MAX_AGE", 0)
    monkeypatch.setattr(probe, "REREAD_PER_ROUND", 1)  # the refused report must not use it up
    with caplog.at_level("WARNING", logger="maity_hub.probe"):
        probe.sweep(migrated, READER)
    assert _observed(migrated, covered)["pr_head_sha"] == "b" * 40
    assert _observed(migrated, other)["pr_head_sha"] == SHA
    lines = [r.getMessage() for r in caplog.records if reason in r.getMessage()]
    assert lines == [f"probe: project {other_project}: no source covers the repository ({reason})"]


def test_a_project_no_source_covers_is_asked_once_a_round(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The first refusal takes the project's other jobs out of the round: one log line."""
    github.pull(7)
    github.branch("agent-b/probe")
    _reported_card(owner, make_client)
    other = _other_project_report(owner, make_client, github)
    assert probe.observe_report(migrated, READER, other) is True
    with migrated.connect() as conn:
        other_project = conn.execute(
            select(t.card.c.project_id).where(t.card.c.id == other)
        ).scalar_one()
    releases: list[str] = []
    links: list[str] = []

    def refused(_engine: Engine, _fg: Any, project_id: str) -> None:
        releases.append(project_id)
        if project_id == other_project:
            raise forge.NotCoveredError("no_grant")

    monkeypatch.setattr(probe, "observe_release", refused)
    monkeypatch.setattr(probe, "observe_links", lambda _e, _f, p: links.append(p))
    monkeypatch.setattr(probe, "MAX_AGE", 0)
    before = _observed(migrated, other)
    with caplog.at_level("WARNING", logger="maity_hub.probe"):
        probe.sweep(migrated, READER)
    assert releases.count(other_project) == 1
    assert other_project not in links and len(links) == 1  # the covered project still has its turn
    assert _observed(migrated, other) == before  # nor is its report read again
    lines = [r.getMessage() for r in caplog.records if "no_grant" in r.getMessage()]
    assert lines == [f"probe: project {other_project}: no source covers the repository (no_grant)"]


def test_a_merge_round_goes_on_past_a_project_no_source_covers(
    monkeypatch: pytest.MonkeyPatch, owner: flow.Human, migrated: Engine, github: FakeGitHub
) -> None:
    flow.project(owner, "other", repository={**REPO, "url": "https://github.com/acme/other"})
    with migrated.begin() as conn:
        projects = conn.execute(select(t.project.c.id)).scalars().all()
        for project_id in projects:
            conn.execute(
                insert(t.ticker_source).values(project_id=project_id, merges_since=clock.now())
            )
    seen: list[str] = []

    def announce(_engine: Engine, _fg: Any, project_id: str) -> None:
        seen.append(project_id)
        raise forge.NotCoveredError("no_grant")

    monkeypatch.setattr(probe, "announce_merges", announce)
    probe.merge_sweep(migrated, READER)
    assert sorted(seen) == sorted(projects)


# --- the required check (§6.1, §6.6) and `?commit=` (§11) ----------------------------------------


@pytest.mark.parametrize(
    ("runs", "status"),
    [
        ([("ci-ok", "success")], "success"),
        ([("ci-ok", "skipped")], "failure"),
        ([("ci-ok", "neutral")], "failure"),
        ([("ci-ok", "timed_out")], "failure"),
        ([("ci-ok", "cancelled")], "cancelled"),
        ([("ci-ok", None)], "pending"),
        ([("ci-ok", "success"), ("ci-ok", "cancelled")], "cancelled"),
        ([("ci-ok", "cancelled"), ("ci-ok", None)], "pending"),
        ([("ci-ok", None), ("ci-ok", "failure")], "failure"),
        ([("ci / sqlite", "success")], "missing"),
    ],
)
def test_the_required_check_takes_the_worst_of_its_name(
    runs: list[tuple[str, str | None]], status: str
) -> None:
    detail = [{"name": n, "status": r or "pending"} for n, r in runs]  # as `checks()` reads them
    assert forge.required_check("ci-ok", "success", detail) == {"name": "ci-ok", "status": status}


def test_the_required_check_is_unknown_on_a_partial_read_and_null_without_a_name() -> None:
    """§11.4: never `missing` from a read that did not see every check."""
    assert forge.required_check("ci-ok", "unknown", []) == {"name": "ci-ok", "status": "unknown"}
    assert forge.required_check(None, "success", [{"name": "ci-ok", "status": "success"}]) is None


def _name_the_check(owner: flow.Human, name: str | None) -> None:
    named = owner.patch(
        "/projects/maintainer/maity", {"repository": {**REPO, "required_check": name}}
    )
    assert named.status_code == 200, named.text


def test_a_pull_request_read_carries_the_required_check(
    owner: flow.Human, github: FakeGitHub
) -> None:
    _name_the_check(owner, "ci / sqlite")
    github.pull(3)
    body = owner.get("/projects/maintainer/maity/probe?pr=3").json()
    assert body["pr"]["required_check"] == {"name": "ci / sqlite", "status": "success"}
    github.answers["/repos/acme/maity/pulls/4"] = None
    missing = owner.get("/projects/maintainer/maity/probe?pr=4").json()
    assert missing["pr"] == {"number": 4, "found": False}


def _commit(github: FakeGitHub, sha: str, runs: list[tuple[str, str | None]]) -> None:
    github.answers[f"/repos/acme/maity/git/commits/{sha}"] = {"sha": sha}
    github.runs(sha, runs)


def test_a_commit_read_has_the_contract_shape(
    owner: flow.Human, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "FORCED_FLOOR", 0)  # the floor has its own test
    _name_the_check(owner, "ci-ok")
    _commit(github, SHA, [("ci-ok", "success"), ("lint", None)])
    github.branch("main", head=OTHER)
    body = owner.get(f"/projects/maintainer/maity/probe?commit={SHA.upper()}").json()
    assert (body["pr"], body["branch"], body["tag"]) == (None, None, None)
    assert body["commit"] == {
        "sha": SHA,
        "found": True,
        "checks": "pending",
        "checks_detail": [
            {"name": "ci-ok", "status": "success"},
            {"name": "lint", "status": "pending"},
        ],
        "required_check": {"name": "ci-ok", "status": "success"},
        "branch_head_sha": OTHER,
        "ahead": True,
    }
    github.branch("main", head=SHA)
    again = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}&max_age=0").json()
    assert (again["commit"]["branch_head_sha"], again["commit"]["ahead"]) == (SHA, False)


def test_a_commit_the_forge_does_not_have_is_found_false_and_reads_no_branch(
    owner: flow.Human, github: FakeGitHub
) -> None:
    github.answers[f"/repos/acme/maity/git/commits/{OTHER}"] = forge.ForgeUnavailableError(
        "No commit found for SHA", status=422
    )
    body = owner.get(f"/projects/maintainer/maity/probe?commit={OTHER}").json()
    assert body["commit"] == {"sha": OTHER, "found": False}
    assert not any("/branches/" in call for call in github.calls)


@pytest.mark.parametrize("sha", ["abc1234", SHA + "0", "g" * 40])
def test_a_commit_that_is_no_full_sha_is_invalid(
    owner: flow.Human, github: FakeGitHub, sha: str
) -> None:
    response = owner.get(f"/projects/maintainer/maity/probe?commit={sha}")
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"commit": "not_a_sha"}
    assert github.calls == []


def test_a_refused_branch_reads_as_null_and_a_spent_budget_drops_the_commit_read(
    owner: flow.Human, github: FakeGitHub
) -> None:
    """§6.13: refused without the budget being spent, `branch_head_sha`/`ahead` are null,
    never `false`; a spent budget drops the read as a whole."""
    _commit(github, SHA, [("ci-ok", "success")])
    branch = "/repos/acme/maity/branches/main"
    github.answers[branch] = forge.ForgeUnavailableError("refused", status=403)
    body = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}").json()
    assert (body["commit"]["branch_head_sha"], body["commit"]["ahead"]) == (None, None)
    github.answers[branch] = forge.ForgeUnavailableError("later", status=403, rate_limited=True)
    _commit(github, OTHER, [("ci-ok", "success")])
    dropped = owner.get(f"/projects/maintainer/maity/probe?commit={OTHER}")
    assert dropped.status_code == 503
    assert dropped.json()["error"]["code"] == "probe_unavailable"


def _checked_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> tuple[Any, str]:
    """A reported card whose last observation told its holder `ci-ok: success`."""
    _name_the_check(owner, "ci-ok")
    github.pull(7)
    github.runs(SHA, [("ci-ok", "success")])
    github.branch("agent-b/probe")
    agent, card_id = _reported_card(owner, make_client)
    assert probe.observe_report(migrated, READER, card_id) is True
    [told] = _reported_events(migrated, card_id)
    assert told.audience and told.payload["observed"]["required_check"] == {
        "name": "ci-ok",
        "status": "success",
    }
    return agent, card_id


def test_a_required_check_status_change_wakes_the_holder(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.6: a skipped run leaves the summary `success`; the required check fails."""
    _, card_id = _checked_card(owner, make_client, migrated, github)
    github.runs(SHA, [("ci-ok", "skipped")])
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    _, changed = _reported_events(migrated, card_id)
    assert changed.payload["observed"]["checks"] == "success"
    assert changed.payload["observed"]["required_check"]["status"] == "failure"
    assert changed.audience != []


def test_a_renamed_required_check_wakes_nobody_whatever_its_status(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """spq4's P3 on #1295: a rename with a status change is no news from the forge; a later
    status change under the new name is."""
    _, card_id = _checked_card(owner, make_client, migrated, github)
    _name_the_check(owner, "ci / sqlite")  # its status: `missing`
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    _, renamed = _reported_events(migrated, card_id)
    assert renamed.payload["observed"]["required_check"] == {
        "name": "ci / sqlite",
        "status": "missing",
    }
    assert renamed.audience == []
    github.runs(SHA, [("ci-ok", "success"), ("ci / sqlite", "success")])
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    *_, now_success = _reported_events(migrated, card_id)
    assert now_success.payload["observed"]["required_check"]["status"] == "success"
    assert now_success.audience != []  # the same name as the last observation: news


def test_a_required_check_cleared_or_named_first_wakes_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _, card_id = _checked_card(owner, make_client, migrated, github)
    _name_the_check(owner, None)
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    _, cleared = _reported_events(migrated, card_id)
    assert cleared.payload["observed"]["required_check"] is None
    assert cleared.audience == []
    _name_the_check(owner, "ci-ok")  # named again, as the last told: nothing new either
    github.runs(SHA, [("ci-ok", "success"), ("lint", "success")])
    _name_the_check(owner, "lint")  # a first name the readers were never told
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    *_, first = _reported_events(migrated, card_id)
    assert first.payload["observed"]["required_check"] == {"name": "lint", "status": "success"}
    assert first.audience == []


def test_a_required_check_renamed_back_is_compared_with_the_last_observation(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """nyh5's P2 on #1306: A, B, A again; the baseline is the last stored observation, so the
    second rename is a silent new baseline too, whatever the status under A meanwhile."""
    _, card_id = _checked_card(owner, make_client, migrated, github)
    _name_the_check(owner, "lint")
    github.runs(SHA, [("ci-ok", "success"), ("lint", "success")])
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    github.runs(SHA, [("ci-ok", "skipped"), ("lint", "success")])
    _name_the_check(owner, "ci-ok")
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    *_, back = _reported_events(migrated, card_id)
    assert back.payload["observed"]["required_check"] == {"name": "ci-ok", "status": "failure"}
    assert back.audience == []


def test_a_status_change_after_a_rename_and_a_new_report_wakes_the_holder(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """e5kk's P2 on #1306: after a silent rename and a new report, the first status change
    under the new name is news, also on the first read for the new report: compared with the
    last observation whatever its audience, not with the last one told."""
    agent, card_id = _checked_card(owner, make_client, migrated, github)
    _name_the_check(owner, "lint")
    github.runs(SHA, [("ci-ok", "success"), ("lint", "success")])
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    _report_again(agent, card_id)  # `report.observed` is null again
    github.runs(SHA, [("ci-ok", "success"), ("lint", "skipped")])  # the summary stays
    assert probe.observe_report(migrated, READER, card_id, max_age=0) is True
    *_, failed = _reported_events(migrated, card_id)
    assert failed.payload["observed"]["checks"] == "success"
    assert failed.payload["observed"]["required_check"] == {"name": "lint", "status": "failure"}
    assert failed.audience != []


def test_a_commit_read_is_stored_whole_or_not_at_all(owner: flow.Human, github: FakeGitHub) -> None:
    """e5kk's P1 on #1306: a branch read refused by a spent budget stores no commit row,
    so no later read finds a commit observation without `branch_head_sha`/`ahead`."""
    _commit(github, SHA, [("ci-ok", "success")])
    branch = "/repos/acme/maity/branches/main"
    github.answers[branch] = forge.ForgeUnavailableError("later", status=403, rate_limited=True)
    dropped = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}")
    assert dropped.status_code == 503
    assert "last" not in dropped.json()["error"]["details"]
    github.answers.pop(branch)
    github.branch("main", head=OTHER)
    body = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}").json()
    assert (body["commit"]["branch_head_sha"], body["commit"]["ahead"]) == (OTHER, True)


def test_the_last_commit_observation_on_a_spent_budget_has_the_contract_shape(
    owner: flow.Human, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """e5kk's P1 on #1306: `details.last` is the §6.13 shape, not the stored row."""
    monkeypatch.setattr(probe, "FORCED_FLOOR", 0)
    _name_the_check(owner, "ci-ok")
    _commit(github, SHA, [("ci-ok", "success")])
    github.branch("main", head=OTHER)
    first = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}").json()["commit"]
    for path in [p for p in github.answers if SHA in p or p.endswith("/branches/main")]:
        github.answers[path] = forge.ForgeUnavailableError("later", status=403, rate_limited=True)
    dropped = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}&max_age=0")
    assert dropped.status_code == 503
    last = dropped.json()["error"]["details"]["last"]
    assert {k: v for k, v in last.items() if k != "observed_at"} == first


def test_review_last_preserves_complete_refused_branch(
    owner: flow.Human, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nyh5's P2 on #1306: a branch refused without a spent budget is a complete answer with
    `branch_head_sha`/`ahead` null. `details.last` is that answer, not the commit joined with
    an older branch read the refusal left in the cache."""
    monkeypatch.setattr(probe, "FORCED_FLOOR", 0)
    _name_the_check(owner, "ci-ok")
    _commit(github, SHA, [("ci-ok", "success")])
    github.branch("main", head=SHA)
    first = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}").json()["commit"]
    assert (first["branch_head_sha"], first["ahead"]) == (SHA, False)
    branch = "/repos/acme/maity/branches/main"
    github.answers[branch] = forge.ForgeUnavailableError("refused", status=403)
    refused = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}&max_age=0")
    assert refused.status_code == 200, refused.text
    second = refused.json()["commit"]
    assert (second["branch_head_sha"], second["ahead"]) == (None, None)
    commit = f"/repos/acme/maity/git/commits/{SHA}"
    github.answers[commit] = forge.ForgeUnavailableError("later", status=403, rate_limited=True)
    dropped = owner.get(f"/projects/maintainer/maity/probe?commit={SHA}&max_age=0")
    assert dropped.status_code == 503
    last = dropped.json()["error"]["details"]["last"]
    assert {k: v for k, v in last.items() if k != "observed_at"} == {
        k: v for k, v in second.items() if k != "observed_at"
    }
