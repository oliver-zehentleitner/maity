"""docs/api.md §6.6 "A merge closes the loop" and §6.1 `merged_closes`: a merge the probe
observes on a card in review wakes the done authority with `task_merged` once per report;
under `auto` with `done_authority` holder or admin the hub closes the card itself unless
a dependency, a child or an objection holds it; a merge seen elsewhere is told when the
card returns to review with the same report."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import events, forge, merged, probe
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_probe import OTHER, READER, REPO, TOKEN, FakeGitHub, _report

BASE = "/projects/maintainer/maity"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(
        settings, forge_github_token=TOKEN, forge_instance_namespaces=frozenset({"maintainer"})
    )


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(forge.Forge, "_get", lambda _self, path: fake(path))
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    return fake


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", repository=REPO)
    return owner


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _policy(owner: flow.Human, **policy: Any) -> None:
    response = owner.patch(BASE, {"policy": policy, "reason": "the merge closes the loop"})
    assert response.status_code == 200, response.text


def _reported(
    github: FakeGitHub,
    owner: flow.Human,
    make_client: ClientFactory,
    card: dict[str, Any] | None = None,
    named: bool = True,
    **report: Any,
) -> tuple[Any, str]:
    """A card claimed and reported with pull request 7, which names the card unless
    `named` is false (§6.6)."""
    agent = flow.agent(make_client, owner)
    card = owner.post(f"{BASE}/tasks", {"title": "A card", **(card or {})}).json()
    if named:
        github.name(7, card["id"])
    assert agent.post(f"{BASE}/tasks/{card['id']}/claim", {}).status_code == 200
    stored = agent.post(f"{BASE}/tasks/{card['id']}/report", _report(**report))
    assert stored.status_code == 200, stored.text
    return agent, card["id"]


def _card(owner: flow.Human, card_id: str) -> dict[str, Any]:
    return dict(owner.get(f"{BASE}/tasks/{card_id}").json())


def test_a_merge_on_a_card_in_review_wakes_the_done_authority_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client)
    assert _card(owner, card_id)["status"] == "review"
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload == {
        "task": card_id,
        "pr": 7,
        "merge_sha": "f" * 40,
        "done_authority": "reviewer",
        "closed": False,
    }
    assert "role:reviewer" in told.audience and "trust:admin" in told.audience
    assert _card(owner, card_id)["status"] == "review"  # notify: the reviewer closes it
    probe.observe_report(migrated, READER, card_id)  # observed again: told once per report
    assert len(_events(migrated, "task_merged")) == 1


def test_a_sweep_sees_the_merge_of_a_report_first_observed_open(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "MAX_AGE", 0)
    monkeypatch.setattr(probe, "FORCED_FLOOR", 0)
    github.pull(7)
    _, card_id = _reported(github, owner, make_client)
    probe.sweep(migrated, READER)
    assert _card(owner, card_id)["report"]["observed"]["pr_state"] == "open"
    assert _events(migrated, "task_merged") == []
    github.pull(7, merged=True)
    probe.sweep(migrated, READER)
    assert _card(owner, card_id)["report"]["observed"]["pr_state"] == "merged"
    assert len(_events(migrated, "task_merged")) == 1
    reads = len(github.calls)
    probe.sweep(migrated, READER)  # a merged report has nothing more to say
    assert [c for c in github.calls[reads:] if "/pulls/7" in c] == []


def test_reports_last_seen_open_are_read_oldest_first_after_everything_else(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "MAX_AGE", 0)
    monkeypatch.setattr(probe, "REREAD_PER_ROUND", 2)
    github.pull(7)
    cards = [_reported(github, owner, make_client)[1] for _ in range(3)]
    never = _reported(github, owner, make_client)[1]
    ages = dict(
        zip(
            cards,
            ("2026-10-03T00:00:00Z", "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"),
            strict=True,
        )
    )
    with migrated.begin() as conn:
        for card_id, at in ages.items():
            report = conn.execute(
                select(t.card.c.report).where(t.card.c.id == card_id)
            ).scalar_one()
            observed = {"pr_state": "open", "observed_at": at}
            conn.execute(
                update(t.card)
                .where(t.card.c.id == card_id)
                .values(report={**report, "observed": observed})
            )
    jobs: list[tuple[str, str]] = []

    def job(name: str) -> Any:
        return lambda _engine, _fg, ref, *_: jobs.append((name, ref))

    monkeypatch.setattr(probe, "observe_report", job("report"))
    monkeypatch.setattr(probe, "observe_release", job("release"))
    monkeypatch.setattr(probe, "observe_links", job("links"))
    probe.sweep(migrated, READER)
    assert jobs == [
        ("report", never),
        ("release", jobs[1][1]),
        ("links", jobs[2][1]),
        ("report", cards[1]),  # the oldest
        ("report", cards[2]),
    ]


def test_auto_under_holder_closes_the_card_itself(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is True and "blocked_by" not in told.payload
    assert _card(owner, card_id)["status"] == "done"
    updated = [e for e in _events(migrated, "task_updated") if e.payload.get("id") == card_id]
    assert updated[-1].payload["fields"] == ["status"] and updated[-1].payload["status"] == "done"
    assert updated[-1].payload["history"] == []  # §6.15: the auto-close writes no entry


RELEASE = {"title": "0.1.0", "kind": "release", "release": {"version": "0.1.0"}}


def test_auto_never_closes_a_release_card_with_an_open_checklist_item(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.7: a release closes through its readiness gate, which the releaser passes
    after the checklist; a merge of its pull request is not that step."""
    response = owner.patch(BASE, {"settings": {"release_checklist": ["CHANGELOG has a section"]}})
    assert response.status_code == 200, response.text
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client, RELEASE)
    assert [i["done"] for i in _card(owner, card_id)["release"]["checklist"]] == [False]
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert (told.payload["closed"], told.payload["blocked_by"]) == (False, ["release"])
    card = _card(owner, card_id)
    assert card["status"] == "review"
    assert _events(migrated, "release_ready") == []


