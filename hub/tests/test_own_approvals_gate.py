"""docs/api.md §2.3 "Own approvals", §6.4, §6.6: outsiders' work reaches `done` only with
`policy.own_approvals` own approvals on its reported head, on every path to done and under
every `done_authority` (tsk-3ggnhdmgmkf3, PR 2). An outside agent has trust `outside` or the
`joined_outside` mark on its current membership, or an owner who holds no membership; most tests
make one by giving an agent's profile to a stranger, and the others set the trust or the mark."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import own_approvals, review_delivery
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


def test_the_holders_move_from_in_progress_passes_once_the_approval_is_there(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The gate refuses the move from `in_progress` without an own approval (above) and lets
    it through with one on the reported head (#2145 review A2429)."""
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    back = outsider.patch(f"{PROJECT}/tasks/{card_id}", {"status": "in_progress"})
    assert back.status_code == 200, back.text
    assert _status(owner, card_id) == "in_progress"
    assert _done(outsider, card_id).status_code == 200
    assert _status(owner, card_id) == "done"


def test_a_done_report_from_an_outside_holder_is_stored_and_goes_to_review(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    stored = _reported(outsider, card_id, done=True)
    assert stored.json()["status"] == "review"
    assert stored.json()["report"]["head"] == SHA


def test_a_done_report_finds_an_approval_that_names_only_its_new_pull_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A review result tied to the card only by its subject `#<n>` is matched against the
    report the `done` brings, not the one it replaces."""
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)  # pull request 7
    reviewer = flow.agent(make_client, owner, role="reviewer")
    sent = reviewer.post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "review_result",
            "to": "all",
            "body": "Reviewed.",
            "review": {"subject": "#8", "head": SHA, "verdict": "approve", "cites": [CITE]},
        },
    )
    assert sent.status_code == 201, sent.text
    pr = {"number": 8, "url": "https://github.com/acme/maity/pull/8", "head": SHA, "state": "open"}
    again = outsider.post(f"{PROJECT}/tasks/{card_id}/report", _report(pr=pr, done=True))
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "done"


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


def test_a_later_comment_withdraws_an_approve_too(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Each author's latest result decides: a `comment` after an `approve` takes it back as a
    `changes` does (#2145 review A2429)."""
    _policy(owner, done_authority="reviewer")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    judge = flow.agent(make_client, owner, role="reviewer")
    _review(judge, card_id)
    assert _count(migrated, card_id) == 1
    _review(judge, card_id, verdict="comment")
    assert _count(migrated, card_id) == 0
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


def test_a_done_report_on_a_blocked_card_short_of_approvals_keeps_it_blocked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A closing report on a `blocked` card short of its own approvals is stored; the card
    stays blocked and returns to `review`, not `done`, once its answer comes (§7; #2145
    review A2429)."""
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    assert outsider.post(f"{PROJECT}/tasks/{card_id}/claim", {}).status_code == 200
    asked = outsider.post(
        f"{PROJECT}/requests",
        {"class": "decision", "title": "Which?", "task_id": card_id, "while_open": "wait"},
    )
    assert asked.status_code == 201, asked.text
    assert _status(owner, card_id) == "blocked"
    stored = outsider.post(f"{PROJECT}/tasks/{card_id}/report", _report(done=True))
    assert stored.status_code == 200, stored.text
    assert stored.json()["status"] == "blocked"
    with migrated.connect() as conn:
        before = conn.execute(
            select(t.card.c.status_before_block).where(t.card.c.id == card_id)
        ).scalar_one()
    assert before == "review"


# --- what counts -----------------------------------------------------------------------------


def _count(engine: Engine, card_id: str) -> int:
    with engine.connect() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
        project = conn.execute(select(t.project)).one()
        return own_approvals.counted(conn, card, project)


def _row(engine: Engine, agent_id: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.agent_id == agent_id, t.membership.c.removed_at.is_(None)
            )
        ).scalar_one()
    return found


def _rejoined(engine: Engine, agent_id: str, role: str = "reviewer") -> int:
    """The agent's row removed (§6.2: it stays, with its dates) and a member's fresh join of
    the same agent: a new row, neither `outside` nor marked."""
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent_id, t.membership.c.removed_at.is_(None))
            .values(active=None, removed_at=factory.at("2026-11-20T10:00:00Z"))
        )
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    return factory.membership(engine, project_id, role, agent_id=agent_id)


def _last_result(engine: Engine, card_id: str) -> int:
    with engine.connect() as conn:
        seq: int = (
            conn.execute(
                select(t.event.c.seq)
                .where(t.event.c.kind == "message", t.event.c.subject_id == card_id)
                .order_by(t.event.c.seq.desc())
                .limit(1)
            )
            .scalars()
            .one()
        )
    return seq


def _set_event(engine: Engine, seq: int, **values: Any) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.event).where(t.event.c.seq == seq).values(**values))


def _outsiders_card(owner: flow.Human, make_client: ClientFactory, engine: Engine) -> str:
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, engine, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    return card_id


def test_the_hub_records_whether_a_review_results_author_stood_as_a_signer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card_id = _outsiders_card(owner, make_client, migrated)
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    reviewer_seq = _last_result(migrated, card_id)
    _review(flow.agent(make_client, owner, role="coder"), card_id)
    coder_seq = _last_result(migrated, card_id)
    with migrated.connect() as conn:
        rows = dict(
            conn.execute(
                select(t.event.c.seq, t.event.c.review_signer).where(
                    t.event.c.seq.in_([reviewer_seq, coder_seq])
                )
            ).all()
        )
    assert rows == {reviewer_seq: True, coder_seq: False}


def test_an_approve_sent_before_its_author_could_sign_never_counts(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Promoted in place after the `approve`: the standing is the one recorded when the hub
    stored it, not reconstructed from the row as it is now."""
    card_id = _outsiders_card(owner, make_client, migrated)
    judge = flow.agent(make_client, owner, role="coder")
    _review(judge, card_id)
    row = _row(migrated, judge.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == row)
            .values(role="reviewer", role_base="reviewer")
        )
    assert _count(migrated, card_id) == 0


