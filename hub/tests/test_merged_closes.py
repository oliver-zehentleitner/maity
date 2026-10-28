"""docs/api.md §6.6 "A merge closes the loop" and §6.1 `merged_closes`: a merge the probe
observes on a card in review wakes the done authority with `task_merged` once per report;
under `auto` with `done_authority` holder or admin the hub closes the card itself unless
a dependency, a child or an objection holds it; a merge seen elsewhere is told when the
card returns to review with the same report."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events, forge, probe
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import READER, REPO, TOKEN, FakeGitHub, _report

BASE = "/projects/maintainer/maity"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, forge_github_token=TOKEN)


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


def test_a_mismatched_merge_triggers_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True, head="e" * 40)
    _, card_id = _reported(owner, make_client)
    probe.observe_report(migrated, READER, card_id)
    assert _events(migrated, "task_merged") == []


def test_a_merge_seen_elsewhere_is_told_when_the_card_returns_to_review(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    """Blocked while a request is open (§7): the merge is remembered and told when the
    answer restores review."""
    github.pull(7, merged=True)
    agent, card_id = _reported(owner, make_client)
    asked = agent.post(
        f"{BASE}/requests", {"class": "decision", "title": "Which?", "task_id": card_id}
    )
    assert asked.status_code == 201, asked.text
    assert _card(owner, card_id)["status"] == "blocked"
    probe.observe_report(migrated, READER, card_id)
    assert _events(migrated, "task_merged") == []  # remembered, not told
    answered = owner.post(f"{BASE}/requests/{asked.json()['id']}/answer", {"text": "go ahead"})
    assert answered.status_code == 200, answered.text
    assert _card(owner, card_id)["status"] == "review"
    [told] = _events(migrated, "task_merged")
    assert told.payload["task"] == card_id and told.payload["merge_sha"] == "f" * 40


def test_a_new_report_in_between_starts_over(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, github: FakeGitHub
) -> None:
    github.pull(7, merged=True)
    agent, card_id = _reported(owner, make_client)
    asked = agent.post(
        f"{BASE}/requests", {"class": "decision", "title": "Which?", "task_id": card_id}
    )
    assert asked.status_code == 201, asked.text
    probe.observe_report(migrated, READER, card_id)  # blocked: remembered
    again = agent.post(f"{BASE}/tasks/{card_id}/report", _report(summary="Reported again."))
    assert again.status_code == 200, again.text
    answered = owner.post(f"{BASE}/requests/{asked.json()['id']}/answer", {"text": "go ahead"})
    assert answered.status_code == 200, answered.text
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

    reviewer = SimpleNamespace(id=1, agent_id="agt-r", role="reviewer")
    holder = SimpleNamespace(id=2, agent_id="agt-h", role="member")
    admin = SimpleNamespace(id=3, agent_id=None, role="admin")
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
    reviewer = SimpleNamespace(id=1, agent_id="agt-r", role="reviewer")
    assert events.wakes(row, reviewer, "agt-r", instance="lead")
    assert not events.wakes(row, reviewer, "agt-r", instance="other")