def test_auto_never_closes_a_release_card_even_when_nothing_is_open(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _policy(owner, done_authority="admin", merged_closes="auto")
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client, RELEASE)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert (told.payload["closed"], told.payload["blocked_by"]) == (False, ["release"])
    assert _card(owner, card_id)["status"] == "review"
    with migrated.connect() as conn:
        in_flight = conn.execute(
            select(t.card.c.release_in_flight).where(t.card.c.id == card_id)
        ).scalar_one()
    assert in_flight is True  # still the open release: the releaser closes it


def test_auto_under_reviewer_acts_as_notify(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _policy(owner, merged_closes="auto")  # done_authority stays reviewer
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is False and "blocked_by" not in told.payload
    assert _card(owner, card_id)["status"] == "review"


def test_an_open_child_keeps_the_card_in_review_and_says_so(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client)
    child = owner.post(f"{BASE}/tasks", {"title": "Still open", "parent": card_id})
    assert child.status_code == 201, child.text
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert (told.payload["closed"], told.payload["blocked_by"]) == (False, ["dependencies"])
    assert _card(owner, card_id)["status"] == "review"


def test_closing_a_child_tells_its_parent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.4 Child cards: the hub closing a child is a status change like any other, so the
    parent hears `task_updated` with its `children` counts."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    parent = owner.post(f"{BASE}/tasks", {"title": "The parent"}).json()
    child = owner.post(f"{BASE}/tasks", {"title": "The child", "parent": parent["id"]}).json()
    github.name(7, child["id"])
    agent = flow.agent(make_client, owner)
    assert agent.post(f"{BASE}/tasks/{child['id']}/claim", {}).status_code == 200
    stored = agent.post(f"{BASE}/tasks/{child['id']}/report", _report())
    assert stored.status_code == 200, stored.text
    probe.observe_report(migrated, READER, child["id"])
    assert _card(owner, child["id"])["status"] == "done"
    told = [e for e in _events(migrated, "task_updated") if e.payload.get("id") == parent["id"]]
    assert told[-1].payload["fields"] == ["children"]
    assert told[-1].payload["children"] == {"open": 0, "total": 1}
    assert _card(owner, parent["id"])["children"] == {"open": 0, "total": 1}


def test_closing_cancels_an_open_takeover(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.19: a takeover ends `cancelled` once the holder's card is done."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client)
    asker = flow.agent(make_client, owner)
    opened = asker.post(f"{BASE}/tasks/{card_id}/takeover", {"reason": "silent for hours"})
    assert opened.status_code == 201, opened.text
    probe.observe_report(migrated, READER, card_id)
    assert _card(owner, card_id)["status"] == "done"
    row = owner.get(f"{BASE}/takeovers/{opened.json()['id']}").json()
    assert (row["status"], row["outcome"]["how"]) == ("cancelled", "cancelled")


def test_a_mismatched_merge_triggers_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True, head="e" * 40)
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert _events(migrated, "task_merged") == []


def _blocked(agent: flow.Agent, owner: flow.Human, card_id: str) -> str:
    """The holder waits on a request (§7): the card goes to `blocked`."""
    asked = agent.post(
        f"{BASE}/requests",
        {"class": "decision", "title": "Which?", "task_id": card_id, "while_open": "wait"},
    )
    assert asked.status_code == 201, asked.text
    assert _card(owner, card_id)["status"] == "blocked"
    return str(asked.json()["id"])


def test_a_merge_on_a_card_blocked_in_review_is_told_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Blocked from review (§7): the report is what waits, so the merge is told now, and
    the answer's return to review tells it no second time."""
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    asked = _blocked(agent, owner, card_id)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["task"] == card_id and told.payload["merge_sha"] == "f" * 40
    assert told.payload["closed"] is False and "role:reviewer" in told.audience
    assert _card(owner, card_id)["status"] == "blocked"  # notify: the hub moves nothing
    answered = owner.post(f"{BASE}/requests/{asked}/answer", {"text": "go ahead"})
    assert answered.status_code == 200, answered.text
    assert _card(owner, card_id)["status"] == "review"
    assert len(_events(migrated, "task_merged")) == 1


def test_auto_closes_a_card_blocked_in_review_and_ends_the_block(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.6: the hub closes it as from review; the request stays open, and its answer
    later moves nothing (§7: only a blocked card has a status to restore)."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    asked = _blocked(agent, owner, card_id)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is True
    card = _card(owner, card_id)
    assert card["status"] == "done" and card["blocked_by_request"] is None
    with migrated.connect() as conn:
        row = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    assert row.status_before_block is None
    moves = [e for e in _events(migrated, "task_updated") if e.payload.get("id") == card_id]
    assert moves[-1].payload["fields"] == ["status"] and moves[-1].payload["status"] == "done"
    assert owner.get(f"{BASE}/requests/{asked}").json()["status"] == "open"
    answered = owner.post(f"{BASE}/requests/{asked}/answer", {"text": "go ahead"})
    assert answered.status_code == 200, answered.text
    assert _card(owner, card_id)["status"] == "done"
    assert len(_events(migrated, "task_merged")) == 1


def test_an_open_child_keeps_a_blocked_card_blocked_and_says_so(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    child = owner.post(f"{BASE}/tasks", {"title": "Still open", "parent": card_id})
    assert child.status_code == 201, child.text
    _blocked(agent, owner, card_id)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert (told.payload["closed"], told.payload["blocked_by"]) == (False, ["dependencies"])
    assert _card(owner, card_id)["status"] == "blocked"


def test_a_merge_seen_in_rework_is_remembered_not_told(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Sent back to `in_progress` and blocked from there, the card's report no longer waits
    for review: the merge is remembered, as for any card not in review (§6.6)."""
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    back = owner.patch(f"{BASE}/tasks/{card_id}", {"status": "in_progress"})
    assert back.status_code == 200, back.text
    _blocked(agent, owner, card_id)
    probe.observe_report(migrated, READER, card_id)
    assert _events(migrated, "task_merged") == []
    refused = owner.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "invalid_transition"


def test_the_done_authority_closes_a_merged_card_blocked_in_review(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Through the API a blocked card closes too: a `blocked→done` by the done authority
    once the report's merge is observed (§6.4, §6.6). Before that an editor gets
    `invalid_transition`, a done authority that is no editor `forbidden`."""
    github.pull(7)
    agent, card_id = _reported(github, owner, make_client)
    _blocked(agent, owner, card_id)
    probe.observe_report(migrated, READER, card_id)  # still open: nothing to close yet
    early = owner.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert early.status_code == 409, early.text
    assert early.json()["error"]["code"] == "invalid_transition"
    reviewer = flow.agent(make_client, owner, role="reviewer")
    unseen = reviewer.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert unseen.status_code == 403, unseen.text
    assert unseen.json()["error"]["code"] == "forbidden"
    github.pull(7, merged=True)
    probe.observe_report(migrated, READER, card_id)
    holder = agent.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert holder.status_code == 403, holder.text  # the holder is not the done authority
    closed = reviewer.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert closed.status_code == 200, closed.text  # not an editor: the done authority
    card = _card(owner, card_id)
    assert card["status"] == "done" and card["blocked_by_request"] is None
    assert card["closed_at"] is not None


def test_an_outside_reviewer_does_not_close_a_merged_card_blocked_in_review(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§2.3 "Own approvals": a reviewing role gives an outside agent no done authority, the
    merged `blocked→done` included (§6.4, §6.6), which the hub reads as a `review→done`.
    Refused exactly as a member coder that is no editor of the card is; the card stays
    blocked, and a member reviewer still closes it."""
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    _blocked(agent, owner, card_id)
    probe.observe_report(migrated, READER, card_id)
    outside = flow.agent(make_client, owner, role="reviewer")
    _owned_by(migrated, outside.id, _stranger(make_client, migrated).id)
    refused = outside.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    coder = flow.agent(make_client, owner).patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert refused.status_code == coder.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == coder.json()["error"]["details"]
    card = _card(owner, card_id)
    assert card["status"] == "blocked" and card["closed_at"] is None
    member = flow.agent(make_client, owner, role="reviewer")
    closed = member.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert closed.status_code == 200, closed.text
    assert _card(owner, card_id)["status"] == "done"


def test_two_signatures_still_need_review_for_a_blocked_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Under `reviewer_and_tester` a close is two signatures on a card in review (§6.4);
    a blocked card waits for the answer that restores review. Nobody can sign while it is
    blocked, so the merge is remembered, not told, and told on the return to review."""
    _policy(owner, done_authority="reviewer_and_tester")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    asked = _blocked(agent, owner, card_id)
    probe.observe_report(migrated, READER, card_id)
    assert _events(migrated, "task_merged") == []
    refused = owner.patch(f"{BASE}/tasks/{card_id}", {"status": "done"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "invalid_transition"
    assert _card(owner, card_id)["status"] == "blocked"
    answered = owner.post(f"{BASE}/requests/{asked}/answer", {"text": "go ahead"})
    assert answered.status_code == 200, answered.text
    assert _card(owner, card_id)["status"] == "review"
    assert len(_events(migrated, "task_merged")) == 1


@pytest.mark.parametrize(
    ("verb", "body", "kind"),
    [
        ("answer", {"text": "go ahead"}, "request_answered"),
        ("withdraw", {"reason": "not needed"}, "request_withdrawn"),
    ],
)
def test_the_end_of_a_request_comes_before_the_return_to_review_and_the_merge(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    verb: str,
    body: dict[str, str],
    kind: str,
) -> None:
    """What happened first, then what followed from it (§6.4, §6.6), one event at a time.
    A merge remembered before this hub told blocked cards (no `merge_told`) is told on the
    return to review."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    asked = _blocked(agent, owner, card_id)
    _remembered(migrated, card_id)
    _stored_pull(migrated)
    ended = owner.post(f"{BASE}/requests/{asked}/{verb}", body)
    assert ended.status_code == 200, ended.text
    [told] = _events(migrated, kind)
    moves = [e for e in _events(migrated, "task_updated") if e.seq > told.seq]
    assert [m.payload["status"] for m in moves] == ["review", "done"]
    [merge] = _events(migrated, "task_merged")
    assert told.seq < moves[0].seq < merge.seq < moves[1].seq


def _remembered(engine: Engine, card_id: str) -> None:
    """What a merge observed on a blocked card left before blocked cards were told: the
    report observed merged, remembered with its key, not told."""
    with engine.begin() as conn:
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == card_id)).scalar_one()
        report = {**report, "observed": {"pr_state": "merged"}, "mismatch": False}
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id)
            .values(report=report, merge_report=merged.report_key(report), merge_told=False)
        )


def _stored_pull(engine: Engine, *dropped: str) -> None:
    """Pull request 7 read from the forge and stored, without the keys in `dropped`: an
    observation stored before the hub kept them."""
    with engine.connect() as conn:
        project = conn.execute(select(t.project)).one()
    probe.observe(engine, READER, project, "pr", "7", max_age=0)
    if dropped:
        row = t.forge_observation.c
        with engine.begin() as conn:
            data = conn.execute(
                select(row.data).where(row.kind == "pr", row.ref == "7")
            ).scalar_one()
            kept = {k: v for k, v in data.items() if k not in dropped}
            conn.execute(
                update(t.forge_observation)
                .where(row.kind == "pr", row.ref == "7")
                .values(data=kept)
            )


# --- only the card the pull request belongs to (§6.6) ---------------------------------------


def _closed_or_why(engine: Engine, card_id: str) -> tuple[bool, list[str]]:
    told = [e for e in _events(engine, "task_merged") if e.payload["task"] == card_id]
    assert len(told) == 1
    return told[0].payload["closed"], told[0].payload.get("blocked_by", [])


@pytest.fixture
def admin_auto(owner: flow.Human) -> None:
    """The policy a coder cannot close a card under on its own: an admin closes it, or the
    merge of the card's own pull request does."""
    _policy(owner, done_authority="admin", merged_closes="auto")


@pytest.mark.usefixtures("admin_auto")
def test_the_card_s_own_merged_pull_request_closes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (True, [])
    assert _card(owner, card_id)["status"] == "done"


@pytest.mark.usefixtures("admin_auto")
def test_a_branch_the_forge_does_not_have_is_no_mismatch_and_closes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """A branch read that finds nothing reads as deleted after the merge, so the report is
    no mismatch; the pull request's own head branch is another, so the hub does not close."""
    github.pull(7, merged=True)
    _, card_id = _reported(
        github, owner, make_client, branch="no-such-branch", upstream="origin/no-such-branch"
    )
    probe.observe_report(migrated, READER, card_id)
    card = _card(owner, card_id)
    assert card["report"]["mismatch"] is False
    assert card["report"]["observed"]["branch_head_sha"] is None
    assert _closed_or_why(migrated, card_id) == (False, ["head_ref"])
    assert card["status"] == "review"


@pytest.mark.usefixtures("admin_auto")
def test_another_branch_pushed_to_the_merged_head_closes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    github.branch("agent-c/other")  # at the pull request's head
    _, card_id = _reported(
        github, owner, make_client, branch="agent-c/other", upstream="origin/agent-c/other"
    )
    probe.observe_report(migrated, READER, card_id)
    assert _card(owner, card_id)["report"]["mismatch"] is False
    assert _closed_or_why(migrated, card_id) == (False, ["head_ref"])


@pytest.mark.usefixtures("admin_auto")
def test_the_remote_branch_of_upstream_is_compared_not_the_local_name(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported(
        github, owner, make_client, branch="my-local-name", upstream="origin/agent-b/probe"
    )
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (True, [])


@pytest.mark.usefixtures("admin_auto")
def test_without_upstream_the_branch_is_compared(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client, upstream=None)
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (True, [])


@pytest.mark.usefixtures("admin_auto")
def test_an_upstream_that_names_another_branch_closes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """`branch` matches, but `upstream` is what names the remote branch once it is set."""
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client, upstream="origin/agent-b/other")
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (False, ["head_ref"])


@pytest.mark.usefixtures("admin_auto")
def test_a_pull_request_from_a_fork_closes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True, repo="someone/maity")
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (False, ["head_ref"])


@pytest.mark.usefixtures("admin_auto")
def test_a_fork_pull_request_is_no_mismatch_beside_a_project_branch_of_its_name(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """The reported branch lives in the fork; a branch of the same name in the project's own
    repository is another branch, so its head contradicts nothing (tsk-k0x4jn4y4ykg)."""
    github.pull(7, merged=True, repo="someone/maity")
    github.branch("agent-b/probe", head=OTHER)  # the project's own, unrelated branch
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert _card(owner, card_id)["report"]["mismatch"] is False
    assert _closed_or_why(migrated, card_id) == (False, ["head_ref"])


@pytest.mark.usefixtures("admin_auto")
def test_a_pull_request_that_does_not_name_the_card_closes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client, named=False)
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (False, ["pull_request_unnamed"])
    assert _card(owner, card_id)["status"] == "review"


@pytest.mark.usefixtures("admin_auto")
def test_a_card_named_in_the_title_counts_in_any_case(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client, named=False)
    github.pull(7, merged=True, title=f"hub: a change ({card_id.upper()})")
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (True, [])


@pytest.mark.usefixtures("admin_auto")
def test_a_pull_request_merged_before_the_report_closes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True, merged_at="2026-01-01T00:00:00Z")
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (False, ["merged_before_report"])


@pytest.mark.usefixtures("admin_auto")
def test_a_merge_time_without_a_zone_counts_as_unknown(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Later than the report, but without a zone it cannot be compared: not a fault, and
    not a close."""
    github.pull(7, merged=True, merged_at="2099-01-01T00:00:00")
    _, card_id = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (False, ["merged_before_report"])
    assert _card(owner, card_id)["status"] == "review"


@pytest.mark.usefixtures("admin_auto")
def test_an_upstream_without_a_remote_s_name_names_no_branch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client, upstream="/agent-b/probe")
    probe.observe_report(migrated, READER, card_id)
    assert _closed_or_why(migrated, card_id) == (False, ["head_ref"])


@pytest.mark.usefixtures("admin_auto")
def test_a_second_card_naming_the_same_pull_request_does_not_close(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    _, first = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, first)
    assert _closed_or_why(migrated, first) == (True, [])
    _, second = _reported(github, owner, make_client)  # the body now names the second too
    probe.observe_report(migrated, READER, second)
    assert _closed_or_why(migrated, second) == (False, ["pull_request_shared"])
    assert _card(owner, second)["status"] == "review"
    assert _card(owner, first)["status"] == "done"


@pytest.mark.usefixtures("admin_auto")
def test_a_pull_request_that_closed_a_card_closes_no_other_after_that_card_moved_on(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """The first card's report names another pull request now (a stacked one): the closed
    `task_merged` still tells that pull request 7 closed it."""
    github.pull(7, merged=True)
    _, first = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, first)
    assert _closed_or_why(migrated, first) == (True, [])
    with migrated.begin() as conn:
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == first)).scalar_one()
        moved = {**report, "pr": {**report["pr"], "number": 8}}
        conn.execute(update(t.card).where(t.card.c.id == first).values(report=moved))
    _, second = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, second)
    assert _closed_or_why(migrated, second) == (False, ["pull_request_shared"])


@pytest.mark.usefixtures("admin_auto")
def test_two_cards_naming_one_pull_request_before_its_merge_both_stay(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7)
    _, first = _reported(github, owner, make_client)
    _, second = _reported(github, owner, make_client)
    github.bodies[7] = f"{first} and {second}"
    github.pull(7, merged=True)
    for card_id in (first, second):
        probe.observe_report(migrated, READER, card_id)
        assert _closed_or_why(migrated, card_id) == (False, ["pull_request_shared"])
        assert _card(owner, card_id)["status"] == "review"


@pytest.mark.usefixtures("admin_auto")
def test_a_cancelled_card_naming_the_pull_request_still_counts(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7)
    _, first = _reported(github, owner, make_client)
    cancelled = owner.patch(f"{BASE}/tasks/{first}", {"status": "cancelled"})
    assert cancelled.status_code == 200, cancelled.text
    github.pull(7, merged=True)
    _, second = _reported(github, owner, make_client)
    probe.observe_report(migrated, READER, second)
    assert _closed_or_why(migrated, second) == (False, ["pull_request_shared"])


@pytest.mark.parametrize("dropped", ["head_ref", "head_repo", "card_ids", "merged_at"])
def test_an_observation_stored_before_the_hub_kept_what_ties_it_closes_nothing(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,
    dropped: str,
) -> None:
    """A merge remembered on a blocked card, told on the return to review from the stored
    observation: what that observation does not hold counts against closing."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    asked = _blocked(agent, owner, card_id)
    _remembered(migrated, card_id)
    _stored_pull(migrated, dropped)
    ended = owner.post(f"{BASE}/requests/{asked}/answer", {"text": "go ahead"})
    assert ended.status_code == 200, ended.text
    why = {
        "head_ref": "head_ref",
        "head_repo": "head_ref",
        "card_ids": "pull_request_unnamed",
        "merged_at": "merged_before_report",
    }[dropped]
    assert _closed_or_why(migrated, card_id) == (False, [why])
    assert _card(owner, card_id)["status"] == "review"


def test_a_new_report_in_between_starts_over(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    back = owner.patch(f"{BASE}/tasks/{card_id}", {"status": "in_progress"})
    assert back.status_code == 200, back.text
    probe.observe_report(migrated, READER, card_id)  # in rework: remembered
    assert _events(migrated, "task_merged") == []
    again = agent.post(f"{BASE}/tasks/{card_id}/report", _report(summary="Reported again."))
    assert again.status_code == 200, again.text
    assert _card(owner, card_id)["status"] == "review"
    assert _events(migrated, "task_merged") == []  # the remembered merge was the old report's
    probe.observe_report(migrated, READER, card_id)
    assert len(_events(migrated, "task_merged")) == 1  # the new report's own observation


def test_it_wakes_the_done_authority_only_and_nobody_once_closed() -> None:
    from types import SimpleNamespace

    def row(authority: str, closed: bool) -> Any:
        return SimpleNamespace(
            kind="task_merged",
            payload={"done_authority": authority, "closed": closed},
            audience=["role:reviewer", "instance:agt-h#ab12", "trust:admin"],
            actor_membership=None,
            actor_credential_id=None,
            conversation_id=None,
            wakes=None,
        )

    reviewer = SimpleNamespace(
        id=1, agent_id="agt-r", trust="member", role="reviewer", role_base="reviewer"
    )
    holder = SimpleNamespace(
        id=2, agent_id="agt-h", trust="member", role="coder", role_base="coder"
    )
    admin = SimpleNamespace(id=3, agent_id=None, trust="admin", role="coder", role_base="coder")
    assert events.wakes(row("reviewer", False), reviewer, "agt-r", instance="cd34")
    assert not events.wakes(row("reviewer", False), holder, "agt-h", instance="ab12")
    assert not events.wakes(row("reviewer", True), reviewer, "agt-r", instance="cd34")
    holder_row = row("holder", False)
    assert events.wakes(holder_row, holder, "agt-h", instance="ab12")
    assert not events.wakes(holder_row, reviewer, "agt-r", instance="cd34")
    assert events.wakes(row("admin", False), admin, "hum-a")


def test_a_team_wake_rule_still_picks_the_instances() -> None:
    """Within the done authority, `row.wakes` narrows to the chosen instances (§5.3)."""
    from types import SimpleNamespace

    row = SimpleNamespace(
        kind="task_merged",
        payload={"done_authority": "reviewer", "closed": False},
        audience=["role:reviewer", "trust:admin"],
        actor_membership=None,
        actor_credential_id=None,
        conversation_id=None,
        wakes={"agt-r": ["lead"]},
    )
    reviewer = SimpleNamespace(
        id=1, agent_id="agt-r", trust="member", role="reviewer", role_base="reviewer"
    )
    assert events.wakes(row, reviewer, "agt-r", instance="lead")
    assert not events.wakes(row, reviewer, "agt-r", instance="other")


# --- outsiders' work (§2.3 "Own approvals"; tsk-997vnv5efkw9) -----------------------------------


def _owned_by(engine: Engine, agent_id: str, human_id: str) -> None:
    """The agent's profile now belongs to `human_id` (an owner outside the project or not)."""
    with engine.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == agent_id)
            .values(owner_id=human_id)
        )


def _stranger(make_client: ClientFactory, engine: Engine) -> flow.Human:
    """A human who holds no membership of the project."""
    return flow.human(make_client, engine, "stranger")


def test_auto_never_closes_outsiders_work_on_a_merge(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.6: `auto` acts as `notify` on outsiders' work without its own approvals on the
    reported head: with none given, the merge leaves the card for its done authority."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    _owned_by(migrated, agent.id, _stranger(make_client, migrated).id)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert (told.payload["closed"], told.payload["blocked_by"]) == (False, ["own_approvals"])
    assert _card(owner, card_id)["status"] == "review"
    assert any(agent.id in x for x in told.audience)  # the done authority under `holder`


def test_auto_closes_outsiders_work_once_it_has_its_own_approval(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """§6.6: with its own approvals on the reported head, a merge under `auto` closes
    outsiders' work as any other card (tsk-3ggnhdmgmkf3)."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    _owned_by(migrated, agent.id, _stranger(make_client, migrated).id)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    approved = reviewer.post(
        f"{BASE}/events",
        {
            "kind": "message",
            "type": "review_result",
            "to": "all",
            "body": "Approved.",
            "task_id": card_id,
            "review": {
                "subject": "#7",
                "head": _report()["head"],
                "verdict": "approve",
                "cites": [{"path": "docs/api.md", "line": 1, "quote": "x"}],
            },
        },
    )
    assert approved.status_code == 201, approved.text
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is True and "blocked_by" not in told.payload
    assert _card(owner, card_id)["status"] == "done"


def test_auto_never_closes_a_card_whose_current_report_an_outsider_filed(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Outsiders' work is also a card whose current report an outside agent filed, while
    one of the project's own holds it (§2.3)."""
    _policy(owner, done_authority="admin", merged_closes="auto")
    github.pull(7, merged=True)
    _, card_id = _reported(github, owner, make_client)
    outsider = flow.agent(make_client, owner)
    _owned_by(migrated, outsider.id, _stranger(make_client, migrated).id)
    with migrated.begin() as conn:
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == card_id)).scalar_one()
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id)
            .values(report={**report, "reported_by": outsider.id})
        )
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert (told.payload["closed"], told.payload["blocked_by"]) == (False, ["own_approvals"])
    assert _card(owner, card_id)["status"] == "review"


def test_auto_judges_outsiders_work_as_the_members_stand_at_the_merge(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Judged at each check (§2.3): an agent whose owner is a member when the merge is
    seen is the project's own, and `auto` closes its card as before."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    agent, card_id = _reported(github, owner, make_client)
    stranger = _stranger(make_client, migrated)
    _owned_by(migrated, agent.id, stranger.id)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=stranger.id)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is True and "blocked_by" not in told.payload
    assert _card(owner, card_id)["status"] == "done"


def test_auto_never_closes_a_card_an_outsider_holds_while_an_own_agent_reported(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """The holder alone makes it outsiders' work (§2.3), whoever filed the current report
    (review A2214 of #2136)."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    holder, card_id = _reported(github, owner, make_client)
    own = flow.agent(make_client, owner)
    with migrated.begin() as conn:
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == card_id)).scalar_one()
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id)
            .values(report={**report, "reported_by": own.id})
        )
    _owned_by(migrated, holder.id, _stranger(make_client, migrated).id)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert (told.payload["closed"], told.payload["blocked_by"]) == (False, ["own_approvals"])
    assert _card(owner, card_id)["status"] == "review"


def test_auto_closes_a_card_a_human_member_holds_and_reported(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """A human holder or reporter is never an outside agent (review A2214 of #2136)."""
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    card = owner.post(f"{BASE}/tasks", {"title": "A card"}).json()
    github.name(7, card["id"])
    assert owner.post(f"{BASE}/tasks/{card['id']}/claim", {}).status_code == 200
    stored = owner.post(f"{BASE}/tasks/{card['id']}/report", _report())
    assert stored.status_code == 200, stored.text
    probe.observe_report(migrated, READER, card["id"])
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is True and "blocked_by" not in told.payload


def test_an_agent_without_a_profile_counts_as_an_outsider(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Nothing shows such an agent is the project's own, so its report keeps the card open."""
    _, card_id = _reported(github, owner, make_client)
    with migrated.begin() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
        project = conn.execute(select(t.project)).one()
        changed = SimpleNamespace(
            claim_holder=None, report={**card.report, "reported_by": "agt-gone"}
        )
        assert merged.outsiders_work(conn, changed, project)
        assert not merged.outsiders_work(conn, card, project)