def test_an_approve_without_a_recorded_standing_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A result the hub stored before it kept the record (the upgrade sets none)."""
    card_id = _outsiders_card(owner, make_client, migrated)
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    assert _count(migrated, card_id) == 1
    _set_event(migrated, _last_result(migrated, card_id), review_signer=None)
    assert _count(migrated, card_id) == 0


def test_an_approve_sent_through_a_bridge_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card_id = _outsiders_card(owner, make_client, migrated)
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    assert _count(migrated, card_id) == 1
    bridge = {"member_id": "agt-bridge", "instance": "br01", "bridge_id": "brg-x"}
    _set_event(migrated, _last_result(migrated, card_id), actor_bridge=bridge)
    assert _count(migrated, card_id) == 0


def test_a_review_result_posted_through_a_bridge_is_recorded_as_no_signers(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A reviewer agent's `approve` sent for it by a bridge (`Maity-For`, §2.3): stored, read
    as the served agent's, and recorded as no signer's, so it counts nothing."""
    from tests.test_bridge_calls import Calls

    card_id = _outsiders_card(owner, make_client, migrated)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    served = factory.agent(migrated, project_id, owner.id, "reviewer")
    bridge = factory.agent(migrated, project_id, owner.id, "coder", instance="brg1")
    made = owner.post(
        f"{PROJECT}/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "reviews for the reviewer"},
    )
    assert made.status_code == 201, made.text
    sent = Calls(make_client(), bridge).post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "review_result",
            "to": "all",
            "body": "Reviewed.",
            "task_id": card_id,
            "review": {"subject": "#7", "head": SHA, "verdict": "approve", "cites": [CITE]},
        },
        served.agent_id,
    )
    assert sent.status_code == 201, sent.text
    with migrated.connect() as conn:
        signer = conn.execute(
            select(t.event.c.review_signer).where(t.event.c.seq == int(sent.json()["seq"]))
        ).scalar_one()
    assert signer is False
    assert _count(migrated, card_id) == 0


