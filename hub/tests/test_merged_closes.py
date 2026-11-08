"""docs/api.md §6.6 "A merge closes the loop" and §6.1 `merged_closes`: a merge the probe
observes on a card in review wakes the done authority with `task_merged` once per report;
under `auto` with `done_authority` holder or admin the hub closes the card itself unless
a dependency, a child or an objection holds it; a merge seen elsewhere is told when the
card returns to review with the same report."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import events, forge, merged, probe
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import READER, REPO, TOKEN, FakeGitHub, _report

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


def _reported(owner: flow.Human, make_client: ClientFactory, **report: Any) -> tuple[Any, str]:
    agent = flow.agent(make_client, owner)
    card = owner.post(f"{BASE}/tasks", {"title": "A card"}).json()
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
    _, card_id = _reported(owner, make_client)
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
    _, card_id = _reported(owner, make_client)
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
    cards = [_reported(owner, make_client)[1] for _ in range(3)]
    never = _reported(owner, make_client)[1]
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
    _, card_id = _reported(owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is True and "blocked_by" not in told.payload
    assert _card(owner, card_id)["status"] == "done"
    updated = [e for e in _events(migrated, "task_updated") if e.payload.get("id") == card_id]
    assert updated[-1].payload["fields"] == ["status"] and updated[-1].payload["status"] == "done"


def test_auto_under_reviewer_acts_as_notify(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _policy(owner, merged_closes="auto")  # done_authority stays reviewer
    github.pull(7, merged=True)
    _, card_id = _reported(owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    [told] = _events(migrated, "task_merged")
    assert told.payload["closed"] is False and "blocked_by" not in told.payload
    assert _card(owner, card_id)["status"] == "review"


def test_an_open_child_keeps_the_card_in_review_and_says_so(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    _policy(owner, done_authority="holder", merged_closes="auto")
    github.pull(7, merged=True)
    _, card_id = _reported(owner, make_client)
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
    _, card_id = _reported(owner, make_client)
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
    _, card_id = _reported(owner, make_client)
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
    agent, card_id = _reported(owner, make_client)
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
    agent, card_id = _reported(owner, make_client)
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
    agent, card_id = _reported(owner, make_client)
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
    agent, card_id = _reported(owner, make_client)
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
    agent, card_id = _reported(owner, make_client)
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


def test_two_signatures_still_need_review_for_a_blocked_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Under `reviewer_and_tester` a close is two signatures on a card in review (§6.4);
    a blocked card waits for the answer that restores review. Nobody can sign while it is
    blocked, so the merge is remembered, not told, and told on the return to review."""
    _policy(owner, done_authority="reviewer_and_tester")
    github.pull(7, merged=True)
    agent, card_id = _reported(owner, make_client)
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
    agent, card_id = _reported(owner, make_client)
    asked = _blocked(agent, owner, card_id)
    _remembered(migrated, card_id)
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


def test_a_new_report_in_between_starts_over(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    agent, card_id = _reported(owner, make_client)
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
