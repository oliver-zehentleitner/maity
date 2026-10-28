"""The narrow exception for replacing a done card's report (§6.6)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import _report, task


@pytest.fixture
def setup(
    make_client: ClientFactory, migrated: Engine
) -> tuple[Any, Any, dict[str, Any], dict[str, Any]]:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    card = task(owner)
    agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    body = _report(
        pr_status="found",
        pr={
            "number": 7,
            "url": "https://github.com/a/b/pull/7",
            "head": "d91e294c" + "0" * 32,
            "state": "open",
        },
    )
    assert (
        agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", body).status_code == 200
    )
    result = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "done"})
    assert result.status_code == 200, result.text
    return owner, agent, result.json(), body


@pytest.mark.parametrize("done", [False, True])
@pytest.mark.parametrize("claimless", [False, True])
def test_report_after_done_preserves_closure_and_schedules_probe(
    setup: Any, migrated: Engine, done: bool, claimless: bool
) -> None:
    owner, agent, card, body = setup
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    if claimless:
        with migrated.begin() as conn:
            conn.execute(
                update(t.card)
                .where(t.card.c.id == card["id"])
                .values(
                    claim_holder=None,
                    claim_instance=None,
                    claim_session_id=None,
                    claim_since=None,
                    lease_until=None,
                )
            )
    before = owner.get(path).json()
    scheduled: list[str] = []
    agent.client.app.state.probe = SimpleNamespace(report_stored=scheduled.append)
    sha = "e" * 40
    try:
        result = agent.post(
            path + "/report",
            {
                **body,
                "head": sha,
                "remote_head": sha,
                "pr": {**body["pr"], "head": sha},
                "done": done,
            },
        )
    finally:
        agent.client.app.state.probe = None
    assert result.status_code == 200, result.text
    after = result.json()
    assert {k: after[k] for k in ("status", "closed_at", "claim")} == {
        k: before[k] for k in ("status", "closed_at", "claim")
    }
    assert after["report"]["head"] == sha and after["report"]["observed"] is None
    assert scheduled == [card["id"]]
    with migrated.connect() as conn:
        event = conn.execute(
            select(t.event)
            .where(t.event.c.kind == "task_reported", t.event.c.subject_id == card["id"])
            .order_by(t.event.c.seq.desc())
        ).first()
    assert event is not None
    assert event.payload["head"] == sha


@pytest.mark.parametrize("who", ["owner", "other"])
def test_another_member_is_refused(setup: Any, make_client: ClientFactory, who: str) -> None:
    owner, _, card, body = setup
    caller = owner if who == "owner" else flow.agent(make_client, owner)
    result = caller.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", body)
    assert result.headers["Maity-Error"] == "invalid_transition"


@pytest.mark.parametrize("number", [8, None])
def test_the_same_pr_is_required(setup: Any, number: int | None) -> None:
    _, agent, card, body = setup
    body = (
        {**body, "pr": {**body["pr"], "number": number}}
        if number
        else {**body, "pr": None, "pr_status": "none"}
    )
    result = agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", body)
    assert result.headers["Maity-Error"] == "invalid"


@pytest.mark.parametrize(
    ("observed", "claimed"),
    [
        ({"pr_state": "merged"}, "open"),
        ({"pr_state": "closed"}, "open"),
        (None, "closed"),
        (None, "merged"),
    ],
)
def test_a_terminal_pr_is_refused(
    setup: Any, migrated: Engine, observed: Any, claimed: str
) -> None:
    _, agent, card, body = setup
    report = {
        **card["report"],
        "observed": observed,
        "pr": {**card["report"]["pr"], "state": claimed},
    }
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card["id"]).values(report=report))
    result = agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", body)
    assert result.headers["Maity-Error"] == "invalid_transition"


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_a_terminal_card_without_open_pr_is_refused(
    make_client: ClientFactory, migrated: Engine, status: str
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    card = task(owner)
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    agent.post(path + "/claim", {})
    agent.post(path + "/report", _report())
    assert owner.patch(path, {"status": status}).status_code == 200
    assert agent.post(path + "/report", _report()).headers["Maity-Error"] == "invalid_transition"


def test_cancelled_stays_terminal_even_with_open_pr(setup: Any, migrated: Engine) -> None:
    _, agent, card, body = setup
    with migrated.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card["id"]).values(status="cancelled"))
    result = agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", body)
    assert result.headers["Maity-Error"] == "invalid_transition"