def test_a_removal_and_rejoin_leave_no_earlier_approve(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card_id = _outsiders_card(owner, make_client, migrated)
    judge = flow.agent(make_client, owner, role="reviewer")
    _review(judge, card_id)
    assert _count(migrated, card_id) == 1
    _rejoined(migrated, judge.id)
    assert _count(migrated, card_id) == 0


def _redact(owner: flow.Human, seq: int) -> None:
    """Through the route (§8.5): the tombstone replaces the payload."""
    done = owner.post(f"{PROJECT}/events/{seq}/redact", {"reason": "said too much"})
    assert done.status_code == 200, done.text


def test_a_redacted_later_result_still_withdraws_the_approve(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card_id = _outsiders_card(owner, make_client, migrated)
    judge = flow.agent(make_client, owner, role="reviewer")
    _review(judge, card_id)
    _review(judge, card_id, verdict="changes")
    _redact(owner, _last_result(migrated, card_id))
    assert _count(migrated, card_id) == 0


def test_a_redacted_later_result_named_by_its_pull_request_alone_withdraws_too(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card_id = _outsiders_card(owner, make_client, migrated)
    judge = flow.agent(make_client, owner, role="reviewer")
    _subject_only(judge)
    assert _count(migrated, card_id) == 1
    _subject_only(judge, verdict="changes")
    with migrated.connect() as conn:
        last = conn.execute(
            select(t.event.c.seq)
            .where(t.event.c.kind == "message", t.event.c.review_pr == 7)
            .order_by(t.event.c.seq.desc())
            .limit(1)
        ).scalar_one()
    _redact(owner, int(last))
    assert _count(migrated, card_id) == 0


def test_a_redacted_approve_counts_nothing_however_it_was_tied(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card_id = _outsiders_card(owner, make_client, migrated)
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    _redact(owner, _last_result(migrated, card_id))
    assert _count(migrated, card_id) == 0


def test_the_count_reads_the_cards_results_through_their_two_indexes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The read is bounded by the card's own results: each query on `event` seeks
    `ix_event_subject` or `ix_event_review_pr`, never scans the project's messages (checked
    with SQLite's planner on the statements the count runs)."""
    from sqlalchemy import event as sa_event

    card_id = _outsiders_card(owner, make_client, migrated)
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    seen: list[tuple[str, Any]] = []

    def capture(conn: Any, cursor: Any, statement: str, params: Any, *_: Any) -> None:
        if "FROM event" in statement and "review_signer" in statement:
            seen.append((statement, params))

    sa_event.listen(migrated, "before_cursor_execute", capture)
    try:
        assert _count(migrated, card_id) == 1
    finally:
        sa_event.remove(migrated, "before_cursor_execute", capture)
    assert len(seen) == 2  # one tied by the card, one named by its pull request
    assert all(" OR " not in statement for statement, _ in seen)
    assert sum("subject_type" in statement for statement, _ in seen) == 1
    assert sum("review_pr =" in statement for statement, _ in seen) == 1
    if migrated.dialect.name != "sqlite":
        return  # the plan is asked of SQLite's planner; the shape above holds everywhere
    used: set[str] = set()
    with migrated.connect() as conn:
        for statement, params in seen:
            plan = str(conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", params).all())
            used |= {name for name in ("ix_event_subject", "ix_event_review_pr") if name in plan}
    assert used == {"ix_event_subject", "ix_event_review_pr"}


def test_a_report_naming_a_pull_request_beyond_the_column_still_counts(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A report may name any pull request number from 1; one wider than the recorded column
    is no result's, and the count still answers instead of failing."""
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    huge = 2_147_483_648
    pr = {"number": huge, "url": f"https://github.com/acme/maity/pull/{huge}", "head": SHA}
    _reported(outsider, card_id, pr={**pr, "state": "open"})
    _refused(_done(outsider, card_id))
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    assert _done(outsider, card_id).status_code == 200


def test_a_suspended_human_neither_approves_nor_makes_its_agents_own(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card_id = _outsiders_card(owner, make_client, migrated)
    member = _human_member(make_client, migrated, "soon-away", "reviewer")
    _review(member, card_id)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    agent_id = factory.agent(migrated, project_id, member.id, "reviewer").agent_id
    assert _count(migrated, card_id) == 1
    with migrated.begin() as conn:
        conn.execute(
            update(t.human)
            .where(t.human.c.id == member.id)
            .values(suspended_at=factory.at("2026-11-22T10:00:00Z"))
        )
    assert _count(migrated, card_id) == 0
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert not own_approvals._own_agent(conn, project, agent_id, set())


@pytest.mark.parametrize("gone", ["suspended_at", "deleted_at"])
def test_an_agent_whose_owner_is_suspended_or_deleted_counts_as_outside(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, gone: str
) -> None:
    """Its card is outsiders' work and its move to `done` is gated, failing closed (the lead's
    ruling of 2026-11-23)."""
    _policy(owner, done_authority="admin")
    member = _human_member(make_client, migrated, f"will-be-{gone[:4]}", "coder")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    agent_id = factory.agent(migrated, project_id, member.id, "coder").agent_id
    card_id = _card(owner)
    with migrated.begin() as conn:  # it holds the card and reported it
        holder = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent_id)
        ).scalar_one()
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id)
            .values(
                status="review",
                claim_holder=holder,
                report={"head": SHA, "reported_by": agent_id, "revision": 1},
            )
        )
    with migrated.connect() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
        project = conn.execute(select(t.project)).one()
        assert not own_approvals.outsiders_work(conn, card, project)
    with migrated.begin() as conn:
        conn.execute(
            update(t.human)
            .where(t.human.c.id == member.id)
            .values(**{gone: factory.at("2026-11-22T10:00:00Z")})
        )
    with migrated.connect() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
        project = conn.execute(select(t.project)).one()
        assert own_approvals.outside_agent(conn, project, agent_id)
        assert own_approvals.missing(conn, card, project) == (1, 0)


def test_a_signature_counts_only_for_the_slot_its_signer_still_may_sign(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A human reviewer's review signature, then moved to tester: still of the project, but
    the review signature no longer stands (§6.4)."""
    _policy(owner, done_authority="reviewer_and_tester")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    reviewer = _human_member(make_client, migrated, "moved-on", "reviewer")
    assert _done(reviewer, card_id, approve="review").status_code == 200
    assert _count(migrated, card_id) == 1
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == reviewer.id)
            .values(role="tester", role_base="tester")
        )
    assert _count(migrated, card_id) == 0


def test_an_approve_counts_only_while_its_author_may_review_or_test(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """An own agent that no longer reviews or tests (here demoted to coder) gives no own
    approval, as a signature would not stand (§6.4)."""
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    judge = flow.agent(make_client, owner, role="reviewer")
    _review(judge, card_id)
    assert _count(migrated, card_id) == 1
    row = _row(migrated, judge.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == row)
            .values(role="coder", role_base="coder")
        )
    assert _count(migrated, card_id) == 0


def test_a_later_result_withdraws_an_approve_across_a_rejoin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The latest result is the author's, not its membership row's: a `changes` sent from a
    later membership withdraws the `approve` sent from an earlier one."""
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    judge = flow.agent(make_client, owner, role="reviewer")
    _review(judge, card_id)
    _review(judge, card_id, verdict="changes")
    later = _rejoined(migrated, judge.id)
    with migrated.begin() as conn:  # the `changes` came from the new row
        last = conn.execute(
            select(t.event.c.seq)
            .where(t.event.c.kind == "message", t.event.c.subject_id == card_id)
            .order_by(t.event.c.seq.desc())
        ).first()
        assert last is not None
        conn.execute(
            update(t.event).where(t.event.c.seq == last.seq).values(actor_membership=later)
        )
    assert _count(migrated, card_id) == 0


def test_an_approve_from_an_outside_membership_never_becomes_an_own_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """An agent that sent its `approve` while it was outside (its membership marked) and later
    joined afresh as a member's agent: the old `approve` stays an outsider's (the lead's
    ruling of 2026-11-23)."""
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    judge = flow.agent(make_client, owner, role="reviewer")
    row = _row(migrated, judge.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == row).values(joined_outside=True)
        )
    _review(judge, card_id)
    _rejoined(migrated, judge.id)
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert not own_approvals.outside_agent(conn, project, judge.id)  # its own now
    assert _count(migrated, card_id) == 0


def test_a_signature_counts_only_for_the_report_it_was_given_on(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="reviewer_and_tester")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    reviewer = flow.human(make_client, migrated, "human-reviewer")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "reviewer", human_id=reviewer.id)
    assert _done(reviewer, card_id, approve="review").status_code == 200
    assert _count(migrated, card_id) == 1
    with migrated.begin() as conn:  # a later report on the card, the signature left in place
        report = conn.execute(select(t.card.c.report).where(t.card.c.id == card_id)).scalar_one()
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id)
            .values(report={**report, "revision": int(report.get("revision") or 1) + 1})
        )
    assert _count(migrated, card_id) == 0


