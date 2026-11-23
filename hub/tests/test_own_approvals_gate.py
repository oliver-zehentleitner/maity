"""docs/api.md §2.3 "Own approvals", §6.4, §6.6: outsiders' work reaches `done` only with
`policy.own_approvals` own approvals on its reported head, on every path to done and under
every `done_authority` (tsk-3ggnhdmgmkf3, PR 2). An outside agent here is one whose owner holds
no membership; the tests make one by giving an agent's profile to a stranger."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import own_approvals
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_probe import SHA, _report

PROJECT = "/projects/maintainer/maity"
OTHER = "f" * 40
CITE = {"path": "docs/api.md", "line": 1, "quote": "x"}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _policy(owner: flow.Human, **policy: Any) -> None:
    done = owner.patch(PROJECT, {"policy": policy, "reason": "own approvals"})
    assert done.status_code == 200, done.text


def _outside(make_client: ClientFactory, engine: Engine, owner: flow.Human, **join: Any) -> Any:
    """An agent of the project whose profile now belongs to a human who is no member."""
    agent = flow.agent(make_client, owner, **join)
    stranger = flow.human(make_client, engine, f"stranger-{agent.id[-6:]}")
    with engine.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == agent.id)
            .values(owner_id=stranger.id)
        )
    return agent


def _card(owner: flow.Human) -> str:
    card: str = owner.post(f"{PROJECT}/tasks", {"title": "A card"}).json()["id"]
    return card


def _reported(who: Any, card_id: str, **report: Any) -> Any:
    assert who.post(f"{PROJECT}/tasks/{card_id}/claim", {}).status_code == 200
    stored = who.post(f"{PROJECT}/tasks/{card_id}/report", _report(**report))
    assert stored.status_code == 200, stored.text
    return stored


def _review(who: Any, card_id: str, verdict: str = "approve", head: str = SHA) -> None:
    sent = who.post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "review_result",
            "to": "all",
            "body": "Reviewed.",
            "task_id": card_id,
            "review": {"subject": "#7", "head": head, "verdict": verdict, "cites": [CITE]},
        },
    )
    assert sent.status_code == 201, sent.text


def _done(who: Any, card_id: str, **more: Any) -> Any:
    return who.patch(f"{PROJECT}/tasks/{card_id}", {"status": "done", **more})


def _refused(answer: Any, needed: int = 1, counted: int = 0) -> None:
    assert answer.status_code == 403, answer.text
    details = answer.json()["error"]["details"]
    assert details == {"reason": "own_approvals", "needed": needed, "counted": counted}


def _status(owner: flow.Human, card_id: str) -> str:
    status: str = owner.get(f"{PROJECT}/tasks/{card_id}").json()["status"]
    return status


# --- done_authority: holder ---------------------------------------------------------------


def test_an_outside_holder_moves_its_own_card_to_done_only_with_an_own_approval(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    _refused(_done(outsider, card_id))
    assert _status(owner, card_id) == "review"  # nothing changed
    reviewer = flow.agent(make_client, owner, role="reviewer")
    _review(reviewer, card_id)
    assert _done(outsider, card_id).status_code == 200
    assert _status(owner, card_id) == "done"


def test_the_holders_move_from_in_progress_is_gated_too(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    assert outsider.post(f"{PROJECT}/tasks/{card_id}/claim", {}).status_code == 200
    _refused(_done(outsider, card_id))
    assert _status(owner, card_id) == "in_progress"


def test_a_done_report_from_an_outside_holder_is_stored_and_goes_to_review(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    stored = _reported(outsider, card_id, done=True)
    assert stored.json()["status"] == "review"
    assert stored.json()["report"]["head"] == SHA


# --- the done authority is a role, a human or an admin --------------------------------------


@pytest.mark.parametrize("authority", ["reviewer", "tester"])
def test_the_done_authority_needs_the_approval_on_the_reported_head(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, authority: str
) -> None:
    _policy(owner, done_authority=authority)
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    judge = flow.agent(make_client, owner, role=authority)
    _refused(_done(judge, card_id))  # an agent's own move is no approval
    _review(judge, card_id, head=OTHER)  # another head counts for nothing
    _refused(_done(judge, card_id))
    _review(judge, card_id)
    assert _done(judge, card_id).status_code == 200


def test_a_later_changes_withdraws_an_approve(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="reviewer")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    judge = flow.agent(make_client, owner, role="reviewer")
    _review(judge, card_id)
    _review(judge, card_id, verdict="changes")
    _refused(_done(judge, card_id))


def test_an_owners_own_move_counts_as_its_approval(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    assert _done(owner, card_id).status_code == 200


def test_two_signatures_of_agents_need_an_own_approval_besides(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Under `reviewer_and_tester` the signature that would complete `approvals` is gated; an
    agent's signature is no own approval, a human's is (§2.3)."""
    _policy(owner, done_authority="reviewer_and_tester", own_approvals=2)
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    tester = flow.agent(make_client, owner, role="tester")
    assert _done(reviewer, card_id, approve="review").status_code == 200  # one signature
    _refused(_done(tester, card_id, approve="test"), needed=2, counted=0)
    _review(reviewer, card_id)
    _refused(_done(tester, card_id, approve="test"), needed=2, counted=1)
    _review(tester, card_id)
    assert _done(tester, card_id, approve="test").status_code == 200
    assert _status(owner, card_id) == "done"


def test_a_merged_card_blocked_from_review_is_gated_too(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    with migrated.begin() as conn:
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == card_id)).scalar_one()
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id)
            .values(
                status="blocked",
                status_before_block="review",
                report={**report, "observed": {"pr_state": "merged"}, "mismatch": False},
            )
        )
    _refused(_done(outsider, card_id))
    assert _status(owner, card_id) == "blocked"


# --- what counts -----------------------------------------------------------------------------


def test_neither_an_outsiders_approval_nor_its_owners_counts(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """An outside agent's approve is no own approval; nor is one from an agent of the owner of
    the agent that holds the card, once that owner has become a member (§2.3)."""
    _policy(owner, done_authority="reviewer")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    _review(_outside(make_client, migrated, owner, role="reviewer"), card_id)
    with migrated.connect() as conn:
        stranger = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == outsider.id)
        ).scalar_one()
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "reviewer", human_id=stranger)
    with migrated.begin() as conn:  # it joined as an outsider's agent: it stays one (§2.3)
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == outsider.id)
            .values(joined_outside=True)
        )
    sibling = factory.agent(migrated, project_id, stranger, "reviewer").agent_id
    with migrated.connect() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
        project = conn.execute(select(t.project)).one()
        assert own_approvals.outsiders_work(conn, card, project)
        assert own_approvals.counted(conn, card, project) == 0
        assert own_approvals.counted(conn, card, project, mover=stranger) == 0
        assert not own_approvals._own_agent(conn, project, sibling, {stranger})


def test_own_agents_owners_counts_only_the_agents_of_owners(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="reviewer", own_agents="owners")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    member = flow.human(make_client, migrated, "member")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "coder", human_id=member.id)
    members_agent = factory.agent(migrated, project_id, member.id, "reviewer")
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert not own_approvals._own_agent(conn, project, members_agent.agent_id, set())
    judge = flow.agent(make_client, owner, role="reviewer")  # the owner's agent
    _review(judge, card_id)
    assert _done(judge, card_id).status_code == 200


def test_an_own_members_card_is_not_gated(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    agent = flow.agent(make_client, owner)
    card_id = _card(owner)
    _reported(agent, card_id)
    assert _done(agent, card_id).status_code == 200