def test_a_signature_whose_signer_no_longer_stands_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="reviewer_and_tester")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    reviewer = flow.human(make_client, migrated, "leaving-reviewer")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "reviewer", human_id=reviewer.id)
    assert _done(reviewer, card_id, approve="review").status_code == 200
    with migrated.begin() as conn:  # isolated, its signature left on the card
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == reviewer.id)
            .values(isolated_since=factory.at("2026-11-21T10:00:00Z"))
        )
    assert _count(migrated, card_id) == 0


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


def test_the_mark_belongs_to_its_row_and_a_members_rejoin_makes_the_agent_its_own(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.3's one way out of outside: removal, then a member's fresh join, a new row without
    the mark. While the marked row is the agent's membership, the agent stays outside, its
    owner a member or not (the lead's ruling of 2026-11-23: the row the check is about)."""
    member = flow.human(make_client, migrated, "came-in")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "coder", human_id=member.id)
    agent_id = factory.agent(migrated, project_id, member.id, "coder").agent_id
    with migrated.begin() as conn:  # it joined while its owner was no member
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent_id)
            .values(joined_outside=True)
        )

    def outside() -> bool:
        with migrated.connect() as conn:
            project = conn.execute(select(t.project)).one()
            return own_approvals.outside_agent(conn, project, agent_id)

    assert outside()  # its owner a member now, the marked row still its membership
    with migrated.begin() as conn:  # removed (§6.2: the row stays, with its dates)
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent_id)
            .values(active=None, removed_at=factory.at("2026-11-20T10:00:00Z"))
        )
    assert outside()  # a reporter who left: its most recent row is still the marked one
    factory.membership(migrated, project_id, "coder", agent_id=agent_id)  # a member's join
    assert not outside()


def _subject_only(who: Any, subject: str = "#7", verdict: str = "approve") -> None:
    """A review result tied to the card only by its pull request (§8.4), no `task_id`."""
    sent = who.post(
        f"{PROJECT}/events",
        {
            "kind": "message",
            "type": "review_result",
            "to": "all",
            "body": "Reviewed.",
            "review": {"subject": subject, "head": SHA, "verdict": verdict, "cites": [CITE]},
        },
    )
    assert sent.status_code == 201, sent.text


def _human_member(make_client: ClientFactory, engine: Engine, handle: str, role: str) -> Any:
    human = flow.human(make_client, engine, handle)
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(engine, project_id, role, human_id=human.id)
    return human


def test_the_pull_request_is_resolved_once_however_many_results_name_it(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2145 review A2429: results named by their pull request alone all name the card's own
    pull request, so whether it is this card's is asked once per count, not once per result
    (the resolution reads the project's reported cards). One count resolves it once, for one
    such result as for three; with none, not at all."""
    card_id = _outsiders_card(owner, make_client, migrated)
    real = review_delivery._card
    calls: list[str] = []

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append("resolve")
        return real(*args, **kwargs)

    monkeypatch.setattr(review_delivery, "_card", counted)
    assert _count(migrated, card_id) == 0 and calls == []  # no such result: no resolution
    for role in ("reviewer", "reviewer", "tester"):
        _subject_only(flow.agent(make_client, owner, role=role))
    calls.clear()
    assert _count(migrated, card_id) == 3
    assert calls == ["resolve"]


def test_an_approval_named_by_its_pull_request_alone_counts_on_a_move(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    _subject_only(flow.agent(make_client, owner, role="reviewer"))
    assert _done(outsider, card_id).status_code == 200


def test_without_done_authority_the_scope_refusal_comes_first(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The gate decides only for a caller that has done authority: anyone else is refused
    for that, as on any card, and learns nothing about the approvals."""
    _policy(owner, done_authority="reviewer")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    refused = _done(outsider, card_id)
    assert refused.status_code == 403, refused.text
    details = refused.json()["error"]["details"]
    assert "scope" in details and details.get("reason") != "own_approvals"


def test_a_human_counts_once_whatever_the_ways_it_approved(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="admin", own_approvals=2)
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    _review(owner, card_id)  # a review result, and then its own move
    _refused(_done(owner, card_id), needed=2, counted=1)


def test_a_human_who_neither_reviews_nor_tests_gives_no_own_approval(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    _review(_human_member(make_client, migrated, "a-coder", "coder"), card_id)
    assert _count(migrated, card_id) == 0
    _review(_human_member(make_client, migrated, "a-reviewer", "reviewer"), card_id)
    assert _count(migrated, card_id) == 1


def test_a_redacted_approve_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    _review(flow.agent(make_client, owner, role="reviewer"), card_id)
    assert _count(migrated, card_id) == 1
    with migrated.begin() as conn:
        conn.execute(
            update(t.event)
            .where(t.event.c.kind == "message", t.event.c.subject_id == card_id)
            .values(redacted=True)
        )
    assert _count(migrated, card_id) == 0


def test_an_agent_with_trust_outside_is_outside_and_its_approve_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Trust `outside` on the agent's own row, its owner a member (here the project's
    owner): outside all the same (§2.3)."""
    _policy(owner, done_authority="admin")
    holder = flow.agent(make_client, owner)
    judge = flow.agent(make_client, owner, role="reviewer")
    card_id = _card(owner)
    _reported(holder, card_id)
    _review(judge, card_id)
    row = _row(migrated, judge.id)
    with migrated.begin() as conn:
        conn.execute(update(t.membership).where(t.membership.c.id == row).values(trust="outside"))
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert own_approvals.outside_agent(conn, project, judge.id)
    assert _count(migrated, card_id) == 0


def test_moves_other_than_to_done_are_not_gated(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="holder")
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    back = outsider.patch(f"{PROJECT}/tasks/{card_id}", {"status": "in_progress"})
    assert back.status_code == 200, back.text
    cancelled = owner.patch(f"{PROJECT}/tasks/{card_id}", {"status": "cancelled"})
    assert cancelled.status_code == 200, cancelled.text


def test_own_agents_owners_of_counts_only_the_picked_members_agents(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    picked = _human_member(make_client, migrated, "picked", "coder")
    other = _human_member(make_client, migrated, "unpicked", "coder")
    _policy(owner, done_authority="admin", own_agents={"owners_of": ["picked"]})
    outsider = _outside(make_client, migrated, owner)
    card_id = _card(owner)
    _reported(outsider, card_id)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    others = factory.agent(migrated, project_id, other.id, "reviewer").agent_id
    pickeds = factory.agent(migrated, project_id, picked.id, "reviewer").agent_id
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert not own_approvals._own_agent(conn, project, others, set())
        assert own_approvals._own_agent(conn, project, pickeds, set())


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
